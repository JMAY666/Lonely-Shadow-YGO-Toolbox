"""Internal transport for isolated P0B/P1 engine experiments only."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / '.local/ygo-learning/p0b-p1'


class NativeSession:
    def __init__(self, runtime, url):
        self.runtime = Path(runtime).resolve()
        allowed={(BASE/name/'runtime').resolve() for name in
                 ('desktop-check-development-modular','desktop-check-development-modular-secondary')}
        expected = self.runtime
        if self.runtime not in allowed or urllib.parse.urlparse(url).hostname != '127.0.0.1':
            raise ValueError('Only the fixed local isolated learning runtime is allowed')
        self.url, self.token, self.sid = url, None, None
        service = self.api('/api/bootstrap')
        if service.get('embedded') is not True or Path(service.get('runtime', '')).resolve() != expected:
            raise ValueError('Service identity does not match the experiment')
        self.token = service['token']
        self.samples = []

    def api(self, path, body=None):
        request = urllib.request.Request(self.url + path,
            data=None if body is None else json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json', **({'X-Trainer-Token': self.token} if self.token else {})})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    @property
    def folder(self):
        if not self.sid:
            raise ValueError('No experiment session')
        folder = (self.runtime / '_trainer/sessions' / self.sid).resolve()
        if folder.parent != (self.runtime / '_trainer/sessions').resolve():
            raise ValueError('Invalid session path')
        return folder

    def read(self, name):
        try:
            return json.loads((self.folder / name).read_text(encoding='utf-8'))
        except (FileNotFoundError, PermissionError, json.JSONDecodeError):
            return None

    def current(self, after=-1, timeout=25, any_player=False):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.read('modular-state.json')
            if value and value['version'] > after and not value['answered']:
                if any_player and value['state']['turn'] > 1:
                    return value
                raw = bytes.fromhex(value['raw'])
                if value['player'] == 0 and not (raw[0] == 16 and raw[2] == 0):
                    return value
            time.sleep(0.01)
        raise TimeoutError('The engine did not publish the expected decision')

    def start(self, deck, hand, name, opponent=None, responses=False):
        if self.sid:
            raise ValueError('Finish the previous experiment first')
        before = time.perf_counter()
        saved = self.api('/api/decks', {'name': 'TEST ONLY P1 ' + name + ' ' + uuid.uuid4().hex[:5], 'deck': deck})
        design = {'name': 'TEST ONLY P1 ' + name, 'notes': 'Public isolated engine contract experiment',
                  'revision': saved['revision'], 'conditions': {'hand_count': len(hand), 'slots': hand, 'banned': []},
                  'opponent_ai': bool(opponent), 'opponent_responses': responses}
        if opponent:
            design['opponent_config'] = opponent
        self.sid = self.api('/api/start', {'deck_id': saved['id'], 'design': design})['id']
        state = self.current()
        with (self.folder / 'native.jsonl').open(encoding='utf-8') as stream:
            header = json.loads(stream.readline())
        if header.get('test_control') is not True:
            raise ValueError('This engine does not have test-control authorization')
        if not state.get('learning', {}).get('available'):
            raise ValueError('Dynamic learning snapshot unavailable: ' + str(state.get('learning')))
        self.samples = []
        self.start_seconds = time.perf_counter() - before
        return state

    def request(self, command, state, paths, timeout=12, scenario=0):
        request_started = time.perf_counter()
        latest = self.read('modular-state.json')
        if not latest or (latest['version'], latest['raw'], latest['answered']) != (state['version'], state['raw'], False):
            raise ValueError('stale_state')
        lease = uuid.uuid4().hex
        if command == 'answer':
            (self.folder / 'modular-lease.txt').write_text(lease, encoding='ascii')
        value = f'{command} {state["version"]} {lease} {scenario} {len(paths)}\n' + '\n'.join(paths) + '\n'
        temporary = self.folder / 'learning-request.tmp'
        temporary.write_text(value, encoding='ascii')
        temporary.replace(self.folder / 'modular.request')
        began, deadline = time.perf_counter(), time.monotonic() + timeout
        reads, polls = 0.0, 0
        while time.monotonic() < deadline:
            read_started = time.perf_counter()
            result = self.read('modular-result.json')
            reads += time.perf_counter() - read_started
            polls += 1
            if result and result.get('token') == lease:
                result['transport_profile'] = {
                    'request_seconds': began - request_started,
                    'result_read_decode_seconds': reads, 'polls': polls,
                    'request_to_result_seconds': time.perf_counter() - request_started}
                return result, time.perf_counter() - began
            time.sleep(0.005)
        raise TimeoutError('Engine request acknowledgement unavailable')

    def probe(self, state, paths=(), scenario=0):
        result, seconds = self.request('probe', state, list(paths), scenario=scenario)
        result['transport_seconds'] = seconds
        return result

    def answer(self, state, response):
        began = time.perf_counter()
        result, _ = self.request('answer', state, [response])
        if result.get('status') != 'submitted':
            raise ValueError('Response not accepted: ' + str(result))
        following = self.current(state['version'], any_player=True)
        if following['player'] != 0:
            # The simple opponent may immediately consume its own window.
            # Observe a stable player checkpoint without issuing any further input.
            following = self.current(state['version'])
        if bytes.fromhex(following['raw'])[0] == 1:
            raise ValueError('Engine rejected the submitted response')
        self.samples.append({'version': state['version'], 'node': state['node'], 'raw': state['raw'],
                             'response': response, 'following_version': following['version'],
                             'acknowledged': True, 'wall_seconds': time.perf_counter() - began})
        return following

    def finish(self):
        if not self.sid:
            return None
        sid, folder = self.sid, self.folder
        self.api('/api/stop', {'id': sid})
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if self.api('/api/modular/state/' + sid).get('state', {}).get('running') is False:
                result = self.api('/api/report/' + sid)
                if result.get('status') == 'completed':
                    self.sid = None
                    return {'id': sid, 'folder': str(folder), 'report': result, 'responses': self.samples,
                            'start_seconds': self.start_seconds}
            time.sleep(0.03)
        raise TimeoutError('Engine did not finish the isolated experiment')
