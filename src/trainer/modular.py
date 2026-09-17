"""Versioned source library, disposable-core route search and built-in AI driver."""
from collections import Counter, deque
from copy import deepcopy
import json
import threading
import time
import uuid

from modular_decisions import (bind, digest, evaluation, integer, model, next_prompt,
                               public_state, forecast_state, resource_rank, semantic_response, terminal_key, response_bindings,
                               bind_variants, semantic_equal, snapshot_matches, canonical_state, script_binding_conflict)
from report import read_journal
from timeline import route_rows
from card_semantics import effect_clause, zone_name
from module_graph import decision_boundaries, decision_id
from module_conditions import branch_condition, condition_matches, facts_from_report, advance_facts
from plan_endboard import attach_terminal_marks, marked_terminal, marked_evaluation, satisfied_marked_terminal
from planning_cache import PlanningCache


PREFERENCES = ('shortest', 'largest', 'balanced', 'safest')
LIMITS = {'seconds': 32, 'nodes': 320, 'depth': 48, 'candidates': 24}
EXTRACTOR_VERSION = 12


class RouteFrontier:
    """Give each recorded continuation a turn before exploring mixed paths."""
    def __init__(self):
        self.guided, self.mixed = deque(), deque()

    def __bool__(self):
        return bool(self.guided or self.mixed)

    def append(self, item):
        (self.guided if item[-1] else self.mixed).append(item)

    def appendleft(self, item):
        # Finishing (or failing) one source must not let its mixed descendants
        # spend the whole budget before the other selected sources are tried.
        if item[-1]: self.guided.append(item)
        else: self.mixed.appendleft(item)

    def popleft(self):
        return (self.guided if self.guided else self.mixed).popleft()


def empty_response_edge(prompt, guide, raw):
    """An extra empty response window is an engine acknowledgement, not a move."""
    choices = prompt.get('choices', [])
    if prompt.get('message') != 16 or len(choices) != 1 or choices[0]['semantic']['kind'] != 'pass':
        return None
    response = choices[0]['response']
    return {**guide[0], 'id': digest(['engine_empty_response', guide[0]['id'], raw]),
            'decision': semantic_response(prompt, response), 'delta': [], 'automatic': True,
            'terminal': False, 'if_condition': None, '_keep_guide': True,
            'source': {**guide[0]['source'], 'automatic_window': True}}


def route_signature(candidate, precise):
    def normalized(value):
        if isinstance(value, dict):
            return {k: normalized(v) for k, v in value.items() if precise or k != 'sequence'}
        if isinstance(value, list): return [normalized(v) for v in value]
        return value
    decisions = []
    for step in candidate['steps']:
        if step.get('automatic'): continue
        decision = step.get('bound_decision') or step['decision']
        if not precise and all(s.get('kind') == 'place' for s in decision.get('selection', [])): continue
        decisions.append(normalized(decision))
    return digest([decisions, candidate.get('observation_required'), candidate['conditional']])


def guide_block_reason(edge, current, catalog):
    if current.get('_unknown_draws'): return '仍有随机结果未确认，暂时无法核对来源所需区域'
    cards = current['state'].get('cards', [])
    required = Counter((s['card']['code'], s['card']['location']) for s in edge['decision'].get('selection', [])
                       if s.get('card', {}).get('code') and s['card'].get('controller') == 0)
    for (code, location), count in required.items():
        own = [c for c in cards if c.get('controller') == 0 and c.get('code') == code]
        available = sum(c.get('location') == location for c in own)
        if available < count:
            name = catalog.get(code, {}).get('name', str(code))
            elsewhere = '、'.join(dict.fromkeys(zone_name(c.get('location', 0)) for c in own if c.get('location') != location))
            return f'下一步需要「{name}」在{zone_name(location)} ×{count}，当前可用 {available}' + (f'；可见副本在{elsewhere}' if elsewhere else '')
    prompt = model(current['raw'], current['state'], current.get('effects')) if current.get('raw') else None
    if prompt and script_binding_conflict(edge['decision'], prompt):
        return '来源与当前规则脚本的效果标识不兼容，尚不能确认同一效果；请在当前版本重新记录此来源'
    return '当前窗口、效果次数或选择条件与来源不同，无法直接续接'


def message(code):
    return {'no_route':'当前来源集合没有找到可接续路线，可手动继续或增加来源',
            'incomplete':'条件信息不足，等待实际结果或补充来源',
            'limited':'搜索达到计算边界，可调整来源后重试',
            'search_limit':'搜索达到计算边界，当前对局和记录已保留',
            'stale_state':'局面已变化，将从当前实际状态重新规划',
            'stale_state_source_or_preference':'局面、来源或偏好已变化，旧结果已作废，请重新规划',
            'stale_lease':'来源、偏好或自动模式已变化，过期输入已撤销',
            'replay_mismatch':'当前引擎重放校验不一致，请保留对局并手动继续',
            'state_mismatch':'当前引擎状态无法可靠重放，请保留对局并手动继续',
            'illegal_response':'规则引擎拒绝了此选择，需从当前窗口重新规划',
            'ai_unavailable':'基础对手 AI 不支持当前必要选择，需手动处理',
            'script_error':'隔离校验发生脚本错误，候选未被执行',
            'prompt_changed':'选择窗口发生变化，旧输入已停止',
            'reported_card_unavailable':'填报的卡牌或份数不在该步骤的剩余牌组中，请核对实际结果；原路线已保留',
            'unknown_opponent_choice':'后续依赖未确认的对手选择，需等待实际事件'}.get(code,code)


def inventory(state):
    return Counter((c.get('code'), c.get('location')) for c in state.get('cards', [])
                   if c.get('controller') == 0 and c.get('location') != 1)


def observed_delta(before, after):
    return [[code, zone, count] for (code, zone), count in (inventory(after)-inventory(before)).items() if zone != 2]


def boundary_distance(source, current):
    """Search ordering only. Legality never follows from snapshot similarity."""
    def resources(state):
        return Counter((c.get('code'), c.get('location'), c.get('sequence') if c.get('location') in (4, 8) else None)
                       for c in state.get('cards', []) if c.get('controller') == 0 and c.get('location') not in (1, 2))
    a, b = resources(source), resources(current)
    return sum((a-b).values())+sum((b-a).values())+sum(source.get(k) != current.get(k) for k in ('phase','turn_player','chain_depth'))


def satisfies_delta(edge, before, after):
    delta = inventory(after)-inventory(before)
    return all(delta[(code, zone)] >= count for code, zone, count in edge['delta'])


def board_pattern(rows,precise=True):
    return [tuple(row if precise else [row[0],row[1],row[3]]) for row in rows]


def healthy_board(state,precise=True):
    return Counter(board_pattern(terminal_key({'cards':[c for c in state.get('cards',[]) if not c.get('disabled')]}),precise))


def terminal_satisfied(before, expected, actual, precise=True):
    hand=lambda s:sum(c.get('controller')==0 and c.get('location')==2 for c in s.get('cards', []))
    healthy=not (healthy_board(expected,precise)-healthy_board(actual,precise))
    return (Counter(board_pattern(terminal_key(actual),precise))==Counter(board_pattern(terminal_key(expected),precise)) and healthy
            and satisfies_delta({'delta':observed_delta(before,expected)},before,actual)
            and hand(actual)>=hand(expected) and actual.get('lp',[0,0])[0]>=expected.get('lp',[0,0])[0]
            and actual.get('lp',[0,0])[1]<=expected.get('lp',[0,0])[1])


def original_goal_met(ctx,state):
    goal=ctx.get('original_goal')
    if goal is None:return None
    if ctx.get('original_goal_kind')=='board':
        reference=ctx.get('original_terminal')
        precise=ctx.get('precise',False)
        return Counter(board_pattern(terminal_key(state),precise))==Counter(board_pattern(goal,precise)) and (not reference or terminal_satisfied(reference,reference,state,precise))
    actual=Counter(c.get('code') for c in state.get('cards', []) if c.get('controller')==0 and c.get('location') in (4,8))
    return not (Counter(goal)-actual)


def hand_count(state):
    return sum(c.get('controller')==0 and c.get('location')==2 for c in state.get('cards', []))


def meaningful(edge):
    return not edge.get('automatic') and any(c.get('kind') not in ('pass','no') for c in edge['decision'].get('selection',[]))


def terminal_matches(edge, state, steps, history, precise=True):
    required=Counter(board_pattern(edge['terminal_board'],precise))
    if required-Counter(board_pattern(terminal_key(state),precise)):return False
    if healthy_board(edge.get('terminal_state',{}),precise)-healthy_board(state,precise):return False
    if any(inventory(state)[(code,zone)]<count for code,zone,count in edge.get('terminal_resources',[])):return False
    allocated=set()
    for pattern,count in sorted(edge.get('terminal_materials',[]),key=lambda row:-row[1]):
        carriers=[c for c in state['cards'] if c.get('controller')==0 and c.get('instance_id') not in allocated and
                  board_pattern([[c.get('code'),c.get('location'),c.get('sequence'),c.get('position')]],precise)==board_pattern([pattern],precise)]
        carrier=next((c for c in carriers if sum(m.get('location')==128 and m.get('overlay_target')==c.get('instance_id') for m in state['cards'])>=count),None)
        if not carrier:return False
        allocated.add(carrier['instance_id'])
    origin=next((step for step in steps if step.get('source',{}).get('route')==edge.get('source',{}).get('route')),None)
    if origin:
        requirement=next((p for p in edge.get('terminal_profiles',[]) if p['position']==origin.get('source',{}).get('position')),None)
        if requirement:
            before=origin['before']
            if hand_count(state)<hand_count(before)+requirement['hand_delta']:return False
            # Recorded damage/healing is part of a terminal's outcome. This also
            # prevents a generic chain-pass from silently skipping a burn effect.
            for player,change in enumerate(requirement['lp_delta']):
                actual=state.get('lp',[0,0])[player]-before.get('lp',[0,0])[player]
                if (change<0 and player==1 and actual>change) or (change>0 and player==0 and actual<change):return False
    anchor=edge.get('terminal_anchor')
    if not anchor:return False
    for actual in [*steps,*history]:
        if not semantic_equal(actual.get('decision'),anchor['decision'],precise):continue
        before=actual['before']
        if (satisfies_delta({'delta':anchor['delta']},before,state)
                and (anchor['hand_delta']<=0 or hand_count(state)-hand_count(before)>=anchor['hand_delta'])
                and (anchor['lp_delta']<=0 or state.get('lp',[0])[0]-before.get('lp',[0])[0]>=anchor['lp_delta'])):return True
    return False


