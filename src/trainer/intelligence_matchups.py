"""Reviewed matchup notes, explicitly imported into personal breakpoint records."""
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from intelligence import text
from plan_tags import normalized


RESEARCH_TEXT_FIELDS = ('summary', 'recognition', 'priorities', 'warnings', 'metagame')


def load_catalog():
    return json.loads((Path(__file__).parent / 'matchups.json').read_text('utf-8'))


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', value):
        raise ValueError('主流对局资料编号无效')
    return value


def source_ids(value, available):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError('主流对局资料引用无效')
    if any(not isinstance(key, str) or key not in available for key in value):
        raise ValueError('主流对局资料引用不存在')
    return list(dict.fromkeys(value))


def validate_catalog(value):
    if not isinstance(value, dict): raise ValueError('主流对局资料格式无效')
    version = identifier(value.get('version'))
    reviewed = text(value.get('reviewed_at'), 40, True)
    window = text(value.get('window'), 200, True)
    sources, guides = value.get('sources'), value.get('guides')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 2000: raise ValueError('主流对局来源列表无效')
    if not isinstance(guides, list) or not 1 <= len(guides) <= 500: raise ValueError('主流对局资料列表无效')
    checked_sources = {}
    for source in sources:
        if not isinstance(source, dict): raise ValueError('主流对局来源格式无效')
        key = identifier(source.get('id'))
        if key in checked_sources: raise ValueError('主流对局来源编号重复')
        url = text(source.get('url'), 2000, True)
        parsed = urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or any(c.isspace() for c in url):
            raise ValueError('主流对局来源链接须为 HTTP 或 HTTPS')
        if source.get('kind') not in ('metagame', 'strategy', 'card_text'): raise ValueError('主流对局来源分类无效')
        checked = {'id': key, 'title': text(source.get('title'), 300, True), 'url': url,
                   'kind': source['kind'], 'note': text(source.get('note', ''))}
        for field in ('published_at', 'period'):
            if field in source: checked[field] = text(source[field], 200)
        checked_sources[key] = checked
    checked_guides = []; seen = set()
    for guide in guides:
        if not isinstance(guide, dict): raise ValueError('主流对局记录格式无效')
        key = identifier(guide.get('id'))
        if key in seen: raise ValueError('主流对局记录编号重复')
        seen.add(key)
        if guide.get('format') not in ('OCG', 'Master Duel'): raise ValueError('主流对局适用环境无效')
        checked = {'id': key, 'topic': text(guide.get('topic'), 80, True),
                   'title': text(guide.get('title'), 120, True), 'format': guide['format'],
                   'period': text(guide.get('period'), 200, True),
                   **{field: text(guide.get(field, '')) for field in RESEARCH_TEXT_FIELDS},
                   'source_ids': source_ids(guide.get('source_ids'), checked_sources),
                   'steps': deepcopy(guide.get('steps'))}
        if 'walkthrough' in guide: checked['walkthrough'] = deepcopy(guide['walkthrough'])
        if 'step_sources' in guide: checked['step_sources'] = deepcopy(guide['step_sources'])
        checked_guides.append(checked)
    return {'version': version, 'reviewed_at': reviewed, 'window': window,
            'sources': checked_sources, 'guides': checked_guides}


def validate_walkthrough(service, value, steps, available_sources):
    if not isinstance(value, dict): raise ValueError('典型推演格式无效')
    sequence, branches = value.get('sequence'), value.get('branches')
    if not isinstance(sequence, list) or not 1 <= len(sequence) <= 100: raise ValueError('典型推演需要 1–100 个步骤')
    if not isinstance(branches, list) or len(branches) > 30: raise ValueError('典型推演分支无效')
    checked_sequence = []
    for step in sequence:
        if not isinstance(step, dict): raise ValueError('典型推演步骤格式无效')
        code, index = step.get('card'), step.get('step_index')
        if code is not None: service.check_code(code, [code])
        if index is not None and (type(index) is not int or not 0 <= index < len(steps)):
            raise ValueError('典型推演关联的断点步骤不存在')
        checked_sequence.append({'card': code, 'step_index': index,
                                 'action': text(step.get('action'), required=True), 'result': text(step.get('result'), required=True)})
    checked_branches = []
    for branch in branches:
        if not isinstance(branch, dict): raise ValueError('典型推演分支格式无效')
        checked_branches.append({'label': text(branch.get('label'), 120, True), 'body': text(branch.get('body'), required=True)})
    return {'premise': text(value.get('premise'), required=True), 'sequence': checked_sequence,
            'branches': checked_branches, 'conclusion': text(value.get('conclusion'), required=True),
            'source_ids': source_ids(value.get('source_ids'), available_sources)}


