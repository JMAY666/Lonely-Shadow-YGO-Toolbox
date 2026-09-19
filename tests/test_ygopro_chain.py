"""Synthetic fixed-layout fixtures; no real duel data or private identities."""
import struct
import unittest

from test_ygopro_live import Memory, PROFILE
from ygopro_capture import CaptureError
from ygopro_live import read_snapshot


def message(m, kind):
    struct.pack_into('<H', m.memory[m.game+PROFILE['duel_info']], 32, kind)


def vector(m, name, address, data):
    m.memory[m.game+PROFILE[name]] = struct.pack('<3Q', address, address+len(data), address+len(data))
    m.memory[address] = data


def chain(m, *, location=8, sequence=0, started=0, code=1184620):
    row = bytearray(64)
    struct.pack_into('<IIiiiB', row, 24, code, code*16, 1, location, sequence, started)
    vector(m, 'chain_vector', 0x8000000, row)


def selection(m, *, server_player=1, flag=0, forced=0, location=2, special=1):
    message(m, 16)
    hint = 0x8100000
    m.memory[m.game+PROFILE['hint_widget']] = struct.pack('<Q', hint)
    m.memory[hint+PROFILE['gui_visible']] = b'\1'
    pointer = m.pointers[0, location]
    code = struct.unpack('<I', m.memory[pointer+PROFILE['client_code']])[0]
    # The fourth location byte is a position for ordinary entries, not zero.
    payload = bytes([16, server_player, 1, special])+bytes(8)+struct.pack('<BBIBBBBI', flag, forced, code, 1, location, 0, 10, code*16)
    m.memory[m.base+PROFILE['message']] = payload
    m.memory[m.base+PROFILE['message_size']] = struct.pack('<Q', len(payload))
    vector(m, 'activation_vector', 0x8200000, struct.pack('<Q', pointer))
    vector(m, 'activation_descriptions', 0x8300000, struct.pack('<II', code*16, flag | forced<<8))
    m.memory[pointer+PROFILE['client_selectable']] = b'\1'
    m.memory[pointer+PROFILE['client_commands']] = struct.pack('<I', 1)
    return pointer


class ChainTests(unittest.TestCase):
    def test_public_chain_does_not_dereference_source_or_target_and_started_is_not_resolved(self):
        m = Memory();chain(m, location=1, sequence=14, started=1)
        row = read_snapshot(m, m.base, PROFILE)['chain']['links'][0]
        self.assertEqual(row['code'],1184620);self.assertIsNone(row['sequence'])
        self.assertTrue(row['processing_started'])
        self.assertNotIn('resolved',row);self.assertNotIn('targets',row);self.assertNotIn('negated',row)

    def test_updating_chain_is_not_a_claim_of_no_chain_and_invalid_rows_fail_closed(self):
        for kind in (70,74):
            m=Memory();message(m,kind);m.private.add(m.game+PROFILE['chain_vector'])
            self.assertEqual(read_snapshot(m,m.base,PROFILE)['chain']['status'],'updating')
        for options in ({'location':4,'sequence':7},{'started':2},{'code':0}):
            m=Memory();chain(m,**options)
            with self.assertRaises(CaptureError):read_snapshot(m,m.base,PROFILE)
        m=Memory();m.memory[m.game+PROFILE['chain_vector']]=struct.pack('<3Q',0x8000000,0x8000001,0x8000040)
        with self.assertRaisesRegex(CaptureError,'边界'):read_snapshot(m,m.base,PROFILE)

    def test_own_live_menu_is_observation_only_and_position_byte_is_supported(self):
        m=Memory();selection(m,forced=1)
        row=read_snapshot(m,m.base,PROFILE)['response']
        self.assertEqual(row['status'],'client_selection');self.assertFalse(row['rules_verified'])
        self.assertEqual(len(row['choices']),1);self.assertTrue(row['choices'][0]['forced'])
        self.assertNotIn('response',row['choices'][0]);self.assertNotIn('legal',row['choices'][0])

    def test_other_players_packet_is_not_decoded(self):
        m=Memory();selection(m,server_player=0)
        self.assertEqual(read_snapshot(m,m.base,PROFILE)['response']['status'],'unconfirmed')
        reads=[n for a,n in m.reads if a==m.base+PROFILE['message']]
        self.assertTrue(reads);self.assertEqual(set(reads),{2})
        self.assertNotIn((m.game+PROFILE['activation_vector'],24),m.reads)

    def test_stale_cached_menu_is_rejected_after_response_even_without_resource_changes(self):
        for part in ('selectable','commands','hint','pointer','description'):
            m=Memory();p=selection(m)
            self.assertEqual(read_snapshot(m,m.base,PROFILE)['response']['status'],'client_selection')
            if part=='selectable':m.memory[p+PROFILE['client_selectable']]=b'\0'
            elif part=='commands':m.memory[p+PROFILE['client_commands']]=bytes(4)
            elif part=='hint':m.memory[0x8100000+PROFILE['gui_visible']]=b'\0'
            elif part=='pointer':m.memory[0x8200000]=struct.pack('<Q',p+8)
            else:m.memory[0x8300000]=bytes(8)
            self.assertEqual(read_snapshot(m,m.base,PROFILE)['response']['status'],'unconfirmed',part)

    def test_unsupported_choices_are_omitted_without_reading_their_candidate_fields(self):
        for options in ({'flag':1},{'location':1},{'special':127}):
            m=Memory();p=selection(m,**options)
            m.private.update([p+PROFILE['client_selectable'],p+PROFILE['client_commands']])
            read=m.read
            forbidden=[m.base+PROFILE['message']+14,m.base+PROFILE['message']+22,0x8200000,0x8300000]
            def protect(a,n):
                if any(a<=f<a+n for f in forbidden):raise AssertionError('Unsupported candidate identity read')
                return read(a,n)
            m.read=protect
            v=read_snapshot(m,m.base,PROFILE)['response']
            self.assertEqual(v['status'],'unconfirmed');self.assertEqual(v['choices'],[])

    def test_message_flags_and_chain_changes_are_part_of_snapshot_consistency(self):
        for part in ('message','chain','selectable'):
            m=Memory();p=selection(m);chain(m);read=m.read;calls=0
            addr={'message':m.game+PROFILE['duel_info']+32,'chain':0x8000000,
                  'selectable':p+PROFILE['client_selectable']}[part]
            def race(a,n):
                nonlocal calls
                data=read(a,n)
                if a==addr:
                    calls+=1
                    if calls>1:data=bytes([data[0]^1])+data[1:]
                return data
            m.read=race
            with self.assertRaisesRegex(CaptureError,'读取期间'):read_snapshot(m,m.base,PROFILE)