def terminal_profiles(edges):
    for final in edges:
        if not final.get('terminal'):continue
        end=final['terminal_state']
        final['terminal_profiles']=[{'position':edge['position'], 'hand_delta':hand_count(end)-hand_count(edge['before']),
            'lp_delta':[end.get('lp',[0,0])[p]-edge['before'].get('lp',[0,0])[p] for p in (0,1)]}
            for edge in edges if edge['position']<=final['position']]


class ModularLibrary:
    def __init__(self, store, read, write):
        self.store, self.read, self.write = store, read, write
        self.root = store.root / 'modular'
        self.entries = {}
        self.version = ''
        self.lock = threading.RLock()
        self.stamps = {}

    def capture(self, report, session_id=None):
        """Freeze evidence while available; legacy sources remain untouched."""
        if report.get('modular_source', {}).get('schema') == 1:
            source=self.upgrade(deepcopy(report['modular_source']))
            marked=report.get('annotations',{}).get('final_marks',{})
            for edge in source['edges']:
                if not edge.get('terminal'):continue
                required=Counter((c['code'],c['location']) for c in edge['terminal_state']['cards'] if c.get('controller')==0 and c['location'] in (16,32) and marked.get(str(c.get('instance_id')),{}).get('marked'))
                edge['terminal_resources']=[[code,zone,count] for (code,zone),count in required.items()]
            return attach_terminal_marks(source, report)
        sid = session_id or report.get('id')
        try:
            folder = self.store.session_path(sid)
            rows, issues = read_journal(folder / 'native.jsonl', sid)
            if issues: raise ValueError('原始决策记录不完整')
            rows = route_rows(rows)[0]
            boundaries = decision_boundaries(rows, folder)
            snapshots, edges, unknown = [], [], []
            for i, entry in enumerate(boundaries):
                node = entry['node']; raw = node.get('raw')
                snapshot = {'id': decision_id(node), 'position': i, 'seq': node['seq'],
                            'state': public_state(node['state']), 'raw': raw if node.get('player') == 0 else None,
                            'effects': node.get('effects', {}) if node.get('player') == 0 else {},
                            'player': node.get('player'), 'status': 'recorded'}
                snapshots.append(snapshot)
                if node.get('player') != 0 or not entry['responses']: continue
                response = entry['responses'][0]
                if len(entry['responses']) != 1:
                    unknown.append({'position': i, 'reason': '同一边界有重试输入，不能当成已确认连接'}); continue
                if i+1 >= len(boundaries):
                    unknown.append({'position': i, 'reason': '缺少决策后的确认边界'}); continue
                following = boundaries[i+1]['node']
                try:
                    prompt = model(raw, node['state'], node.get('effects'))
                    semantic = semantic_response(prompt, response['raw'])
                    if prompt.get('unsupported'): raise ValueError('此窗口需要补充决策解码')
                    if not node.get('effects') and any(c.get('effect') for c in prompt['choices']):
                        raise ValueError('旧记录缺少准确效果标识，请在新版引擎重录此来源')
                    if any(choice.get('effect') and choice['effect'].get('operation_line') is None for choice in semantic.get('selection', [])):
                        raise ValueError('记录未能唯一定位具体效果，需要补充引擎效果依据')
                    if any(e and (e.get('labels') is None or e.get('property_flags') is None) for e in [semantic.get('context'),*(c.get('effect') for c in semantic.get('selection', []))]):
                        raise ValueError('旧记录缺少效果分支标签，请在新版引擎重录此来源')
                    edges.append({'from': snapshot['id'], 'to': decision_id(following), 'position': i,
                                  'decision': semantic, 'response': response['raw'],
                                  'bindings': response_bindings(prompt, response['raw']),
                                  'before': snapshot['state'], 'after': public_state(following['state']),
                                  'delta': observed_delta(node['state'], following['state']),
                                  'automatic': prompt['message'] == 16 and len(prompt['choices']) == 1 and prompt['choices'][0]['semantic']['kind'] == 'pass',
                                  'terminal': False, 'status': 'recorded'})
                except (ValueError, IndexError, KeyError, TypeError, StopIteration) as error:
                    unknown.append({'position': i, 'reason': str(error)})
            # A successful route ends at a recorded, settled player decision.
            if edges and boundaries:
                last = boundaries[-1]['node']
                if last.get('player') == 0 and last.get('prompt') in (10, 11) and not last['state'].get('chain_depth') and not any(u.get('position',0)>edges[-1]['position'] for u in unknown):
                    # Opponent empty-pass checkpoints between the last own decision
                    # and settled boundary are allowed, never replayed as own actions.
                    final_edge = edges[-1]
                    final_edge['terminal'] = True
                    final_edge['terminal_board'] = terminal_key(last['state'])
                    final_edge['terminal_state'] = public_state(last['state'])
                    anchor=next((edge for edge in reversed(edges) if meaningful(edge)),None)
                    if anchor:
                        final_edge['terminal_anchor']={'decision':anchor['decision'],'delta':observed_delta(anchor['before'],last['state']),
                            'hand_delta':hand_count(last['state'])-hand_count(anchor['before']),
                            'lp_delta':last['state']['lp'][0]-anchor['before']['lp'][0]}
                    # Incidental graveyard cards (especially random mills) are
                    # not unconditional goal requirements. Keep explicitly
                    # marked resources; the active anchor proves its own result.
                    marked=report.get('annotations',{}).get('final_marks',{})
                    required=Counter((c['code'],c['location']) for c in last['state']['cards'] if c.get('controller')==0 and c['location'] in (16,32) and marked.get(str(c.get('instance_id')),{}).get('marked'))
                    final_edge['terminal_resources']=[[code,zone,count] for (code,zone),count in required.items()]
                    final_edge['terminal_materials']=[]
                    for carrier in last['state']['cards']:
                        if carrier.get('controller')!=0 or carrier.get('location')!=4:continue
                        count=sum(c.get('location')==128 and c.get('overlay_target')==carrier.get('instance_id') for c in last['state']['cards'])
                        if count:final_edge['terminal_materials'].append(([carrier['code'],4,carrier['sequence'],carrier['position']],count))
            terminal_profiles(edges)
            return attach_terminal_marks({'schema': 1, 'extractor_version': EXTRACTOR_VERSION, 'snapshots': snapshots, 'edges': edges, 'unknown': unknown,
                    'engine': report.get('engine_sha256'), 'scripts': report.get('scripts_sha256'),
                    'status': 'recorded' if edges else 'incomplete'}, report)
        except (ValueError, OSError, TypeError) as error:
            return {'schema': 1, 'snapshots': [], 'edges': [], 'unknown': [{'reason': str(error)}], 'status': 'incomplete'}

    def upgrade(self,source):
        """Rebuild derived conditions from frozen evidence, preserving old files."""
        if source.get('extractor_version')==EXTRACTOR_VERSION:return source
        nodes={n['id']:n for n in source.get('snapshots',[])}
        valid=[]
        for edge in source.get('edges',[]):
            try:
                node=nodes[edge['from']];p=model(node['raw'],node['state'],node.get('effects'))
                edge['decision']=semantic_response(p,edge['response'])
                if any(e and (e.get('labels') is None or e.get('property_flags') is None) for e in [edge['decision'].get('context'),*(c.get('effect') for c in edge['decision'].get('selection', []))]):
                    raise ValueError('旧记录缺少效果分支标签，请在新版引擎重录此来源')
                edge['bindings']=response_bindings(p,edge['response'])
                edge['automatic']=p['message']==16 and len(p['choices'])==1 and p['choices'][0]['semantic']['kind']=='pass'
                valid.append(edge)
            except (ValueError,TypeError,KeyError,IndexError,StopIteration) as error:
                source.setdefault('unknown',[]).append({'position':edge.get('position',0),'reason':str(error)})
        source['edges']=valid
        for edge in valid:
            if not edge.get('terminal'):continue
            end=edge.get('terminal_state')
            anchor=next((e for e in reversed(valid) if meaningful(e) and e['position']<=edge['position']),None)
            if not end or not anchor or any(u.get('position',0)>edge['position'] for u in source.get('unknown',[])):
                edge['terminal']=False;continue
            edge['terminal_anchor']={'decision':anchor['decision'],'delta':observed_delta(anchor['before'],end),
                                    'hand_delta':hand_count(end)-hand_count(anchor['before']),
                                    'lp_delta':end['lp'][0]-anchor['before']['lp'][0]}
            # Old inferred grave counts are not explicit user goal marks.
            edge['terminal_resources']=[]
            edge['terminal_materials']=[]
            for c in end['cards']:
                if c.get('controller')!=0 or c.get('location')!=4:continue
                count=sum(m.get('location')==128 and m.get('overlay_target')==c.get('instance_id') for m in end['cards'])
                if count:edge['terminal_materials'].append(([c['code'],4,c['sequence'],c['position']],count))
        terminal_profiles(valid)
        source['extractor_version']=EXTRACTOR_VERSION
        source['status']='recorded' if valid else 'incomplete'
        return source

    def freeze(self, plan):
        plan['modular_source'] = self.capture(plan)
        for branch in plan.get('branches', []):
            if branch.get('report'):
                branch['report']['modular_source'] = self.capture(branch['report'], branch.get('session_id'))

    def sync(self):
        with self.store.lock, self.lock:
            fresh = {}
            for path in sorted(self.store.plans.glob('*.json')):
                try:
                    info = path.stat(); stamp = (info.st_mtime_ns, info.st_size, info.st_ino)
                    if self.stamps.get(path.stem) == stamp and path.stem in self.entries and self.entries[path.stem]['status'] != 'failed':
                        fresh[path.stem] = self.entries[path.stem]; continue
                    plan = self.read(path); version = digest([EXTRACTOR_VERSION,plan])
                    previous = self.entries.get(path.stem)
                    if previous and previous['version'] == version:
                        fresh[path.stem] = previous; continue
                    obj = self.root / 'versions' / path.stem / f'{version}.json'
                    if obj.exists(): entry = self.read(obj)
                    else:
                        routes = []
                        for route_id, name, report, sid in [(plan['id'], plan['name'], plan, plan['id']),
                                *((b['id'], b['name'], b['report'], b.get('session_id')) for b in plan.get('branches', []) if b.get('report') and b.get('valid', True))]:
                            evidence = self.capture(report, sid)
                            branch=next((b for b in plan.get('branches',[]) if b['id']==route_id),None)
                            if branch:
                                guard=branch_condition(plan,branch)
                                evidence['if_condition']=guard
                                boundary=(guard.get('event') or {}).get('seq',branch['source']['seq'])
                                snapshots={node['id']:node for node in evidence['snapshots']}
                                for edge in evidence['edges']:
                                    if snapshots[edge['from']]['seq']<=boundary:continue
                                    edge['if_condition']=deepcopy(guard)
                                if guard['status']!='verified':evidence['unknown'].append({'reason':'IF 条件尚无实际事件确认，请完成妥协场并核对打断结果'})
                            routes.append({'id': route_id, 'name': name, **evidence})
                        entry = {'id': path.stem, 'name': plan['name'], 'version': version,
                                 'revision': plan.get('edit_revision', 0), 'routes': routes,
                                 'opening_conditions': deepcopy(plan.get('expansion', {}).get('conditions')),
                                 'actual_opening': deepcopy(plan.get('expansion', {}).get('actual_opening')),
                                 'opening_note': '来源起手条件仅描述初始手牌；连接动作仍按具体卡牌和规则引擎验证，属性相同不代表路线可替换',
                                 'status': 'ready' if any(r['edges'] for r in routes) else 'incomplete'}
                        self.write(obj, entry)
                    fresh[path.stem] = entry
                    self.stamps[path.stem] = stamp
                except (ValueError, OSError, KeyError, TypeError) as error:
                    fresh[path.stem] = {'id': path.stem, 'name': path.stem, 'version': 'failed',
                                        'status': 'failed', 'error': str(error), 'routes': []}
            version = digest({key: value['version'] for key, value in fresh.items()})
            if version != self.version:
                changed = {sid for sid in self.entries.keys() | fresh.keys() if self.entries.get(sid, {}).get('version') != fresh.get(sid, {}).get('version')}
                self.store.modular.sources_changing(changed)
                self.write(self.root / 'index.json', {'schema': 1, 'version': version, 'entries': fresh})
                self.entries, self.version = fresh, version
            return self.summary()

    def summary(self):
        return {'schema': 1, 'version': self.version, 'sources': [{**{k: v for k, v in e.items() if k != 'routes'},
                'snapshots': sum(len(r['snapshots']) for r in e['routes']),
                'connections': sum(len(r['edges']) for r in e['routes']),
                'unknown': [u for r in e['routes'] for u in r['unknown']]} for e in self.entries.values()]}

    def edges(self, selected):
        result = []
        for sid in selected:
            entry = self.entries.get(sid, {})
            for route in entry.get('routes', []):
                for edge in route['edges']:
                    source = {'plan': sid, 'name': entry['name'], 'version': entry['version'], 'route': route['id'],
                              'route_name': route['name'], 'snapshot': edge['from'], 'position': edge['position']}
                    result.append({**edge, 'id': digest([source, edge['decision']]), 'source': source})
        return result


