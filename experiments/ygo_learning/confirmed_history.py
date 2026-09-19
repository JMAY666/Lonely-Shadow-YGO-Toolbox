"""Commit only exact engine acknowledgements; rebuild from the accepted prefix."""
from contract_v2 import build,feature_arrays,committed_history


class ConfirmedHistory:
    def __init__(self):self.rows=[];self.windows=set()

    def commit(self, bundle, features, index, acknowledgement):
        window=tuple(bundle['window']);option=bundle['candidates'][index]
        if window in self.windows:raise ValueError('duplicate_acknowledgement')
        if (acknowledgement.get('version'),acknowledgement.get('raw'))!=window:
            raise ValueError('acknowledgement_window_mismatch')
        if not acknowledgement.get('acknowledged') or acknowledgement.get('response') not in option['responses']:
            raise ValueError('acknowledgement_response_mismatch')
        if acknowledgement.get('following_version',-1)<=window[0]:raise ValueError('missing_successor')
        self.rows.append(committed_history(features,index,bundle['observation']));self.windows.add(window)

    @classmethod
    def rebuild(cls, steps, catalog, supported_codes):
        history=cls()
        for step in steps:
            bundle=build(step['before'],catalog)
            features=feature_arrays(bundle,history.rows,supported_codes)
            indexes=[i for i,c in enumerate(bundle['candidates']) if step['response'] in c['responses']]
            if len(indexes)!=1:raise ValueError('accepted_prefix_cannot_be_rebound')
            history.commit(bundle,features,indexes[0],step['acknowledgement'])
        return history
