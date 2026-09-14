from copy import deepcopy
from pathlib import Path
import sys
import unittest
import json
import uuid
import struct
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from timeline import route_rows, timeline_nodes
from report import build_report
from app import atomic_json, read_json
import test_store


def row(seq, kind, **fields):
    return dict(seq=seq, kind=kind, time_ms=seq, **fields)


STATE = dict(turn=1, phase=4, turn_player=0, lp=[8000, 8000], cards=[], chain_depth=0)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.rows = [row(1, 'begin'), row(2, 'checkpoint', node=1, state=STATE),
                     row(3, 'response'), row(4, 'checkpoint', node=2, state=STATE),
                     row(5, 'response'), row(6, 'checkpoint', node=3, state=STATE)]

    def test_rewind_then_forward_keeps_original_prefix_without_duplicate_events(self):
        original = deepcopy(self.rows)
        rows = self.rows + [row(7, 'rewind', target=1, state=STATE)]
        active, full, nodes = route_rows(rows)
        self.assertEqual([r['seq'] for r in active], [1, 2, 7])
        self.assertEqual([r['seq'] for r in full], [1, 2, 3, 4, 5, 6])
        self.assertEqual(nodes, [1, 2, 3])
        rows += [row(8, 'rewind', target=2, state=STATE)]
        self.assertEqual([r['seq'] for r in route_rows(rows)[0]], [1, 2, 3, 4, 8])
        self.assertEqual(self.rows, original)

    def test_branch_discards_only_suffix_and_supports_repeated_rewinds(self):
        rows = self.rows + [row(7, 'rewind', target=2, state=STATE), row(8, 'branch', target=2),
                            row(9, 'response'), row(10, 'checkpoint', node=4, state=STATE),
                            row(11, 'rewind', target=1, state=STATE)]
        active, full, nodes = route_rows(rows)
        self.assertEqual(nodes, [1, 2, 4])
        self.assertEqual([r['seq'] for r in active], [1, 2, 11])
        self.assertNotIn(6, [r['seq'] for r in full])
        with self.assertRaises(ValueError): route_rows(rows + [row(12, 'rewind', target=3)])

    def test_completed_report_uses_restored_state_and_only_effective_events(self):
        state = {**STATE, 'lp': [7000, 8000]}
        rows = [row(1, 'begin'), row(2, 'checkpoint', node=1, state=STATE),
                row(3, 'batch', raw='6400e8030000', state=state),
                row(4, 'checkpoint', node=2, state=state), row(5, 'rewind', target=1, state=STATE),
                row(6, 'end', reason='manual')]
        meta = dict(id='fixture', started_ms=0, deck=dict(main=[], extra=[], side=[]))
        report = build_report(meta, rows, [])
        self.assertEqual(report['actions'], [])
        self.assertEqual(report['final_state']['lp'], [8000, 8000])
        self.assertEqual(report['warnings'], [])

    def test_chain_actions_keep_numbers_and_merge_until_all_evidence_completed(self):
        rows = [row(2, 'checkpoint', node=1, state=STATE), row(10, 'checkpoint', node=2, state=STATE)]
        actions = [dict(id='3:0', kind='effect', summary='效果一', cards=[], evidence_refs=['3:0', '9:0']),
                   dict(id='5:0', kind='effect', summary='效果二', cards=[], evidence_refs=['5:0', '7:0']),
                   dict(id='12:0', kind='effect', summary='处理中', cards=[], evidence_refs=['12:0'])]
        nodes, pending = timeline_nodes(rows, actions)
        self.assertEqual(nodes[0]['steps'], [])
        self.assertEqual([s['number'] for s in nodes[1]['steps']], [1, 2])
        self.assertEqual([s['number'] for s in pending], [3])

    def test_delayed_evidence_cannot_move_step_one_behind_step_two(self):
        rows = [row(2,'checkpoint',node=1,state=STATE),row(10,'checkpoint',node=2,state=STATE),row(20,'checkpoint',node=3,state=STATE)]
        actions = [dict(id='3:0',kind='effect',summary='延迟完成',cards=[],evidence_refs=['3:0','15:0']),
                   dict(id='5:0',kind='effect',summary='后续动作',cards=[],evidence_refs=['5:0','7:0'])]
        nodes,pending=timeline_nodes(rows,actions)
        self.assertEqual(nodes[1]['steps'],[])
        self.assertEqual([s['number'] for s in nodes[2]['steps']],[1,2])
        self.assertEqual(pending,[])