class Modular:
    def __init__(self, store, read, write, write_bytes):
        self.store, self.read, self.write, self.write_bytes = store, read, write, write_bytes
        self.library = ModularLibrary(store, read, write)
        self.lock = threading.RLock()
        self.bridge_lock = threading.Lock()
        self.sessions = {}
        self.worker = None
        self.search_lock = threading.RLock()
        self.planning_lock = threading.Lock()
        self.planning_cache = PlanningCache()
        from duel_precompute import Precompute
        self.precompute = Precompute(self)
        self.providers = {}
        self.consumers = {'duel', 'automatic-duel', 'expansion', 'modular'}
        self.register_provider('decks', '卡组编辑', self.deck_input_version)
        self.register_provider('expansions', '展开与分支记录', lambda: {
            'version': self.library.version, 'records': len(self.library.entries)})
        self.register_provider('cards', '卡库与规则资源', lambda: {
            'version': digest(self.store.catalog.sources), 'records': len(self.store.catalog.cards)})

    def register_provider(self, name, owner, reader):
        """Local integration point for future features; readers own their raw data.

        Registering a provider does not grant its data executable-route status.
        Decisions still need native evidence and the usual disposable-core checks.
        """
        if not name or name in self.providers or not callable(reader):raise ValueError('数据提供方注册无效')
        self.providers[name] = (owner, reader)

    def deck_input_version(self):
        versions={}
        for label,root in (('library',self.store.decks),('existing',self.store.runtime/'deck')):
            for path in sorted(root.rglob('*.ydk')):
                if not path.is_symlink():versions[label+'/'+path.relative_to(root).as_posix()]=digest(path.read_bytes().hex())
        return {'version':digest(versions),'records':len(versions)}

    def data(self):
        self.library.sync()
        return {'schema':1, 'providers':[{'id':name,'owner':owner,**reader()} for name,(owner,reader) in self.providers.items()],
                'consumers':sorted(self.consumers), 'library':self.library.summary(),
                'authority':'原始数据归各功能所有；模块化保存派生索引，当前局面由规则引擎确认'}

    def dispatch(self, request):
        consumer, intent = request.get('consumer'), request.get('intent')
        if consumer not in self.consumers:raise ValueError('调用方尚未接入模块化调度')
        handlers={'configure':self.configure,'search':lambda body:self.public_result(self.search(body['id'])),
                  'execute':self.execute,'auto':self.automatic,'status':lambda body:self.status(body['id'])}
        if intent=='data':result=self.data();versions=None
        elif intent in ('plan-prepare','plan-poll','plan-cancel') and consumer in ('duel','automatic-duel'):
            result = self.precompute.dispatch(intent, request)
            versions = result.get('inputs', {})
        elif intent in ('plan','plan-adopt','plan-confirm','plan-observe','plan-close') and consumer in ('duel','automatic-duel'):
            from duel_planner import dispatch
            with self.planning_lock:
                if intent == 'plan-adopt' and request.get('job'): self.precompute.validate_adoption(request)
                result=dispatch(self,intent,request)
            versions=result['inputs']
        elif intent=='match':
            from duel import match
            from card_semantics import display_effects
            result=match(self.store,request)
            result['matches']=[display_effects(plan) for plan in result['matches']]
            versions={'deck':request.get('revision'),'sources':digest([(p['id'],p.get('edit_revision',0)) for p in result['matches']]),
                      'validation':'saved_requirements_only'}
        else:
            if intent not in handlers:raise ValueError('模块化调度请求类型无效')
            sid=request.get('id');folder=self.store.session_path(sid)
            meta=self.read(folder/'session.json')
            # The deck used in this duel stays frozen even if its editor changes.
            versions={'session':sid,'deck':meta.get('deck_sha256'),'engine':meta.get('engine_sha256'),
                      'scripts':meta.get('scripts_sha256')}
            result=handlers[intent](request)
            if intent!='status':
                with self.lock:self.audit(self.context(sid),'dispatch',consumer=consumer,intent=intent)
        return {'schema':1,'request_id':uuid.uuid4().hex,'consumer':consumer,'intent':intent,
                'inputs':versions,'result':result}

    def context(self, sid):
        with self.lock:
            if sid not in self.sessions:
                path = self.store.session_path(sid) / 'modular.json'
                value = self.read(path) if path.exists() else {'schema': 1, 'id': sid, 'preference': 'shortest',
                    'preference_version': 0, 'selected': [], 'goal': [], 'original_goal': None, 'audit': [], 'completed': [], 'pending': None}
                value.update(auto=False, result=None, busy=False, followup=None, reason='手动模式')
                value.setdefault('source_epoch', 0)
                value.setdefault('precise', False)
                value.setdefault('original_goal_kind','board' if value.get('original_goal') and isinstance(value['original_goal'][0],list) else 'cards')
                self.sessions[sid] = value
            return self.sessions[sid]

    def save(self, ctx):
        value = {k: v for k, v in ctx.items() if k not in ('result', 'busy', 'followup', 'forecast_state', 'forecast_route', 'forecast_bank', 'forecast_progress', 'forecast_partial')}
        self.write(self.store.session_path(ctx['id']) / 'modular.json', value)

    def audit(self, ctx, kind, **values):
        ctx['audit'].append({'time_ms': time.time_ns()//1_000_000, 'kind': kind, **deepcopy(values)})
        self.save(ctx)

    def state(self, sid):
        path = self.store.session_path(sid) / 'modular-state.json'
        if not path.exists(): raise ValueError('等待新版引擎到达决策边界')
        for attempt in range(20):
            try:
                value = self.read(path); break
            except PermissionError:
                if attempt == 19: raise
                time.sleep(.01)
        if not self.store.alive(self.read(self.store.session_path(sid)/'session.json')): value['running'] = False
        else: value['running'] = True
        forecast = self.sessions.get(sid, {}).get('forecast_state')
        if forecast: value.update(deepcopy(forecast))
        return value

    def visible_state(self, state):
        value = {k:deepcopy(v) for k,v in state.items() if not k.startswith('_')}; value['state'] = public_state(value['state'])
        if state.get('_unknown_draws'):
            value['state'] = forecast_state(state['state'], state['_unknown_draws'])
            value.update(raw=None, effects={})
        if value.get('player') != 0: value.update(raw=None, effects={})
        return value

    def configure(self, body):
        sid = body['id']; ctx = self.context(sid)
        with self.store.lock, self.lock:
            preference = body.get('preference', ctx['preference'])
            precise=body.get('precise',ctx['precise'])
            if type(precise) is not bool:raise ValueError('精确匹配开关无效')
            if preference not in PREFERENCES: raise ValueError('路线偏好无效')
            selected = body.get('sources', ctx['selected'])
            self.library.sync()
            if not isinstance(selected, list) or any(s not in self.library.entries for s in selected): raise ValueError('来源方案已经变化，请刷新来源列表')
            goal = body.get('goal', ctx['goal'])
            if not isinstance(goal, list) or len(goal) > 30 or any(type(c) is not int or c not in self.store.catalog.cards for c in goal): raise ValueError('终场条件应是有效卡牌编号列表')
            self.cancel_lease(sid)
            ctx.update(preference=preference, precise=precise, selected=list(dict.fromkeys(selected)), goal=goal,
                       preference_version=ctx['preference_version']+1, result=None, followup=None)
            if ctx['original_goal'] is None and goal: ctx.update(original_goal=goal[:],original_goal_kind='cards')
            self.audit(ctx, 'preference_changed', preference=preference, precise=precise, goal=goal, sources=ctx['selected'])
        self.ensure_worker()
        return self.status(sid)

    def cancel_lease(self, sid):
        (self.store.session_path(sid)/'modular-lease.txt').unlink(missing_ok=True)

    def sources_changing(self, identifiers):
        # Store mutations call this before their atomic commit point. Actions
        # already consumed by the core settle normally; queued leases are revoked.
        with self.lock:
            for sid, ctx in list(self.sessions.items()):
                if not set(ctx['selected']).intersection(identifiers): continue
                self.cancel_lease(sid)
                ctx['result'] = None
                ctx['followup'] = None
                ctx['source_epoch'] = ctx.get('source_epoch', 0)+1
                self.planning_cache.discard(sid, 'search')
                ctx['reason'] = '来源方案正在更新，旧候选已失效，等待从实际局面重新规划'
                self.audit(ctx, 'sources_updating')

    def bridge(self, sid, state, path, scenario=0, command='probe', lease=None):
        with self.bridge_lock:
            token = lease or uuid.uuid4().hex
            folder = self.store.session_path(sid)
            full_path = state.get('_prefix', []) + path if command != 'answer' else path
            forecast = command != 'answer' and 'forecast_meta' in self.sessions.get(sid, {})
            cache_key = None
            if forecast:
                # Full replay identity retains ordering, duplicate cards, outcomes,
                # seed/session and resource versions. A confirmed prefix can reuse
                # the same probe; an actual correction gets a different identity.
                cache_key = digest([state['version'], scenario, full_path, state.get('_observations', []),
                                    self.sessions[sid]['forecast_meta']['inputs'].get('engine'),
                                    self.sessions[sid]['forecast_meta']['inputs'].get('scripts')])
                actual = self.state(sid)
                if actual['version'] != state['version'] or not actual['running'] or actual['answered']:
                    raise ValueError('stale_state')
                cached = self.planning_cache.get('probe', sid, cache_key)
                if cached is not None: return cached
            text = f"{'forecast' if forecast else command} {state['version']} {token} {scenario} {len(full_path)}\n" + '\n'.join(full_path) + '\n'
            if forecast:
                observations = state.get('_observations', [])
                text += str(len(observations)) + '\n'
                for observation in observations:
                    text += ' '.join(map(str, [observation['index'], observation['kind'], len(observation['codes']), *observation['codes']])) + '\n'
            self.write_bytes(folder/'modular.request', text.encode('ascii'))
            deadline = time.monotonic()+7
            while time.monotonic() < deadline:
                result_path = folder/'modular-result.json'
                if result_path.exists():
                    try: value = self.read(result_path)
                    except PermissionError:
                        time.sleep(.012); continue
                    if value.get('token') == token:
                        if value['status'] == 'error': raise ValueError(value['error'])
                        if command == 'answer': return value
                        raw, uncertain = next_prompt(value['batches']) if full_path else (state['raw'], False)
                        value.update(raw=raw, uncertain=uncertain or bool(value.get('private_cards')), player=(bytes.fromhex(raw)[2] if bytes.fromhex(raw)[0] == 23 else bytes.fromhex(raw)[1]) if raw else None)
                        if cache_key is not None: self.planning_cache.put('probe', sid, cache_key, value)
                        return value
                # An accepted answer can publish its successor between the result
                # read and this check. Its acknowledgement still belongs to this
                # token; a newer prompt is not a failure of the committed answer.
                if command != 'answer' and self.state(sid)['version'] != state['version']: raise ValueError('stale_state')
                time.sleep(.012)
            raise ValueError('search_limit')

    def token(self, state, ctx):
        sources = digest({sid: self.library.entries.get(sid, {}).get('version') for sid in ctx['selected']})
        return [state['version'], state['revision'], sources, ctx['preference_version']]

    def valid_token(self, sid, expected):
        if self.sessions.get(sid, {}).get('forecast_cancelled') or self.store.closing: return False
        self.library.sync()
        current = self.state(sid)
        actual = self.token(current, self.context(sid))
        valid = current['running'] and not current['answered'] and actual == expected
        if not valid and self.context(sid).get('forecast_meta'):
            self.audit(self.context(sid), 'search_invalidated', running=current['running'], answered=current['answered'],
                       state_changed=actual[:2] != expected[:2], sources_changed=actual[2] != expected[2],
                       preference_changed=actual[3] != expected[3])
        return valid

    def search(self, sid, *, refresh=False, **options):
        with self.search_lock:
            ctx = self.context(sid)
            if 'forecast_meta' not in ctx: return self._search(sid, **options)
            self.library.sync(); state = self.state(sid); expected = self.token(state, ctx)
            if not state['running'] or state['answered'] or state['player'] != 0:
                raise ValueError('引擎尚未开放我方决策')
            key = digest([state, expected[2], ctx['precise'], ctx['goal'], ctx.get('original_goal'), ctx['preference'],
                          ctx.get('forecast_steps'), options, EXTRACTOR_VERSION])
            started = time.monotonic(); before = self.planning_cache.stats.copy()
            if refresh: self.planning_cache.discard(sid, 'search')
            result = None if refresh else self.planning_cache.get('search', sid, key)
            if result is not None and not result.get('complete'): result = None
            hit = result is not None
            if hit:
                if not self.valid_token(sid, expected): raise ValueError('stale_state_source_or_preference')
                result.update(token=expected, preference=ctx['preference'])
                for candidate in result['candidates']:
                    candidate['token'] = expected
                    candidate['id'] = digest([expected, candidate['path'], candidate.get('terminal_goal_id', 'observation')])
                self.rank(result['candidates'], ctx['preference'])
            else:
                result = self._search(sid, **options)
                # A partial search is evidence of work left, never a reusable
                # final answer. Preference changes have their own search key.
                if result.get('complete'): self.planning_cache.put('search', sid, key, result)
            result['cache'] = {'result_hit': hit,
                'scope': 'completed_search' if hit else 'verified_probes',
                'probe_hits': self.planning_cache.stats['probe_hits'] - before['probe_hits'],
                'probe_misses': self.planning_cache.stats['probe_misses'] - before['probe_misses']}
            result['computed_seconds'] = result['seconds']
            result['seconds'] = round(time.monotonic() - started, 3)
            if not options.get('scenario'):
                ctx['result'] = result
                if hit: self.audit(ctx, 'planning_cache_hit', candidates=len(result['candidates']))
            return result

    def _search(self, sid, *, scenario=0, seed=None, limits=None, all_preferences=False):
        ctx = self.context(sid); self.library.sync(); state = self.state(sid)
        if not state['running'] or state['answered'] or state['player'] != 0: raise ValueError('引擎尚未开放我方决策')
        expected = self.token(state, ctx); preference = ctx['preference']; goal = ctx['goal'][:]
        actual_history=self.decision_history(sid) + ctx.get('forecast_steps', [])
        edges = self.library.edges(ctx['selected']); bounds = {**LIMITS, **(limits or {})}
        forecast = 'forecast_meta' in ctx
        marked_goals = [e for e in edges if e.get('terminal') and e.get('terminal_marks')] if forecast else []
        actual_facts=facts_from_report(self.store._report(sid)) if any(edge.get('if_condition') for edge in edges) else []
        state.setdefault('_if_memory', {'chains':{},'facts':actual_facts})
        longest = max((len(r['edges']) for source in ctx['selected'] for r in self.library.entries.get(source, {}).get('routes', [])), default=0)
        bounds['depth'] = min(128, max(bounds['depth'], longest+8))
        start = time.monotonic(); queue = RouteFrontier() if forecast else deque(); source_checks = {}
        by_route = {}
        root_prompt = model(state['raw'], state['state'], state.get('effects'))
        for edge in edges: by_route.setdefault((edge['source']['plan'], edge['source']['route']), []).append(edge)
        for route_key, route in by_route.items():
            eligible = [i for i,e in enumerate(route) if (not ctx['precise'] or snapshot_matches(e['before'],state['state'])) and bind_variants(e['decision'], root_prompt,precise=ctx['precise'],limit=1)]
            first = min(eligible, key=lambda i: (boundary_distance(route[i]['before'], state['state']), i)) if eligible else None
            source_checks[route_key] = {'source': deepcopy(route[0]['source']), 'status': 'queued' if first is not None else 'no_start',
                                        'checked': 0, 'total': len(route[first:]) if first is not None else 0}
            if first is not None: queue.append((seed or state, [], [], frozenset(), False, route[first:]))
        # Verify each applicable recorded continuation before spending the rest
        # of the budget on freely mixed paths. Starting hands are never equated.
        queue.append((seed or state, [], [], frozenset(), False, None))
        incomplete_sources = any(r['unknown'] for source in ctx['selected'] for r in self.library.entries.get(source, {}).get('routes', []))
        candidates = {} if forecast else []
        rejected, nodes, limited, unknown = Counter(), 0, False, bool(incomplete_sources)
        probe_start = self.planning_cache.stats['probe_misses'] if forecast else 0
        def budget_used():
            return self.planning_cache.stats['probe_misses'] - probe_start if forecast else nodes
        def remember(candidate):
            if not forecast:
                candidates.append(candidate); return
            signature = route_signature(candidate, ctx['precise'])
            previous = candidates.get(signature)
            matching = list((previous or {}).get('satisfied_goal_sources', []))
            source = candidate.get('terminal_source')
            if source and source not in matching: matching.append(deepcopy(source))
            if previous is None or (resource_rank(candidate['evaluation']), -candidate['remaining']) > (resource_rank(previous['evaluation']), -previous['remaining']):
                candidates[signature] = candidate
            candidates[signature]['satisfied_goal_sources'] = matching
        queued_paths = {()}
        # Keep different provenances when paths reach the same state: a source
        # prefix is a preference, never the only legal continuation.
        while queue:
            if forecast and scenario == 0 and nodes % 16 == 0:
                ctx['forecast_progress'] = {'nodes': nodes, 'seconds': round(time.monotonic()-start, 3),
                    'candidates': len(candidates), 'checked': sum(c['status'] not in ('queued', 'checking') for c in source_checks.values()),
                    'total': len(source_checks), 'phase': '共享路线搜索与规则校验'}
                ctx['forecast_partial'] = self.public_result({'candidates': list(candidates.values())[:4],
                    'complete': False, 'limited': True, 'status': 'searching', 'preference': preference,
                    'seconds': round(time.monotonic()-start, 3), 'coverage': {'total': len(source_checks),
                    'checked': ctx['forecast_progress']['checked'], 'routes': deepcopy(list(source_checks.values()))}})
            if budget_used() >= bounds['nodes'] or time.monotonic()-start >= bounds['seconds'] or (len(candidates) >= bounds['candidates']*(8 if forecast else 1) and (not forecast or not queue.guided)):
                limited = True; break
            current, path, steps, seen, uncertain, guide = queue.popleft()
            check = source_checks[(guide[0]['source']['plan'], guide[0]['source']['route'])] if guide else None
            if check: check['status'] = 'checking'
            if len(steps) >= bounds['depth']: limited = True; continue
            if not self.valid_token(sid, expected): raise ValueError('stale_state_source_or_preference')
            try: prompt = model(current['raw'], current['state'], current.get('effects'))
            except (ValueError, TypeError):
                if check: check.update(status='blocked', reason='当前决策窗口无法读取')
                unknown = True; continue
            if prompt.get('unsupported'):
                if check: check.update(status='blocked', reason='当前决策窗口尚不支持')
                unknown = True; continue
            applicable = {}
            for edge in guide[:1] if guide else edges:
                if ctx['precise'] and (current.get('_unknown_draws') or not snapshot_matches(edge['before'],current['state'])):
                    unknown |= bool(current.get('_unknown_draws'))
                    rejected['精确匹配：已记录局面或区域细节不同']+=1;continue
                if not condition_matches(edge.get('if_condition'),current.get('_if_memory',{}).get('facts',[]),current['state']):
                    rejected['IF 干扰条件尚未发生，或首次补点资源不足']+=1;continue
                for response in bind_variants(edge['decision'],prompt,current.get('_unknown_draws',[]),ctx['precise'],limit=1 if guide else 3):
                    if any((binding.get('card') or {}).get('instance_id') in current.get('_unknown_draws', []) for binding in response_bindings(prompt,response)):
                        unknown=True;rejected['后续需要尚未确定的随机结果身份']+=1;continue
                    applicable.setdefault(response, []).append(edge)
            if not applicable and guide and 'forecast_meta' in ctx:
                acknowledgement = empty_response_edge(prompt, guide, current['raw'])
                if acknowledgement:
                    applicable[prompt['choices'][0]['response']] = [acknowledgement]
            if not applicable:
                if check: check.update(status='blocked', reason=guide_block_reason(guide[0], current, self.store.catalog.cards))
                if guide and script_binding_conflict(guide[0]['decision'], prompt): unknown = True
                if guide: queue.append((current, path, steps, seen, uncertain, None))
                rejected['当前合法窗口没有来源动作；资源、区域、效果次数或时机不匹配'] += 1
                if not path:
                    for edge in edges:
                        if edge['decision']['message'] != prompt['message']: continue
                        for selected in edge['decision'].get('selection', []):
                            card = selected.get('card')
                            if not card: continue
                            if card.get('unknown'):
                                rejected['需要对手尚未公开的目标条件，当前不能确认']+=1;continue
                            actual = [c for c in current['state']['cards'] if c.get('code') == card['code'] and c.get('controller') == 0 and c.get('location') == card['location']]
                            name = self.store.catalog.cards.get(card['code'], {}).get('name', str(card['code']))
                            if not actual: rejected[f'{name}：所需区域 {card["location"]} 中没有可用副本'] += 1
                            elif card.get('sequence') is not None and not any(c.get('sequence') == card['sequence'] for c in actual): rejected[f'{name}：需要区域位置 {card["sequence"]}，当前实例位置不同'] += 1
                            elif selected.get('effect'): rejected[f'{name}：引擎未开放此具体效果（说明 {selected["effect"].get("description")}）；次数、代价或限制须满足当前窗口'] += 1
            for response, origins in applicable.items():
                if steps: origins.sort(key=lambda edge: (edge['source']['route'] != steps[-1]['source']['route'],
                    edge['source']['position'] <= steps[-1]['source']['position'], abs(edge['source']['position']-steps[-1]['source']['position']-1)))
                if budget_used() >= bounds['nodes'] or time.monotonic()-start >= bounds['seconds']: limited = True; break
                nodes += 1; extended = path+[current['raw']+':'+response]
                try:
                    following = self.bridge(sid, state, extended, scenario)
                    selected=next((b.get('effect') for b in response_bindings(prompt,response) if b.get('effect')),None)
                    if_memory=advance_facts(current.get('_if_memory'),current['state'],following['state'],following['batches'],selected)
                    random_result = following['uncertain']; private_cards=set(following.get('private_cards',[]))
                    hidden = bool(public_state(state['state'])['unknown'])
                    opponent_steps = 0
                    while following['player'] == 1 and not following['ended']:
                        if opponent_steps >= 20: raise ValueError('search_limit')
                        opponent_prompt = model(following['raw'], following['state'], following.get('effects'))
                        if hidden and scenario == 0:
                            # Evaluate the explicitly stated no-response condition;
                            # never let privately visible opponent cards choose it.
                            decline = next((c for c in opponent_prompt['choices'] if c['semantic']['kind'] in ('pass', 'no')), None)
                            if not decline: raise ValueError('unknown_opponent_choice')
                            extended.append(following['raw']+':'+decline['response'])
                        else: extended.append(following['raw']+':ai')
                        previous_state=following['state']
                        following = self.bridge(sid, state, extended, scenario); opponent_steps += 1
                        if_memory=advance_facts(if_memory,previous_state,following['state'],following['batches'])
                        random_result |= following['uncertain']
                        private_cards.update(following.get('private_cards',[]))
                    condition = uncertain or random_result or hidden
                    unknown |= random_result
                    if not following['raw']: continue
                    private_opponent={c.get('instance_id') for c in state['state']['cards'] if c.get('controller')==1 and
                        (c.get('location') in (1,2,64) or c.get('location') in (4,8,32) and c.get('position',0)&10)}
                    if any(c.get('instance_id') in private_opponent and c.get('controller')==1 and c.get('location') in (4,8,16,32) and c.get('position',0)&5 for c in following['state']['cards']):
                        unknown=True;rejected['后续依赖尚未公开的对手卡牌，等待实际事件确认']+=1;continue
                    previously_accessible={c.get('instance_id') for c in current['state']['cards'] if c.get('controller')==0 and c.get('location')!=1}
                    uncertain_cards=set(current.get('_unknown_draws', [])) | private_cards
                    if random_result:
                        uncertain_cards.update(c.get('instance_id') for c in following['state']['cards'] if c.get('controller')==0 and c.get('location')!=1 and c.get('instance_id') not in previously_accessible)
                    following['_unknown_draws']=list(uncertain_cards)
                    following['_if_memory']=if_memory
                    key = digest(canonical_state([following['state'], following['raw'], following.get('effects')]))
                    if key in seen: rejected['检测到重复状态，停止循环'] += 1; continue
                    for edge in origins:
                        if not satisfies_delta(edge, current['state'], following['state']):
                            rejected['实际结果与来源连接不同，保留真实结果重新衔接'] += 1
                        step = {'edge': edge['id'], 'source': edge['source'], 'decision': edge['decision'],
                                'bound_decision':semantic_response(prompt,response),
                                'before': forecast_state(current['state'],current.get('_unknown_draws', [])),
                                'sources': [origin['source'] for origin in origins],
                                'if_condition':edge.get('if_condition'),
                                'bindings': response_bindings(prompt, response), 'source_bindings': edge.get('bindings', []),
                                'response': response, 'state': forecast_state(following['state'],uncertain_cards), 'delta': edge['delta'],
                                'next_raw': following['raw'],
                                'path_end': len(extended), 'next_effects': following.get('effects', {}),
                                'if_memory': deepcopy(if_memory),
                                'automatic': edge.get('automatic', False)}
                        selected = next(iter(edge['decision'].get('selection', [])), {})
                        if selected.get('kind')=='special' and selected.get('card',{}).get('location')==8 and self.store.catalog.cards.get(selected['card'].get('code'),{}).get('type',0)&0x1000000:
                            step['operation_label']='灵摆召唤'
                        if selected.get('effect'):
                            step['effect_label'] = effect_clause({'cards': [selected.get('card', {})],
                                'engine_effect': selected['effect'], 'effect': {'description_id': selected['effect'].get('description')}},
                                {str(k): v for k, v in self.store.catalog.cards.items()})
                        route = steps+[step]
                        if check and not edge.get('_keep_guide'):
                            check['checked'] = check['total'] - len(guide) + 1
                            if len(guide) == 1: check['status'] = 'checked'
                        new_unknown = uncertain_cards - set(current.get('_unknown_draws', []))
                        if 'forecast_meta' in ctx and new_unknown:
                            if check: check['status'] = 'needs_observation'
                            terminal = forecast_state(following['state'], uncertain_cards)
                            slots = [c.get('location') for c in following['state']['cards'] if c.get('instance_id') in new_unknown]
                            pending_terminal = marked_terminal({}, terminal)
                            remember({'id': digest([expected, extended, 'observation']), 'steps': route,
                                'remaining': sum(not s['automatic'] for s in route), 'terminal': terminal,
                                **pending_terminal,
                                'evaluation': {**evaluation(terminal, self.store.catalog.cards), **marked_evaluation(pending_terminal)}, 'goal_met': False,
                                'conditional': True, 'validation': 'needs_observation', 'observation_required': slots,
                                'reason': '到达随机结果步骤，请填写实际抽牌或堆墓结果后继续计算',
                                'robustness': {'status': 'unassessed', 'scenarios': []}, 'path': extended, 'token': expected})
                            continue
                        terminals = []
                        visible_terminal = forecast_state(following['state'], uncertain_cards)
                        if bytes.fromhex(following['raw'])[0] in (10,11) and not following['state'].get('chain_depth'):
                            for goal_edge in marked_goals:
                                if not condition_matches(goal_edge.get('if_condition'), if_memory.get('facts', []), following['state']): continue
                                marked = satisfied_marked_terminal(goal_edge, visible_terminal, ctx['precise'])
                                if marked: terminals.append((goal_edge, marked))
                            if edge['terminal'] and (not forecast or not edge.get('terminal_marks')) and terminal_matches(edge,following['state'],route,actual_history,ctx['precise']):
                                terminals.append((edge, marked_terminal(edge, visible_terminal, ctx['precise'])))
                        reached_goals = set()
                        for goal_edge, marked in terminals:
                            if any(c.get('instance_id') in uncertain_cards and c.get('location') in (4,8) for c in following['state']['cards']):
                                unknown=True;continue
                            terminal = visible_terminal
                            ev = evaluation(terminal, self.store.catalog.cards)
                            if forecast: ev.update(marked_evaluation(marked))
                            actual = Counter(c.get('code') for c in terminal['cards'] if c.get('controller') == 0 and c.get('location') in (4, 8))
                            candidate = {'id': digest([expected, extended, goal_edge['id']]) if forecast else digest([expected, [s['edge'] for s in route]]), 'steps': route,
                                'terminal_goal_id': goal_edge['id'], 'terminal_source':goal_edge['source'], 'terminal_if':goal_edge.get('if_condition'),
                                'remaining': sum(not s['automatic'] for s in route), 'terminal': terminal, 'evaluation': ev, **marked,
                                'goal_met': not (Counter(goal)-actual), 'conditional': condition,
                                'validation': 'conditional' if condition else 'engine_verified',
                                'reason': '路径来自来源中的合法决策与空响应确认；引擎已到达标记终场目标，未标记中间牌不作为终场要求' if forecast else '每次选择均来自来源方案；隔离引擎已到达对应场上目标，手牌与可用权限按本局实际资源显示',
                                'robustness': {'status': 'unassessed', 'scenarios': []},
                                'path': extended, 'token': expected}
                            candidate['original_goal_met'] = original_goal_met(ctx,terminal)
                            remember(candidate)
                            if candidate['goal_met']: reached_goals.add(goal_edge['id'])
                        if marked_goals and all(g['id'] in reached_goals for g in marked_goals):
                            # No extra play can improve a marked goal already
                            # satisfied here. Explore earlier alternatives next.
                            if check: check['status'] = 'goal_reached'
                            continue
                        remaining_guide = (guide if edge.get('_keep_guide') else guide[1:]) if guide else None
                        queue_key = (tuple(extended), remaining_guide[0]['id'] if remaining_guide else None)
                        if queue_key not in queued_paths:
                            queued_paths.add(queue_key)
                            continuation = (following, extended, route, seen|{key}, condition, remaining_guide or None)
                            if remaining_guide or steps and edge['source']['route'] == steps[-1]['source']['route'] and edge['source']['position'] > steps[-1]['source']['position']:
                                queue.appendleft(continuation)
                            else: queue.append(continuation)
                except ValueError as error:
                    if check: check.update(status='blocked', reason=message(str(error)))
                    if 'stale' in str(error): raise
                    if 'limit' in str(error): limited = True
                    elif 'unknown' in str(error) or str(error) in ('ai_unavailable', 'script_error', 'prompt_changed'): unknown = True
                    else: rejected[str(error)] += 1
        candidates = list(candidates.values()) if forecast else list({c['id']: c for c in candidates}.values())
        verified_nodes = budget_used()
        if scenario == 0 and candidates and state['state'].get('turn_player') == 0:
            # One named, repeatable interference model; no claims beyond its scope.
            if forecast: ctx['forecast_progress'] = {'nodes': nodes, 'candidates': len(candidates), 'phase': '四种偏好评价与限定干扰校验'}
            stress = self.search(sid, scenario=1, all_preferences=all_preferences, limits={**bounds, 'seconds': min(4, bounds['seconds']), 'nodes': min(80, bounds['nodes'])})
            for candidate in candidates:
                key = candidate['steps'][0]['decision']
                alternatives = [c for c in stress['candidates'] if c['steps'][0]['decision'] == key]
                declared_goal = next((g for g in marked_goals if g['id'] == candidate.get('terminal_goal_id')), None)
                retained = any(satisfied_marked_terminal(declared_goal, c['terminal'], ctx['precise']) for c in alternatives) if declared_goal else any(terminal_key(c['terminal']) == terminal_key(candidate['terminal']) and resource_rank(c['evaluation']) >= resource_rank(candidate['evaluation']) for c in alternatives)
                candidate['robustness'] = {'status': 'evaluated' if alternatives or not stress['limited'] else 'limited',
                    'scenarios': [{'name': '假设对手手牌只有一张灰流丽，沿用内置基础 AI 响应',
                                   'continued': bool(alternatives), 'limited': stress['limited'],
                                   'original_terminal_retained': retained,
                                   'terminal': alternatives[0]['terminal'] if alternatives else None,
                                   'basis': '隔离引擎真实处理与来源后续重组；未评估其他手坑、盖卡和多次干扰'}]}
            evaluated = {}
            evaluation_deadline = time.monotonic()+4
            for candidate in candidates:
                signature = digest(candidate['terminal'])
                if signature not in evaluated:
                    evaluated[signature] = {'confirmed_response': 0, 'interruptions': None,
                        'response_evaluation': '未评估未来对手回合；临时方案按来源标记比较终场'} if forecast else self.evaluate_terminal(sid, state, candidate) if time.monotonic() < evaluation_deadline else {
                        'confirmed_response': 0, 'interruptions': None, 'response_evaluation': '未评估：本次终场评价达到计算边界'}
                candidate['evaluation'].update(evaluated[signature])
        # Always keep attainable alternatives when the desired goal is unavailable.
        self.rank(candidates, preference)
        if forecast:
            positions = {key: [e['source']['position'] for e in route] for key, route in by_route.items()}
            for candidate in candidates:
                adaptations, previous = [], None
                for step in candidate['steps']:
                    source = step['source']
                    if source.get('automatic_window'): continue
                    position = source.get('position', 0)
                    route_key = (source.get('plan'), source.get('route'))
                    index = positions.get(route_key, []).index(position) if position in positions.get(route_key, []) else -1
                    if previous is None and index > 0:
                        adaptations.append(f"从当前局面接入「{source.get('route_name', source.get('name'))}」第 {position+1} 个决策点；此前步骤以本局已确认记录为准")
                    elif previous and (route_key != previous['_route_key'] or index != previous['_index']+1):
                        adaptations.append(f"由「{previous.get('route_name', previous.get('name'))}」第 {previous.get('position', 0)+1} 个决策，接续「{source.get('route_name', source.get('name'))}」第 {position+1} 个决策")
                    previous = {**source, '_route_key': route_key, '_index': index}
                candidate['adaptations'] = list(dict.fromkeys(adaptations))
        if forecast and not all_preferences: candidates = candidates[:bounds['candidates']]
        result = {'token': expected, 'candidates': candidates, 'preference': preference, 'precise':ctx['precise'],
                  'status': 'found' if candidates else 'limited' if limited else 'incomplete' if unknown or any(e['status'] != 'ready' for e in self.library.entries.values() if e['id'] in ctx['selected']) else 'no_route',
                  'limited': limited, 'nodes': nodes, 'new_verifications': verified_nodes,
                  'seconds': round(time.monotonic()-start, 3), 'limits': bounds,
                  'complete': not limited and not unknown and (scenario != 0 or preference != 'safest' or all(c['robustness']['status'] == 'evaluated' for c in candidates)),
                  'coverage': {'total': len(source_checks),
                               'checked': sum(c['status'] not in ('queued', 'checking') for c in source_checks.values()),
                               'routes': list(source_checks.values())},
                  'evaluation_limits': {'interference_seconds': 4, 'terminal_seconds': 4, 'terminal_probe_seconds': 2.5},
                  'rejected': dict(rejected), 'start': self.visible_state(state), 'goal': goal,
                  'notice': '范围仅限所选来源与搜索预算，不代表规则上无解；未知对手信息、随机结果和未评估阻抗不会标成确定成功'}
        if scenario == 0:
            with self.store.lock, self.lock:
                if not self.valid_token(sid, expected): raise ValueError('stale_state_source_or_preference')
                ctx['result'] = result
                ctx['last_planned'] = expected
                if not ctx['auto']: ctx['reason'] = '已从当前实际局面重新规划'
                self.audit(ctx, 'replanned', token=expected, preference=preference, candidates=len(candidates), status=result['status'])
        return result

    def decision_history(self,sid):
        rows,_=read_journal(self.store.session_path(sid)/'native.jsonl',sid)
        rows=route_rows(rows)[0];result=[];node=None;response=None
        for row in rows:
            if row.get('kind')=='checkpoint':
                if node and response:
                    try:
                        prompt=model(node['raw'],node['state'],node.get('effects'))
                        result.append({'decision':semantic_response(prompt,response['raw']),'before':public_state(node['state']),
                                       'actor':response.get('actor'),'node':decision_id(node),'next_module':decision_id(row),
                                       'response_seq':response['seq'],'state':public_state(row['state']),
                                       'automatic':prompt['message']==16 and len(prompt['choices'])==1})
                    except (ValueError,KeyError,TypeError,IndexError,StopIteration):pass
                node=row if row.get('player')==0 else None;response=None
            elif row.get('kind')=='response' and node:response=row
        return result

    def evaluate_terminal(self, sid, state, candidate):
        """One actual next-turn response scenario, without inventing effect counts.

        This is evaluation evidence, not a source action or executable route.
        Even if several options exist, only a lower bound of one is reported;
        shared costs/once-per-turn permissions are never summed independently.
        """
        path = candidate['path'][:]
        started = time.monotonic()
        try:
            current = self.bridge(sid, state, path, 2)
            activated = False
            for _ in range(24):
                if time.monotonic()-started > 2.5: raise ValueError('evaluation_limit')
                prompt = model(current['raw'], current['state'], current.get('effects'))
                choices = prompt['choices']
                if prompt['player'] == 0 and activated and prompt['message'] in (12, 16):
                    known_instances={c.get('instance_id') for c in candidate['terminal']['cards'] if c.get('controller')==0 and not c.get('unknown')}
                    options = [c for c in choices if c['semantic']['kind'] in ('yes', 'activate') and (c.get('effect') or {}).get('category', 0) & 0x10004000 and (c.get('card') or {}).get('instance_id') in known_instances]
                    if options:
                        response = options[0]
                        pot_links={c['link'] for c in current['state'].get('chains',[]) if (c.get('effect') or {}).get('handler_code')==55144522}
                        path.append(current['raw']+':'+response['response'])
                        result = self.bridge(sid, state, path, 2)
                        from protocol import packets, u32
                        paid_lp=0
                        for _ in range(20):
                            events=[(msg,body) for batch in result['batches'] for _,msg,body in packets(bytes.fromhex(batch))]
                            paid_lp+=sum(u32(body,1) for msg,body in events if msg==100 and body[0]==0)
                            if any(msg in (75,76) and body[0] in pot_links for msg,body in events):
                                return {'confirmed_response': 1, 'interruptions': {'resolved_lower_bound': 1,
                                    'effect': response['effect'], 'card': response['card'],
                                    'lp_paid':paid_lp, 'evidence':[{'message':msg,'chain':body[0]} for msg,body in events if msg in (75,76) and body[0] in pot_links],
                                    'scope': '下个对手回合发动强欲之壶，响应和必要代价已由引擎处理，记录了对方该连锁被无效；仅计一次，不累加共享代价或次数'},
                                    'basis': '先比较本场景实际结算验证的干扰下界，再比较场上与手牌资源、场上怪兽、保留额外卡组和生命值；未评估项不加分'}
                            if any(msg==74 for msg,_ in events):return {'confirmed_response':0,'interruptions':{'resolved_lower_bound':0,'scope':'响应可发动，但本场景未确认对方效果被无效；其他响应与怪兽效果场景未评估'}}
                            if not result['raw'] or time.monotonic()-started>2.5:raise ValueError('evaluation_limit')
                            p=model(result['raw'],result['state'],result.get('effects'))
                            if p['player']==1:raw='ai'
                            elif p['mode']=='cards':
                                eligible=[c for c in p['choices'] if (c.get('card') or {}).get('instance_id') in known_instances]
                                if len(eligible)<p['minimum']:raise ValueError('evaluation_cost_unknown')
                                raw=bytes([p['minimum'],*(c['response'] for c in eligible[:p['minimum']])]).hex()
                            else:
                                choice=next((c for c in p['choices'] if c['semantic']['kind'] in ('pass','no')),None)
                                if not choice:raise ValueError('evaluation_requires_choice')
                                raw=choice['response']
                            path.append(result['raw']+':'+raw);result=self.bridge(sid,state,path,2)
                        raise ValueError('evaluation_limit')
                    return {'confirmed_response': 0, 'interruptions': {'lower_bound': 0, 'scope': '下个对手回合发动强欲之壶时未出现可发动响应；其他场景未评估'}}
                if prompt['player'] == 0:
                    choice = next((c for c in choices if c['semantic']['kind'] in ('end_turn', 'pass', 'no')), None)
                elif prompt['message'] == 11:
                    choice = next((c for c in choices if c['semantic']['kind'] == 'activate' and c['semantic'].get('card', {}).get('code') == 55144522), None)
                    if choice: activated = True
                elif prompt['mode'] == 'places': choice = choices[0] if choices else None
                else: choice = next((c for c in choices if c['semantic']['kind'] in ('pass', 'no')), None)
                if not choice: raise ValueError('evaluation_requires_choice')
                path.append(current['raw']+':'+choice['response']); current = self.bridge(sid, state, path, 2)
                if current['ended']: break
        except (ValueError, TypeError, IndexError) as error:
            if 'stale' in str(error): raise
            return {'confirmed_response': 0, 'interruptions': None, 'response_evaluation': '未评估：'+str(error)}
        return {'confirmed_response': 0, 'interruptions': None, 'response_evaluation': '未评估：未到达规定响应场景'}

    @staticmethod
    def rank(candidates, preference):
        if not candidates: return
        low = min(c['remaining'] for c in candidates); high = max(c['remaining'] for c in candidates)
        terminals = sorted(set(resource_rank(c['evaluation']) for c in candidates))
        for c in candidates:
            steps = 100 * (high-c['remaining']) / (high-low) if high > low else 100
            terminal = 100 * terminals.index(resource_rank(c['evaluation'])) / (len(terminals)-1) if len(terminals) > 1 else 100
            c['ranking'] = {'steps': round(steps, 2), 'terminal': round(terminal, 2), 'average': round((steps+terminal)/2, 2)}
        def key(c):
            ev = tuple(-v for v in resource_rank(c['evaluation']))
            common = (not c['goal_met'],)
            if preference == 'shortest': return (*common, c['remaining'], c['conditional'], *ev, c['id'])
            if preference == 'balanced': return (*common, -c['ranking']['average'], c['conditional'], c['remaining'], *ev, c['id'])
            if preference == 'safest':
                robust = c['robustness']
                return (*common, robust['status'] != 'evaluated', -sum(s.get('original_terminal_retained', False) for s in robust['scenarios']), -sum(s.get('continued', False) for s in robust['scenarios']), *ev, c['remaining'], c['id'])
            return (*common, *ev, c['conditional'], c['remaining'], c['id'])
        candidates.sort(key=key)

    def followup_candidate(self, sid, state):
        """Recheck a selected continuation; any observed deviation triggers search."""
        ctx=self.context(sid); follow=ctx.get('followup')
        if not follow or follow['token'][2:] != self.token(state,ctx)[2:] or follow['source_epoch'] != ctx['source_epoch']: return None
        steps=deepcopy(follow['candidate']['steps'])
        actual=digest(canonical_state([public_state(state['state']),state['raw']]))
        expected=follow['expected']
        # The native UI can automatically answer empty response windows before
        # the service observes them. Only those rule acknowledgements may skip.
        while actual != expected and steps and steps[0].get('automatic'):
            step=steps.pop(0);expected=digest(canonical_state([step['state'],step['next_raw']]))
        settled=bool(state['raw']) and bytes.fromhex(state['raw'])[0] in (10,11) and not state['state'].get('chain_depth')
        declines_only=all(s.get('automatic') or s['decision'].get('selection') and
                          all(c['kind'] in ('pass','no') for c in s['decision']['selection']) for s in steps)
        # Different legal trigger orders can eliminate a later optional decline
        # window. Completion still requires the actual settled terminal, hand,
        # material/resource outcomes and LP; an outstanding active choice cannot
        # be silently skipped.
        if settled and declines_only and terminal_satisfied(follow['before'],follow['candidate']['terminal'],state['state']):
            ctx.update(auto=False,reason='已到达所选路线的实际终场',followup=None,last_planned=self.token(state,ctx))
            self.audit(ctx,'terminal_reached',actual=public_state(state['state']),original_goal_met=original_goal_met(ctx,state['state']),
                       source=follow['candidate'].get('terminal_source'),if_condition=follow['candidate'].get('terminal_if'))
            return {'finished':True}
        if actual != expected or not steps: return None
        prompt=model(state['raw'],state['state'],state.get('effects'))
        response=steps[0]['response']
        if not self.step_input_matches(steps[0],prompt,ctx['precise']):return None
        path=[state['raw']+':'+response]
        following=self.bridge(sid,state,path)
        for _ in range(20):
            if following['player'] != 1: break
            if public_state(state['state'])['unknown']:
                p=model(following['raw'],following['state'],following.get('effects'))
                decline=next((c for c in p['choices'] if c['semantic']['kind'] in ('pass','no')),None)
                if not decline:return None
                path.append(following['raw']+':'+decline['response'])
            else:path.append(following['raw']+':ai')
            following=self.bridge(sid,state,path)
        if digest(canonical_state([public_state(following['state']),following['raw']])) != digest(canonical_state([steps[0]['state'],steps[0]['next_raw']])):return None
        candidate=deepcopy(follow['candidate']);token=self.token(state,ctx)
        steps[0]['response']=response;steps[0]['bindings']=response_bindings(prompt,response)
        candidate.update(id=digest([token,[s['edge'] for s in steps]]),steps=steps,remaining=sum(not s.get('automatic') for s in steps),
                         token=token,path=path,validation='next_step_rechecked',reason='当前一步在新局面重新校验；后续沿用此前验证的所选路线，变化时重新搜索')
        with self.store.lock,self.lock:
            if not self.valid_token(sid,token):return None
            ctx['result']={'token':token,'candidates':[candidate],'preference':ctx['preference'],'precise':ctx['precise'],'status':'found','limited':False,
                           'nodes':1,'seconds':0,'limits':LIMITS,'rejected':{},'start':self.visible_state(state),'goal':ctx['goal']}
            ctx['last_planned']=token
        return candidate

    @staticmethod
    def step_input_matches(step,prompt,precise):
        try:
            actual=semantic_response(prompt,step['response'])
            return semantic_equal(step.get('bound_decision',step['decision']),actual,True) and semantic_equal(step['decision'],actual,precise)
        except (ValueError,IndexError,KeyError,TypeError,StopIteration):return False

    def execute(self, body):
        sid = body['id']; ctx = self.context(sid)
        if ctx.get('forecast_meta'): raise ValueError('临时方案通过步骤确认推进，不执行真实对局输入')
        with self.store.lock, self.lock:
            result = ctx.get('result')
            candidate = next((c for c in (result or {}).get('candidates', []) if c['id'] == body.get('candidate')), None)
            if not candidate or not self.valid_token(sid, candidate['token']): raise ValueError('候选已过期，请从当前局面重新规划')
            if ctx.get('pending'): raise ValueError('上一步仍在等待引擎确认')
            state = self.state(sid); step = candidate['steps'][0]
            # Rebind against the live prompt immediately before submission.
            response=step['response']
            if not self.step_input_matches(step,model(state['raw'],state['state'],state.get('effects')),ctx['precise']):raise ValueError('当前具体效果、卡牌实例或选择窗口已经变化')
            lease = uuid.uuid4().hex
            self.write_bytes(self.store.session_path(sid)/'modular-lease.txt', lease.encode('ascii'))
            ctx['pending'] = {'token': candidate['token'], 'step': deepcopy(step), 'lease': lease,
                              'terminal_source':candidate.get('terminal_source'),'terminal_if':candidate.get('terminal_if'),
                              'expected': candidate['terminal'], 'candidate': candidate['id'], 'remaining': len(candidate['steps']),
                              'remaining_decisions': candidate['remaining'],
                              'source_epoch': ctx['source_epoch'],
                              'before': public_state(state['state']), 'node': state['node']}
            remainder=deepcopy(candidate);remainder['steps']=remainder['steps'][1:]
            ctx['followup']={'candidate':remainder,'expected':digest(canonical_state([step['state'],step['next_raw']])),
                             'before':public_state(state['state']),'token':candidate['token'],'source_epoch':ctx['source_epoch']}
            ctx['result'] = None
            if ctx['original_goal'] is None: ctx.update(original_goal=terminal_key(candidate['terminal']),original_goal_kind='board',original_terminal=deepcopy(candidate['terminal']))
            self.audit(ctx, 'decision_submitted', **ctx['pending'], preference=ctx['preference'])
        try:
            return self.bridge(sid, state, [response], command='answer', lease=lease)
        except ValueError as error:
            with self.lock:
                rows, _ = read_journal(self.store.session_path(sid)/'native.jsonl', sid)
                boundary = next((r['seq'] for r in rows if r.get('kind') == 'checkpoint' and r.get('node') == state['node']), float('inf'))
                committed = any(r['seq'] > boundary and r.get('kind') == 'response' and r.get('actor') == 'modular_ai' and r.get('raw', '').startswith(response) for r in rows)
                if committed:
                    ctx.update(auto=False, reason='输入已记录，等待引擎确认；不会重复提交')
                    self.audit(ctx, 'acknowledgement_missing', reason=str(error))
                    self.reconcile(sid)
                    return {'status': 'submitted_unconfirmed', 'token': lease}
                ctx['pending'] = None
                ctx['followup'] = None
                if 'stale' not in str(error): ctx['auto'] = False
                self.cancel_lease(sid)
                self.audit(ctx, 'submission_failed')
            raise

    def reconcile(self, sid):
        with self.lock:
            return self._reconcile(sid)

    def _reconcile(self, sid):
        ctx = self.context(sid); state = self.state(sid); pending = ctx.get('pending')
        if not state.get('running',True) and (ctx.get('auto') or pending):
            self.cancel_lease(sid)
            ctx.update(auto=False,pending=None,followup=None,reason='引擎已结束，操作记录已保留')
            self.audit(ctx,'engine_closed',unconfirmed=bool(pending))
            return state
        if pending and state['version'] != pending['token'][0] and not state['answered'] and state['player'] == 0:
            rows, _ = read_journal(self.store.session_path(sid)/'native.jsonl', sid)
            # Only engine response + subsequent actual decision boundary is completion.
            boundary = next((r['seq'] for r in rows if r.get('kind') == 'checkpoint' and r.get('node') == pending['node']), float('inf'))
            subsequent = [r for r in rows if r['seq'] > boundary]
            matched = any(r.get('kind') == 'response' and r.get('actor') == 'modular_ai' and r.get('raw', '').startswith(pending['step']['response']) for r in subsequent)
            from protocol import packets
            rejected = any(msg == 1 for r in subsequent if r.get('kind') == 'batch' for _, msg, _ in packets(bytes.fromhex(r.get('raw', ''))))
            matched &= not rejected
            if matched:
                ctx['completed'].append({'step':pending['step'], 'lease':pending['lease'], 'token':pending['token'],
                                         'actual':public_state(state['state']), 'version':state['version']})
                self.audit(ctx, 'decision_confirmed', source=pending['step']['source'], version=state['version'])
                if pending['remaining_decisions'] <= (0 if pending['step']['automatic'] else 1) and pending['token'][3] == ctx['preference_version'] and pending.get('source_epoch', 0) == ctx['source_epoch'] and not state['state'].get('chain_depth') and bytes.fromhex(state['raw'])[0] in (10,11) and terminal_satisfied(pending['before'], pending['expected'], state['state']):
                    ctx.update(auto=False, reason='已到达所选路线的实际终场')
                    ctx['last_planned'] = self.token(state, ctx)
                    self.audit(ctx, 'terminal_reached', actual=public_state(state['state']), original_goal_met=original_goal_met(ctx,state['state']),
                               source=pending.get('terminal_source'),if_condition=pending.get('terminal_if'))
            else:
                ctx.update(auto=False, reason='引擎未确认此决策，保留真实局面并暂停')
            ctx['pending'] = None
            self.save(ctx)
        return state

    def automatic(self, body):
        ctx = self.context(body['id'])
        if ctx.get('forecast_meta'): raise ValueError('临时方案不启用自动打牌，请使用步骤图')
        if type(body.get('enabled')) is not bool: raise ValueError('自动模式设置无效')
        with self.lock:
            ctx['auto'] = body['enabled']; self.cancel_lease(ctx['id'])
            ctx['reason'] = '正在准备自动路线' if ctx['auto'] else '已由用户停止自动执行'
            self.audit(ctx, 'mode_changed', enabled=ctx['auto'])
        self.ensure_worker()
        return self.status(ctx['id'])

    def ensure_worker(self):
        with self.lock:
            if self.worker and self.worker.is_alive(): return
            self.worker = threading.Thread(target=self.run, daemon=True, name='modular-ygo-ai'); self.worker.start()

    def run(self):
        while not self.store.closing:
            for sid, ctx in list(self.sessions.items()):
                if ctx.get('forecast_meta'): continue
                try:
                    self.library.sync()
                    state = self.reconcile(sid)
                    if ctx['busy'] or ctx['pending'] or state['answered'] or state['player'] != 0: continue
                    if not state['running']: ctx['auto'] = False; continue
                    changed = ctx.get('last_planned') is not None and ctx.get('last_planned') != self.token(state, ctx)
                    if not ctx['auto'] and not changed: continue
                    ctx['busy'] = True
                    continued=self.followup_candidate(sid,state) if ctx['auto'] else None
                    cached=ctx.get('result')
                    ready=bool(cached and cached.get('candidates') and cached.get('token')==self.token(state,ctx)
                               and self.valid_token(sid,cached['token']))
                    result = cached if continued or ready else self.search(sid)
                    if not ctx['auto']: continue
                    if not result['candidates']:
                        ctx.update(auto=False, reason=message(result['status'])); self.audit(ctx, 'ai_paused', reason=ctx['reason'])
                    else:
                        candidate = result['candidates'][0]
                        self.execute({'id': sid, 'candidate': candidate['id']})
                        if ctx['auto']: ctx['reason'] = '内置 YGO AI 正在按当前偏好执行'
                except (ValueError, OSError, KeyError) as error:
                    ctx.update(reason=message(str(error)))
                    if 'stale' not in str(error): ctx['auto'] = False
                finally: ctx['busy'] = False
            time.sleep(.3)

    def status(self, sid):
        ctx = self.context(sid)
        try: state = self.reconcile(sid)
        except ValueError: state = None
        with self.lock:
            value={k:deepcopy(v) for k,v in ctx.items() if k not in ('followup','completed','audit','result','pending') and not k.startswith('forecast_')}
            value['result']=self.public_result(ctx['result']) if ctx.get('result') else None
            value['pending']={k:ctx['pending'].get(k) for k in ('lease','token','node','remaining_decisions')} if ctx.get('pending') else None
            value['completed']=[{'version':item['version'],'step':{k:deepcopy(item['step'].get(k)) for k in ('source','decision','bindings')}} for item in ctx['completed']]
            # Full evidence stays in the local audit file. Frequent UI polling
            # must not copy every historical candidate and snapshot repeatedly.
            value['audit']=[{k:deepcopy(v) for k,v in item.items() if k in ('time_ms','kind','preference','goal','sources','source',
                            'version','reason','enabled','candidates','status','original_goal_met','precise','consumer','intent','if_condition')} for item in ctx.get('audit',[])]
        history=[step for step in self.decision_history(sid) if not step['automatic']]
        value['actual_count']=len(history)
        value['actual_steps']=history[-12:]
        for step in value['actual_steps']:
            selection=next(iter(step['decision'].get('selection',[])),{})
            if selection.get('effect'):
                step['effect_label']=effect_clause({'cards':[selection.get('card',{})], 'engine_effect':selection['effect'],
                    'effect':{'description_id':selection['effect'].get('description')}}, {str(k):v for k,v in self.store.catalog.cards.items()})
        return {**value, 'state': self.visible_state(state) if state else None, 'library': self.library.summary()}

    @staticmethod
    def public_result(result):
        result=deepcopy(result)
        for candidate in result.get('candidates', []):
            candidate.pop('path',None)
            for step in candidate.get('steps',[]):
                for key in ('next_raw','next_effects','if_memory'):step.pop(key,None)
        return result
