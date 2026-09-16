"""Project explicit source end-board marks onto a different, verified duel."""
from copy import deepcopy


def attach_terminal_marks(source, report):
    edits = report.get('annotations') or {}
    final = next((n.get('state') for n in report.get('review', {}).get('nodes', [])
                  if n.get('kind') == 'final'), None) or report.get('final_state') or {}
    cards = final.get('cards', [])
    for edge in source.get('edges', []):
        if not edge.get('terminal'): continue
        # These are source instances, not a list inferred from card text or zones.
        edge['terminal_marks'] = [
            {'card': deepcopy(card), 'mark': deepcopy(edits['final_marks'][str(card['instance_id'])]),
             'note': (edits.get('cards') or {}).get(str(card['instance_id']), '')}
            for card in cards if card.get('code') and
            (edits.get('final_marks') or {}).get(str(card.get('instance_id')), {}).get('marked')]
    return source


def marked_terminal(edge, state, precise=False):
    targets, used = [], set()
    marks = edge.get('terminal_marks', [])
    for entry in marks:
        source = entry['card']
        eligible = [c for c in state.get('cards', []) if c.get('instance_id') is not None
                    and c['instance_id'] not in used and c.get('code') and not c.get('unknown')
                    and all(c.get(k) == source.get(k) for k in ('code', 'controller', 'location'))
                    and (not precise or source.get('location') not in (4, 8)
                         or c.get('sequence') == source.get('sequence'))
                    and (source.get('location') not in (4, 8, 32, 64)
                         or bool(c.get('position', 0) & 10) == bool(source.get('position', 0) & 10))]
        eligible.sort(key=lambda c: (c.get('sequence') != source.get('sequence'), c['instance_id']))
        if not eligible: continue
        card = eligible[0]; used.add(card['instance_id'])
        targets.append({'card': deepcopy(card), 'mark': deepcopy(entry['mark']), 'note': entry['note']})
    return {'terminal_targets': targets, 'terminal_mark_count': len(marks),
            'terminal_mark_status': 'unmarked' if not marks else 'complete' if len(targets) == len(marks) else 'partial'}


def marked_evaluation(terminal):
    active = [t for t in terminal['terminal_targets'] if not t['card'].get('disabled')]
    return {'marked_cards': len(active),
            'marked_effects': sum(sum(bool(v) for v in t['mark'].get('effects', {}).values()) for t in active),
            'mark_status': terminal['terminal_mark_status'],
            'basis': '终场只按来源标记且匹配当前区域的卡牌数、标记效果数比较；未标记资源不计分，标记效果不等于可用阻抗次数'}
