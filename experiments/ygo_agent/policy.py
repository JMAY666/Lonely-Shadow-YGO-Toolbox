"""CPU-only, pinned policy inference with transactional recurrent state."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import sys
import time

LOCAL = Path(__file__).resolve().parents[2] / '.local/ygo-agent-pilot'


class Policy:
    def __init__(self):
        if __package__:
            from .bootstrap import verify_assets
        else:
            from bootstrap import verify_assets
        verify_assets()
        import numpy as np
        from ai_edge_litert.interpreter import Interpreter
        sys.path.insert(0, str(LOCAL / 'upstream'))
        from ygoinf import features
        self.np, self.features = np, features
        features.init_code_list(str(LOCAL / 'code_list.txt'))
        # The native Windows loader does not accept every Unicode filesystem path.
        self.interpreter = Interpreter(model_content=(LOCAL / 'model.tflite').read_bytes(), num_threads=2)
        self.interpreter.allocate_tensors()
        expected = [[1, 512], [1, 512], [1, 24, 12], [1, 160, 41], [1, 23], [1, 32, 14]]
        if [d['shape'].tolist() for d in self.interpreter.get_input_details()] != expected:
            raise ValueError('Unexpected model input contract')
        self.rstate, self.history = features.init_rstate(), features.HistoryActions()
        self.pending = None

    def _step(self, data):
        f, np = self.features, self.np
        value = f.Input.model_validate(data)
        actions = f.get_legal_actions(value.action_msg)
        if not 0 < len(actions) <= f.MAX_ACTIONS:
            raise ValueError(f'Model action capacity exceeded: {len(actions)}')
        cards, specs = f.encode_cards(value.cards)
        with redirect_stdout(io.StringIO()): encoded = f.encode_legal_actions(actions, specs)
        obs = {'cards_': cards, 'global_': f.encode_global(value.global_, value.cards),
               'actions_': encoded, 'h_actions_': self.history.encode(value.global_.turn)}
        tensors = [*self.rstate, *(np.array([obs[k]]) for k in sorted(obs))]
        if len(actions) == 1:
            probs = [1.0]
        else:
            for detail, tensor in zip(self.interpreter.get_input_details(), tensors):
                self.interpreter.set_tensor(detail['index'], tensor)
            self.interpreter.invoke()
            output = [self.interpreter.get_tensor(d['index']) for d in self.interpreter.get_output_details()]
            self.rstate = output[0], output[1]
            probs = output[2][0, :len(actions)].tolist()
        if not all(np.isfinite(p) and p >= 0 for p in probs) or sum(probs) <= 0:
            raise ValueError('Invalid model action scores')
        order = sorted(range(len(actions)), key=lambda i: (-probs[i], i))
        predictions = [{'index': i, 'probability': probs[i], 'response': actions[i].response,
                        'can_finish': actions[i].can_finish} for i in order]
        choice = order[0]
        self.history.update(encoded[choice], value.global_.turn, value.global_.phase)
        return predictions

    def recommend(self, native):
        if self.pending is not None: raise ValueError('Previous recommendation has not been acknowledged')
        before = deepcopy((self.rstate, self.history))
        started = time.perf_counter()
        selected, rankings = [], []
        try:
            for _ in range(25):
                candidates = self._step(native.input(selected))
                rankings.append(candidates)
                best = candidates[0]
                if native.prompt['mode'] not in ('cards', 'sum'): break
                if best['response'] == -1: break
                if best['response'] in selected: raise ValueError('Duplicate material selection')
                selected.append(best['response'])
                if native.prompt['mode'] == 'sum':
                    if best['can_finish'] and len(selected) >= native.prompt['minimum']: break
                elif len(selected) == native.prompt['maximum']: break
            else: raise ValueError('Material decision limit reached')
            response = native.response(best, selected)
            if response is None: raise ValueError('Model selection cannot be encoded as a native response')
            result = {'version': native.snapshot['version'], 'prompt': native.snapshot['raw'], 'response': response,
                      'label': native.label(response), 'inference_ms': round((time.perf_counter() - started) * 1000, 3),
                      'rankings': rankings, 'selected': selected}
            after = deepcopy((self.rstate, self.history))
            self.pending = (result, after)
            return result
        finally:
            self.rstate, self.history = before

    def commit(self, version, prompt, response):
        if self.pending is None: raise ValueError('No pending recommendation')
        result, state = self.pending
        if (version, prompt, response) != (result['version'], result['prompt'], result['response']):
            raise ValueError('Actual action differs; discard this policy session and rebuild its history')
        self.rstate, self.history = state
        self.pending = None