def import_topic_name(name, version, topics):
    existing = {normalized(topic['name']) for topic in topics.values()}
    if normalized(name) not in existing: return name
    number = 1
    while True:
        # Reserve space within topic.save's 80-character limit; full version stays in research.
        suffix = f'（资料版 {version[:40]}' + (f' · {number}' if number > 1 else '') + '）'
        candidate = name[:80 - len(suffix)].rstrip() + suffix
        if normalized(candidate) not in existing: return candidate
        number += 1


def import_matchups(service, document, knowledge, catalog=None):
    catalog = validate_catalog(load_catalog() if catalog is None else catalog)
    updated = deepcopy(knowledge)
    result = {'added': 0, 'unchanged': 0, 'missing': [], 'changed': False, 'version': catalog['version']}
    for guide in catalog['guides']:
        key = f"matchup:{catalog['version']}:{guide['id']}"
        record = updated['records'].get(key)
        if record is None:
            topic_id = 'topic:' + key
            if topic_id not in updated['topics']:
                name = import_topic_name(guide['topic'], catalog['version'], updated['topics'])
                updated['topics'][topic_id] = {'id': topic_id, 'name': name, 'tag_ids': [], 'deck_id': None, 'note': ''}
            record = service.validate_record({'title': guide['title'], 'topic_id': topic_id,
                                              'steps': guide['steps']}, updated, None, trusted=True)
            research = {'catalog_version': catalog['version'], 'reviewed_at': catalog['reviewed_at'],
                        **{field: guide[field] for field in ('format', 'period', *RESEARCH_TEXT_FIELDS)},
                        'sources': [deepcopy(catalog['sources'][source]) for source in guide['source_ids']],
                        'edited': False, 'steps_edited': False}
            if 'walkthrough' in guide:
                research['walkthrough'] = validate_walkthrough(service, guide['walkthrough'], record['steps'], guide['source_ids'])
            if 'step_sources' in guide:
                citations = guide['step_sources']
                if not isinstance(citations, list) or len(citations) != len(record['steps']):
                    raise ValueError('断点来源数量与步骤不一致')
                research['step_sources'] = [source_ids(refs, guide['source_ids']) for refs in citations]
            record.update(id=key, research=research)
            updated['records'][key] = record
            result['added'] += 1
        else:
            result['unchanged'] += 1
        for code in sorted(service.record_codes(record)):
            if code not in service.store.catalog.cards:
                result['missing'].append({'code': code, 'guide_id': guide['id'], 'record_id': key})
    result['changed'] = updated != knowledge
    knowledge.clear(); knowledge.update(updated)
    return result


def save_research(record, value, previous):
    """Only personal prose is editable; catalog provenance remains the saved snapshot."""
    previous = previous or {}
    research = previous.get('research')
    if research is None:
        if 'research' in value: raise ValueError('研究来源仅能通过内置资料导入')
        return
    incoming = value.get('research', {})
    if not isinstance(incoming, dict): raise ValueError('研究资料格式无效')
    checked = deepcopy(research)
    for key in RESEARCH_TEXT_FIELDS:
        if key in incoming: checked[key] = text(incoming[key])
    changed = any(record[key] != previous.get(key) for key in ('title', 'topic_id', 'steps', 'note'))
    changed = changed or any(checked.get(key) != research.get(key) for key in RESEARCH_TEXT_FIELDS)
    checked['edited'] = bool(research.get('edited') or changed)
    checked['steps_edited'] = bool(research.get('steps_edited') or record['steps'] != previous.get('steps'))
    record['research'] = checked
