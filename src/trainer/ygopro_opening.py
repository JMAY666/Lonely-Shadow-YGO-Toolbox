"""Freeze a verified initial deal; later draws never replace the opening hand."""
from collections import Counter
from copy import deepcopy
import uuid


def create(armed):
    return {'status':'waiting' if armed else 'missed', 'armed':armed, 'cards':[], 'candidate':None,
            'observed_count':0, 'snapshot_id':None, 'confirmed':None,
            'error':'' if armed else '连接时已经开局，无法确认最初起手；请在下一局选择先后攻前开始监测。'}


def observe(opening, sample, frame, now):
    if opening['status'] in ('ready', 'missed'):return False
    before = deepcopy(opening)
    if sample and sample.get('error'):
        opening['error'] = sample['error']
        return opening != before
    if sample:
        hand = sample['hand']
        opening['observed_count'] = len(hand)
        if sample.get('draw') and sample['turn'] == 0 and opening['candidate'] is None:
            opening['candidate'] = list(sample['draw'])
            opening['status'] = 'dealing'
        candidate = opening['candidate']
        if candidate and sample['turn'] <= 1 and Counter(hand) == Counter(candidate):
            opening.update(status='ready', cards=list(hand), snapshot_id=uuid.uuid4().hex,
                           captured_ms=now(), captured_turn=sample['turn'],
                           detected_order='first' if frame['evidence']['is_first'] else 'second',
                           method='initial-draw-and-own-hand', error='')
            opening['candidate'] = None
            return True
        opening['error'] = ''
    turn = frame.get('evidence', {}).get('turn', 0)
    if frame['phase'] == 'detected' and (not opening['candidate'] or turn > 1):
        opening.update(status='missed', error='未完整捕捉到本局初始发牌，请在下一局选择先后攻前开启监测。')
    return opening != before


def public(opening):
    return {key:deepcopy(value) for key,value in opening.items() if key not in ('candidate','armed')}