class TimelineStoreTests(unittest.TestCase):
    def setUp(self):
        test_store.StoreTests.setUp(self)
        self.sid = str(uuid.uuid4())
        self.folder = self.store.session_path(self.sid)
        self.folder.mkdir()
        self.meta = dict(id=self.sid, name='隔离回退测试', started_ms=1, status='running',
                         plan_stage='recording', deck=self.deck, catalog={}, expansion={'name':'测试', 'notes':''})
        atomic_json(self.folder / 'session.json', self.meta)
        self.rows = [row(1,'begin'), row(2,'checkpoint',node=1,state=STATE)]
        self.write_rows()
        atomic_json(self.folder / 'timeline-state.json', {'cursor':1, 'revision':0, 'at_node':True})
        self.store.alive = Mock(return_value=True)

    def tearDown(self): test_store.StoreTests.tearDown(self)

    def write_rows(self):
        (self.folder / 'native.jsonl').write_text('\n'.join(json.dumps({**r,'session':self.sid}) for r in self.rows)+'\n','utf8')

    def test_acceptance_busy_and_stale_requests_never_overwrite_pending_command(self):
        for node, revision in [(True,0),(2,0),(1,1),(1,True)]:
            with self.assertRaises(ValueError): self.store.rewind(dict(id=self.sid,node=node,revision=revision))
        result = self.store.rewind(dict(id=self.sid,node=1,revision=0))
        command = (self.folder / 'rewind.request').read_bytes()
        self.assertEqual(result['status'],'queued')
        with self.assertRaisesRegex(ValueError,'正在恢复'): self.store.rewind(dict(id=self.sid,node=1,revision=0))
        self.assertEqual((self.folder / 'rewind.request').read_bytes(),command)
        self.store.alive.return_value=False
        self.assertEqual(self.store.timeline(self.sid)['operation']['error'],'engine_closed')

    def test_response_checkpoint_does_not_mark_a_place_selection_as_a_settled_node(self):
        self.rows.append(row(3,'checkpoint',node=2,state=STATE,prompt=18,player=0,restorable=True))
        self.write_rows()
        atomic_json(self.folder/'timeline-state.json',{'cursor':2,'revision':1,'at_node':True,'available_nodes':[1,2]})
        timeline=self.store.timeline(self.sid)
        self.assertEqual(timeline['cursor'],1)
        self.assertEqual(timeline['engine_cursor'],2)
        self.assertFalse(timeline['at_node'])
        self.assertEqual([n['id'] for n in timeline['nodes']],[1])

    def test_save_after_restore_excludes_old_suffix_and_later_rewind_cannot_change_plan(self):
        state = {**STATE,'lp':[7000,8000]}
        card = dict(code=55144522, name='强欲之壶', instance_id=1, controller=0, owner=0, location=2, sequence=0, position=1, reason=0x400)
        initial = {**STATE, 'cards':[card]}
        self.meta['deck'] = dict(main=[55144522],extra=[],side=[])
        self.meta['expansion']['actual_opening'] = [55144522]
        atomic_json(self.folder / 'session.json',self.meta)
        self.rows = [row(1,'loaded',state={**STATE,'cards':[{**card,'location':1}]}),row(2,'batch',raw=(bytes([90,0,1])+struct.pack('<I',55144522)).hex(),state=initial),
                     row(3,'checkpoint',node=1,state=initial),row(4,'batch',raw='6400e8030000',state=state),
                     row(5,'checkpoint',node=2,state=state),row(6,'rewind',target=1,state=initial),row(7,'end',reason='manual')]
        self.write_rows()
        self.store.alive.return_value=False
        body=dict(id=self.sid,name='已确认路线',notes='测试')
        preview=self.store.preview_plan(body)
        saved=self.store.save_plan({**body,'confirmation':preview['confirmation']})
        self.assertEqual(saved['actions'],[])
        self.assertEqual(saved['final_state']['lp'],[8000,8000])
        before=self.store.plan_path(self.sid).read_bytes()
        with self.assertRaises(ValueError): self.store.rewind(dict(id=self.sid,node=1,revision=0))
        self.assertEqual(self.store.plan_path(self.sid).read_bytes(),before)

    def test_lost_acknowledgement_is_reconciled_only_after_committed_cursor_is_published(self):
        token = uuid.uuid4().hex
        atomic_json(self.folder / 'rewind-operation.json',dict(token=token,status='running'))
        self.rows.append(row(3,'rewind',target=1,revision=1,token=token,state=STATE))
        self.write_rows()
        self.assertEqual(self.store.timeline(self.sid)['operation']['status'],'running')
        atomic_json(self.folder / 'timeline-state.json',dict(cursor=1,revision=1,at_node=True))
        self.assertEqual(self.store.timeline(self.sid)['operation']['status'],'done')


if __name__ == '__main__': unittest.main()
