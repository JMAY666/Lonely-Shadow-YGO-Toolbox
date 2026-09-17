"""Evidence-based reports, with immutable native journal references."""
from collections import Counter
from copy import deepcopy
import json

from protocol import NAMES, PROMPTS, packets, u32, location
from actions import project_actions
from card_semantics import material_method, summon_method
from timeline import route_rows
from review import make_review

REPORT_VERSION = 13

LIMITS = [
    '事件时间为引擎批次采集时间；同批事件用字节偏移确定先后。',
    '连锁结算完成表示引擎完成处理，不代表效果预期目标一定达成。',
    '费用仅依据 REASON_COST 或支付生命值事件；未提供的效果语义标为未知。',
    '卡牌实例依据核心 cardid；事件位置无法唯一匹配时实例为未知。',
    '结束状态来自最后一次核心快照；中断可能丢失尚未落盘的最后一批。',
]


def read_journal(path, session):
    rows, issues, seen = [], [], {}
    if not path.exists(): return rows, issues
    for line_no, line in enumerate(path.read_bytes().splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or type(row.get('seq')) is not int or row['seq'] < 1 or type(row.get('time_ms')) is not int:
                raise ValueError('无效记录结构')
            if row.get('session') != session:
                issues.append(f'已隔离其他会话数据：行 {line_no}'); continue
            seq = row['seq']
            if seq in seen:
                if seen[seq] != row: issues.append(f'冲突的重复序号：{seq}')
                continue
            if rows and seq != rows[-1]['seq'] + 1: issues.append(f'采集序号不连续：{seq}')
            seen[seq] = row; rows.append(row)
        except (ValueError, KeyError, TypeError):
            issues.append(f'未完成或损坏的记录行：{line_no}')
    return rows, issues


def build_report(meta, rows, issues):
    source_count = len(rows)
    rows = route_rows(rows)[0]
    report = deepcopy(meta)
    report.update(events=[], initial_hand=None, final_state=None, loaded_verified=False,
                  warnings=list(issues), limitations=LIMITS, statistics={})
    names = {int(k): v['name'] for k, v in meta.get('catalog', {}).items()}
    state, chains, summoning = {'cards': []}, {}, {}
    turn_started = False
    last_prompt = None
    building_links = {}
    previous_seq = None
    resolution_source = None

    def ref(loc, code=None):
        if loc.get('location', 0) & 0x80:
            hosts = {c['instance_id'] for c in state['cards'] if c['controller'] == loc.get('controller')
                     and c['location'] == (loc['location'] & 0x7f) and c['sequence'] == loc.get('sequence')}
            matches = [c for c in state['cards'] if c.get('overlay_target') in hosts and c['sequence'] == loc.get('position')
                       and (not code or c['code'] == code)]
        else:
            matches = [c for c in state['cards'] if all(c.get(k) == loc.get(k) for k in ('controller', 'location', 'sequence'))
                       and (not code or c['code'] == code)]
        c = matches[0] if len(matches) == 1 else None
        number = code or (c and c['code'])
        return {'code': number, 'name': names.get(number, c.get('name') if c else '未知'),
                'instance_id': c['instance_id'] if c else None, **loc}

    def append(row, msg, offset, **values):
        event = {'id': f"{row['seq']}:{offset}", 'native_seq': row['seq'], 'byte_offset': offset,
                 'time_ms': row['time_ms'], 'message': msg, 'type': NAMES.get(msg, msg),
                 'cards': [], 'effect': None, 'cost': None, 'targets': None, 'result': None, **values}
        report['events'].append(event)
        return event

    def annotate_cause(event, snapshot, destination=None):
        """Only use post-batch reasons for uniquely identified cards at the observed destination."""
        observed = []
        for c in event['cards']:
            match = [x for x in snapshot['cards'] if c.get('instance_id') is not None and x['instance_id'] == c['instance_id']]
            if len(match) != 1: return
            item = match[0]
            if destination and any(item.get(k) != v for k, v in destination.items()): return
            observed.append(item)
        if not observed: return
        reasons = {x.get('reason') for x in observed}
        if len(reasons) == 1: event['observed_reason'] = next(iter(reasons))
        causes = [x.get('reason_effect') for x in observed]
        if causes[0] is not None and all(x == causes[0] for x in causes): event['cause'] = deepcopy(causes[0])

    def snapshot_card(c, snapshot):
        if c.get('instance_id') is None: return None
        matches = [item for item in snapshot['cards'] if item['instance_id'] == c['instance_id'] and item['code'] == c['code']]
        return matches[0] if len(matches) == 1 else None

    def annotate_summon(event, snapshot):
        for c in event['cards']:
            item = snapshot_card(c, snapshot)
            if not item or any(item.get(k) != c.get(k) for k in ('controller', 'location', 'sequence')): continue
            if 'summon_info' in item:
                c.update(summon_info=item['summon_info'], summon_method=summon_method(item['summon_info']),
                         material_instance_ids=item.get('material_instance_ids', []), summon_method_source='core_summon_info')
                c['native_material_cards'] = [{k: m.get(k) for k in ('instance_id','code','name','controller','location','sequence')}
                                              for m in snapshot['cards'] if m['instance_id'] in item.get('material_instance_ids', [])]

    def move_state(c, origin, dest):
        """Maintain instance identity through removals, insertions and same-deck reorders."""
        if c.get('instance_id') is None: return
        own = next((x for x in state['cards'] if x['instance_id'] == c['instance_id']), None)
        if own is None: return
        same_zone = origin['controller'] == dest['controller'] and origin['location'] == dest['location']
        linear = (1, 2, 16, 32, 64)
        for item in state['cards']:
            if item['instance_id'] == c['instance_id']: continue
            at_origin = item['controller'] == origin['controller'] and item['location'] == origin['location']
            at_dest = item['controller'] == dest['controller'] and item['location'] == dest['location']
            if same_zone and origin['location'] in linear:
                if at_origin and dest['sequence'] <= item['sequence'] < origin['sequence']: item['sequence'] += 1
                elif at_origin and origin['sequence'] < item['sequence'] <= dest['sequence']: item['sequence'] -= 1
            elif not same_zone:
                if at_origin and origin['location'] in linear and item['sequence'] > origin['sequence']: item['sequence'] -= 1
                if at_dest and dest['location'] in linear and item['sequence'] >= dest['sequence']: item['sequence'] += 1
        own.update(dest)

    for row in rows:
        if previous_seq is not None and row['seq'] != previous_seq + 1:
            building_links.clear()  # Missing messages could include the end of a cost window.
            resolution_source = None
        previous_seq = row['seq']
        kind = row.get('kind')
        if kind in ('checkpoint', 'rewind', 'branch_restored') and 'state' in row:
            state = deepcopy(row['state'])
        if kind == 'loaded':
            state = deepcopy(row['state'])
            for c in state['cards']: names[c['code']] = c['name']
            report['loaded_verified'] = all(
                Counter(c['code'] for c in state['cards'] if c['controller'] == 0 and c['location'] == loc)
                == Counter(meta['deck'][zone]) for zone, loc in (('main', 1), ('extra', 64)))
            report['loaded_state_ref'] = row['seq']
            if not report['loaded_verified']: report['warnings'].append('引擎实际载入卡牌与构筑不一致')
        if kind == 'response':
            e = append(row, '玩家选择' if row.get('actor') == 'user' else '对手手动选择' if row.get('actor') == 'opponent_manual' else '对手 AI 选择' if row.get('actor') == 'opponent_ai' else '占位方自动跳过', 0,
                       actor=row.get('actor'), raw=row['raw'], prompt_ref=last_prompt and last_prompt['id'], result='等待后续引擎事件确认')
            if last_prompt:
                e['prompt'] = last_prompt.get('message')
                e['choices'] = last_prompt.get('choices')
                try:
                    raw = bytes.fromhex(row['raw'])
                    if e['prompt'] in (15, 20) and raw and raw[0] <= len(raw) - 1:
                        options = last_prompt.get('choices', [])
                        e['cards'] = [options[i] for i in raw[1:1 + raw[0]] if i < len(options)]
                except (ValueError, IndexError): pass
        if kind == 'script_error':
            append(row, '效果脚本错误', 0, result='客户端记录了脚本诊断，请检查本次 native 日志及客户端错误日志')
            report['warnings'].append('本次训练存在脚本诊断，相关效果可能未正常执行')
        if kind == 'batch' or kind == 'branch_restored' and row.get('raw'):
            for c in row['state']['cards']: names[c['code']] = c['name']
            try:
                for offset, msg, b in packets(bytes.fromhex(row['raw'])):
                    e = append(row, msg, offset, raw=b.hex())
                    if msg in PROMPTS:
                        e['actor'] = 'self' if b[0] == 0 else 'wall'
                        last_prompt = e
                    if msg == 50:
                        code, origin, dest, reason = u32(b), location(b, 4), location(b, 8), u32(b, 12)
                        c = ref(origin, code); e.update(cards=[c], origin=origin, destination=dest, reason=reason)
                        e['cost'] = {'reason_cost': True} if reason & 0x80 else None
                        if origin['location'] == dest['location'] == 1 and origin['controller'] == dest['controller']:
                            size = sum(item['controller'] == dest['controller'] and item['location'] == 1 for item in state['cards'])
                            e['deck_operation'] = ('position_refresh' if origin['sequence'] == dest['sequence'] else
                                                   'move_to_bottom' if dest['sequence'] == 0 else
                                                   'move_to_top' if dest['sequence'] == size - 1 else 'reorder')
                        annotate_cause(e, row['state'], {k: dest[k] for k in ('controller', 'location', 'sequence')})
                        if reason & 8:
                            e['material_method'] = material_method(reason)
                            item = snapshot_card(c, row['state'])
                            if item and item.get('reason') == reason:
                                target = item.get('reason_card_instance') or item.get('overlay_target')
                                if target: e['material_target'] = target
                                if dest['location'] & 0x80:
                                    # Overlay addresses encode the host's location, not the material's location.
                                    if item.get('overlay_target'): e['material_target'] = item['overlay_target']
                                    if item.get('reason_effect'): e['cause'] = deepcopy(item['reason_effect'])
                            if not e.get('material_target') and e['material_method'] in ('连接召唤','同调召唤','超量召唤'):
                                cause = e.get('cause') or {}
                                if cause.get('handler_instance'): e['material_target'] = cause['handler_instance']
                        # Some placement messages retain the card's previous draw reason. This metadata is only corroboration.
                        if e.get('observed_reason') != reason: e.pop('cause', None)
                        move_state(c, origin, dest)
                    elif msg == 90:
                        player, count = b[:2]; e['actor'] = 'self' if player == 0 else 'wall'
                        e['cards'] = []
                        for i in range(count):
                            code = u32(b, 2 + i * 4) & 0x7fffffff
                            deck_cards = [c for c in state['cards'] if c['controller'] == player and c['location'] == 1]
                            top = max(deck_cards, key=lambda c: c['sequence']) if deck_cards else None
                            c = ref({'controller': player, 'location': 1, 'sequence': top['sequence'] if top else -1}, code)
                            e['cards'].append(c)
                            if c['instance_id'] is not None:
                                top.update(location=2, sequence=sum(x['controller'] == player and x['location'] == 2 for x in state['cards']))
                        annotate_cause(e, row['state'], {'controller': player, 'location': 2})
                        reason = e.get('observed_reason')
                        e['draw_kind'] = 'effect' if reason is not None and reason & 0x40 else 'rule' if reason is not None and reason & 0x400 else 'unknown'
                        if player == 0 and not turn_started and e['draw_kind'] == 'rule' and report['initial_hand'] is None:
                            report['initial_hand'] = deepcopy(e['cards']); report['initial_hand_ref'] = e['id']
                    elif msg in (60, 62, 64, 54):
                        e['cards'] = [ref(location(b, 4), u32(b))]
                        annotate_cause(e, row['state'])
                        if msg != 54: annotate_summon(e, row['state'])
                        if msg != 54: summoning.setdefault(msg + 1, []).extend(e['cards'])
                    elif msg in (61, 63, 65):
                        e['cards'] = summoning.pop(msg, []); e['result'] = '引擎确认召唤成功'
                        annotate_summon(e, row['state'])
                        annotate_cause(e, row['state'])
                    elif msg == 53:
                        e['cards'] = [ref(location(b, 4), u32(b))]; e['position_from'], e['position_to'] = b[7:9]
                    elif msg == 70:
                        n = b[15]
                        e.update(cards=[ref(location(b, 4), u32(b))], chain=n,
                                 triggering_controller=b[8],
                                 triggering_location=b[9], triggering_sequence=b[10],
                                 effect={'description_id': u32(b, 11), 'semantic_result': '未知'})
                        for native_chain in row['state'].get('chains', []):
                            if native_chain.get('link') == n:
                                e['engine_effect'] = native_chain.get('effect')
                                break
                        chains[n] = {'activation_ref': e['id'], 'cards': e['cards'], 'negated': False, 'disabled': False}
                        building_links[n] = e
                    elif msg in (71, 72, 73, 75, 76):
                        n = b[0]; ch = chains.get(n, {})
                        e.update(chain=n, activation_ref=ch.get('activation_ref'), cards=ch.get('cards', []))
                        for native_chain in row['state'].get('chains', []):
                            if native_chain.get('link') == n:
                                e['engine_effect'] = native_chain.get('effect')
                                break
                        if msg in (75, 76): e['resolution_source_ref'] = resolution_source
                        if msg == 75: ch['negated'] = True
                        if msg == 76: ch['disabled'] = True
                        if msg in (71, 75, 76): building_links.pop(n, None)
                        if msg == 72:
                            building_links.clear()
                            resolution_source = ch.get('activation_ref')
                        if msg == 73:
                            e['result'] = '发动已无效' if ch.get('negated') else '效果已无效' if ch.get('disabled') else '处理完成；实际结果请核对后续事件与场面'
                            resolution_source = None
                    elif msg == 74:
                        chains.clear(); building_links.clear()
                        resolution_source = None
                    elif msg == 83:
                        e['targets'] = [ref(location(b, 1 + i * 4)) for i in range(b[0])]
                        e['cards'] = e['targets']
                    elif msg in (91, 92, 94, 100):
                        e.update(player=b[0], amount=u32(b, 1))
                        if msg == 100:
                            e['cost'] = {'lp': e['amount']}
                            # PAY_LPCOST has no card reference. In the pinned core, a link's
                            # cost executes between CHAINING and CHAINED. Require one open
                            # window, the matching payer and a corroborating native effect.
                            if len(building_links) == 1:
                                activation = next(iter(building_links.values()))
                                native = activation.get('engine_effect') or {}
                                candidates = [c for c in row['state'].get('chains', []) if c.get('link') == activation['chain']]
                                if len(candidates) == 1 and activation.get('triggering_controller') == e['player']:
                                    source = candidates[0].get('effect') or {}
                                    key = 'effect_handle' if native.get('effect_handle') and source.get('effect_handle') else 'effect_id'
                                    if native.get(key) is not None and native.get(key) == source.get(key) and native.get('handler_instance') is not None and native.get('handler_instance') == source.get('handler_instance'):
                                        e.update(cause=deepcopy(source), cost_activation_ref=activation['id'], cost_source='chain_construction_window_and_snapshot')
                    elif msg in (15, 20):
                        e['choices'] = [ref(location(b, 9 + i * 8), u32(b, 5 + i * 8)) for i in range(b[4])]
                    elif msg in (25, 30, 42):
                        e['player'] = b[0]
                        e['cards'] = [ref(dict(zip(('controller','location','sequence'), b[6+i*7:9+i*7])), u32(b, 2+i*7)) for i in range(b[1])]
                    elif msg == 31:
                        e['cards'] = [ref(dict(zip(('controller','location','sequence'), b[7+i*7:10+i*7])), u32(b, 3+i*7)) for i in range(b[2])]
                    elif msg == 12:
                        e.update(cards=[ref(location(b, 5), u32(b, 1))], effect={'description_id': u32(b, 9)})
                    elif msg in (40, 41):
                        e['value'] = int.from_bytes(b, 'little')
                        building_links.clear()
                        if msg == 40: turn_started = True
                    elif msg in (32, 33, 35, 36, 37, 39, 55):
                        # These break simple event-to-location correspondence; wait for the authoritative batch snapshot.
                        for c in state['cards']: c['sequence'] = -1
                state = deepcopy(row['state'])
            except (ValueError, IndexError) as exc:
                report['warnings'].append(f"原始记录 {row['seq']}：{exc}")
                state = deepcopy(row['state'])
                resolution_source = None
        if 'state' in row:
            report['final_state'], report['final_state_ref'] = deepcopy(row['state']), row['seq']
    stats = Counter(e['message'] for e in report['events'])
    report['raw_statistics'] = {
        '通常召唤成功': stats[61], '特殊召唤成功事件': stats[63], '效果发动': stats[70],
        '连锁结算完成': stats[73], '发动或效果无效': stats[75] + stats[76], '区域移动': stats[50],
        '抽卡数量': sum(len(e['cards']) for e in report['events'] if e['message'] == 90 and e.get('actor') == 'self'),
        '玩家响应': stats['玩家选择'], '占位方自动跳过': stats['占位方自动跳过'],
    }
    report['actions'] = project_actions(report)
    report['statistics'] = {
        '通常召唤成功': stats[61], '特殊召唤成功事件': stats[63], '效果发动': stats[70],
        '效果抽卡': sum(len(e['cards']) for e in report['events'] if e['message'] == 90 and e.get('actor') == 'self' and e.get('draw_kind') == 'effect'),
        '发动或效果无效': stats[75] + stats[76], '展开步骤': len(report['actions']),
    }
    report['statistics_note'] = '抽卡统计仅包含引擎标记的效果抽卡，排除起手和规则抽卡；特殊召唤按成功事件计数。'
    report['report_version'] = REPORT_VERSION
    report['duration_ms'] = max(0, (report.get('ended_ms') or (rows[-1]['time_ms'] if rows else meta['started_ms'])) - meta['started_ms'])
    report['record_count'] = source_count
    report['active_record_count'] = len(rows)
    report['review'] = make_review(report, rows)
    return report
