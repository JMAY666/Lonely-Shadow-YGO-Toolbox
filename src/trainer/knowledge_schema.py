"""ygo-deck-knowledge 知识包模式：本地游戏王牌组知识的校验、依赖分析与三向合并。

仅使用 Python 3.11 标准库；不含文件系统访问、网络请求或可执行反序列化。
"""
import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime

FORMAT = 'ygo-deck-knowledge'
SCHEMA = 1
MAX_BYTES = 32 * 1024 * 1024
KINDS = ('source', 'build', 'route', 'step', 'fragment', 'branch', 'endboard', 'countermeasure')

_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$')
_VER_RE = re.compile(r'^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$')
_MAX_DEPTH = 64
_CHECK_TYPES = ('structure', 'human', 'engine', 'strategy')
_CHECK_STATUS = ('passed', 'failed', 'unknown')
_REPRESENTATIONS = ('tutorial', 'strategy', 'decisions')
_MISSING = object()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _iso_ok(value):
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except (ValueError, AttributeError):
        return False


def _check_json(value):
    stack = [(value, 0)]
    visited = 0
    while stack:
        visited += 1
        if visited > 500000 or len(stack) > 500000:
            raise ValueError('资料条目过多，请分成多个制作项目')
        node, depth = stack.pop()
        if depth > _MAX_DEPTH:
            raise ValueError(f'JSON 嵌套过深（超过 {_MAX_DEPTH} 层），已拒绝处理')
        if isinstance(node, dict):
            for key, sub in node.items():
                if not isinstance(key, str):
                    raise ValueError(f'对象键必须是字符串，得到 {type(key).__name__}')
                stack.append((sub, depth + 1))
        elif isinstance(node, list):
            stack.extend((sub, depth + 1) for sub in node)
        elif isinstance(node, float):
            if node != node or node in (float('inf'), float('-inf')):
                raise ValueError('数值必须有限（不允许 NaN / Infinity）')
        elif not isinstance(node, (str, int, bool)) and node is not None:
            raise ValueError(f'值必须是 JSON 类型，得到 {type(node).__name__}')


def _check_safe_keys(node):
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, val in cur.items():
                if not isinstance(key, str) or key.startswith('__') or key in ('prototype', 'constructor'):
                    raise ValueError(f'数据包含不安全的键名：{key!r}')
                stack.append(val)
        elif isinstance(cur, list):
            stack.extend(cur)


def _safe_url(url):
    match = re.match(r'^([A-Za-z][A-Za-z0-9+.-]*)://', url) if isinstance(url, str) else None
    if url not in ('', None) and (match is None or match.group(1) not in ('http', 'https')):
        raise ValueError(f'不安全的 URL（仅允许 http/https 或空字符串）：{url!r}')
    return url


def digest(value):
    _check_json(value)
    blob = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f'非法标识符 {value!r}：需匹配 ^[A-Za-z0-9][A-Za-z0-9._:-]{{0,119}}$')
    if '/' in value or '\\' in value or '..' in value:
        raise ValueError(f'非法标识符 {value!r}：不允许路径、斜杠或 .. 片段')
    return value


def new_document(name='新知识包', theme=''):
    if not isinstance(name, str) or not isinstance(theme, str):
        raise ValueError('name 与 theme 必须是字符串')
    return {
        'format': FORMAT,
        'schema': SCHEMA,
        'package': {
            'id': uuid.uuid4().hex,
            'name': name,
            'theme': theme,
            'version': '0.1.0',
            'environment': '',
            'app_min': '1.42.0',
        },
        'records': {},
        'checks': [],
    }


def _validate_data(rid, kind, data):
    where = f'记录 {rid}（{kind}）'

    def sfield(field):
        if field in data and not isinstance(data[field], str):
            raise ValueError(f'{where}：data.{field} 必须是字符串')

    def ilist(field):
        if field in data and (not isinstance(data[field], list) or not all(_is_int(x) and 0 < x <= 0xffffffff for x in data[field])):
            raise ValueError(f'{where}：data.{field} 必须是整数列表（卡牌代码）')

    def idfield(field):
        if field in data:
            if not isinstance(data[field], str):
                raise ValueError(f'{where}：data.{field} 必须是记录 ID 字符串')
            try:
                identifier(data[field])
            except ValueError as exc:
                raise ValueError(f'{where}：data.{field} 非法：{exc}') from exc

    if kind == 'source':
        if 'content' in data and not isinstance(data['content'], (str, dict, list)):
            raise ValueError(f'{where}：data.content 必须是字符串或对象')
        if 'url' in data:
            if not isinstance(data['url'], str):
                raise ValueError(f'{where}：data.url 必须是字符串')
            _safe_url(data['url'])
        sfield('note')
    elif kind == 'build':
        ilist('main')
        ilist('extra')
        if 'side' in data and data['side'] is not None:
            ilist('side')
        sfield('conditions')
        sfield('notes')
    elif kind in ('route', 'fragment'):
        if 'steps' in data:
            steps = data['steps']
            if not isinstance(steps, list):
                raise ValueError(f'{where}：data.steps 必须是步骤 ID 列表')
            for sid in steps:
                if not isinstance(sid, str):
                    raise ValueError(f'{where}：data.steps 元素必须是字符串 ID')
                try:
                    identifier(sid)
                except ValueError as exc:
                    raise ValueError(f'{where}：data.steps 元素非法：{exc}') from exc
        if 'opening' in data:
            opening = data['opening']
            if not isinstance(opening, dict):
                raise ValueError(f'{where}：data.opening 必须是对象（既有条件格式或 cards/notes）')
            if 'cards' in opening and (not isinstance(opening['cards'], list)
                                       or not all(_is_int(x) and 0 < x <= 0xffffffff for x in opening['cards'])):
                raise ValueError(f'{where}：data.opening.cards 必须是整数列表')
            if 'notes' in opening and not isinstance(opening['notes'], str):
                raise ValueError(f'{where}：data.opening.notes 必须是字符串')
        sfield('conditions')
        sfield('notes')
        if 'representation' in data and data['representation'] not in _REPRESENTATIONS:
            raise ValueError(f'{where}：data.representation 必须是 {"、".join(_REPRESENTATIONS)} 之一')
        if 'plan' in data and not isinstance(data['plan'], dict):
            raise ValueError(f'{where}：data.plan 必须是可移植的对象（仅在显式导入时存在）')
    elif kind == 'step':
        ilist('cards')
        for field in ('action', 'costs', 'targets', 'limits', 'result', 'conditions'):
            sfield(field)
    elif kind == 'branch':
        idfield('anchor')
        idfield('route')
        for field in ('timing', 'interference', 'resources', 'conditions', 'notes'):
            sfield(field)
    elif kind == 'endboard':
        ilist('cards')
        if 'effects' in data and (not isinstance(data['effects'], list)
                                  or not all(isinstance(e, dict) for e in data['effects'])):
            raise ValueError(f'{where}：data.effects 必须是对象列表（可描述共享代价/次数限制）')
        for field in ('resources', 'constraints', 'notes'):
            sfield(field)
    else:  # countermeasure
        for field in ('opponent', 'situation', 'responses', 'exceptions', 'notes'):
            sfield(field)


def _validate_record(rid, rec):
    if not isinstance(rec, dict):
        raise ValueError(f'记录 {rid} 必须是对象')
    if rec.get('id') != rid:
        raise ValueError(f'记录键 {rid!r} 与其 id 字段 {rec.get("id")!r} 不一致')
    if rec.get('kind') not in KINDS:
        raise ValueError(f'记录 {rid}：未知类型 {rec.get("kind")!r}（允许：{"、".join(KINDS)}）')
    revision = rec.get('revision')
    if not _is_int(revision) or revision < 1:
        raise ValueError(f'记录 {rid}：revision 必须为正整数（布尔值不算），得到 {revision!r}')
    if not isinstance(rec.get('title'), str) or not rec['title'].strip() or len(rec['title']) > 500:
        raise ValueError(f'记录 {rid}：title 必须是字符串')
    if 'editor_note' in rec and not isinstance(rec['editor_note'], str):
        raise ValueError(f'记录 {rid}：整理备注必须是字符串')
    tags = rec.setdefault('tags', [])
    if not isinstance(tags, list):
        raise ValueError(f'记录 {rid}：tags 必须是数组')
    for tag in tags:
        if not isinstance(tag, str) or not _ID_RE.fullmatch(tag) or '..' in tag:
            raise ValueError(f'记录 {rid}：tag 必须是稳定的标签 ID：{tag!r}')
    refs = rec.setdefault('refs', [])
    if not isinstance(refs, list):
        raise ValueError(f'记录 {rid}：refs 必须是数组')
    for ref in refs:
        if (not isinstance(ref, dict) or not isinstance(ref.get('id'), str)
                or not isinstance(ref.get('relation'), str)):
            raise ValueError(f'记录 {rid}：refs 元素必须是含 id 与 relation 字符串的对象')
        try:
            identifier(ref['id'])
        except ValueError as exc:
            raise ValueError(f'记录 {rid}：引用 id 非法：{exc}') from exc
    if 'deleted' in rec and not isinstance(rec['deleted'], bool):
        raise ValueError(f'记录 {rid}：deleted 必须是布尔值')
    data = rec.setdefault('data', {})
    if not isinstance(data, dict):
        raise ValueError(f'记录 {rid}：data 必须是对象')
    _check_safe_keys(data)
    _check_json(data)
    _validate_data(rid, rec['kind'], data)


def _validate_check(chk):
    if not isinstance(chk, dict):
        raise ValueError('check 必须是对象')
    try:
        cid = identifier(chk.get('id'))
        identifier(chk.get('target'))
    except ValueError as exc:
        raise ValueError(f'check 非法：{exc}') from exc
    if chk.get('type') not in _CHECK_TYPES:
        raise ValueError(f'check {cid}：type 必须是 {"、".join(_CHECK_TYPES)} 之一')
    if chk.get('status') not in _CHECK_STATUS:
        raise ValueError(f'check {cid}：status 必须是 {"、".join(_CHECK_STATUS)} 之一')
    chk.setdefault('note', '')
    if not isinstance(chk['note'], str):
        raise ValueError(f'check {cid}：note 必须是字符串')
    if not isinstance(chk.get('at'), str) or not _iso_ok(chk['at']):
        raise ValueError(f'check {cid}：at 必须是 ISO 日期时间字符串')
    inputs = chk.setdefault('inputs', {})
    if not isinstance(inputs, dict):
        raise ValueError(f'check {cid}：inputs 必须是对象')
    for key, val in inputs.items():
        if not isinstance(key, str) or not isinstance(val, str):
            raise ValueError(f'check {cid}：inputs 必须是 {{记录ID: 语义哈希}} 的字符串映射')
    if 'environment' in chk and not isinstance(chk['environment'], dict):
        raise ValueError(f'check {cid}：environment 必须是对象')


def validate_document(raw, strict=False):
    # Inspect before deepcopy/serialization so hostile nesting is rejected predictably.
    _check_json(raw)
    _check_safe_keys(raw)
    doc = deepcopy(raw)
    if not isinstance(doc, dict):
        raise ValueError('文档必须是 JSON 对象')
    if doc.get('format') != FORMAT:
        raise ValueError(f'format 必须是 {FORMAT!r}')
    schema = doc.get('schema')
    if not _is_int(schema) or schema != SCHEMA:
        raise ValueError(f'schema 必须是整数 {SCHEMA}')
    pkg = doc.get('package')
    if not isinstance(pkg, dict):
        raise ValueError('package 必须是对象')
    try:
        identifier(pkg.get('id'))
    except ValueError as exc:
        raise ValueError(f'package.id 非法：{exc}') from exc
    for field in ('name', 'theme', 'environment'):
        pkg.setdefault(field, '')
    pkg.setdefault('app_min', '1.42.0')
    for field in ('name', 'theme', 'environment', 'app_min'):
        if not isinstance(pkg[field], str):
            raise ValueError(f'package.{field} 必须是字符串')
    if not isinstance(pkg.get('version'), str) or not _VER_RE.fullmatch(pkg['version']):
        raise ValueError(f'package.version 必须是三段数字语义化版本（可带 -后缀）：{pkg.get("version")!r}')
    if len(pkg['version']) > 64 or len(pkg['app_min']) > 64 or not _VER_RE.fullmatch(pkg['app_min']):
        raise ValueError('发布版本与最低应用版本必须是有效版本号，最长 64 字符')
    if not pkg['name'].strip() or len(pkg['name']) > 200 or len(pkg['theme']) > 200:
        raise ValueError('知识包名称不能为空，名称与主题最多 200 字')
    records = doc.setdefault('records', {})
    if not isinstance(records, dict):
        raise ValueError('records 必须是对象')
    for rid, rec in records.items():
        try:
            identifier(rid)
        except ValueError as exc:
            raise ValueError(f'records 键非法：{exc}') from exc
        _validate_record(rid, rec)
    checks = doc.setdefault('checks', [])
    if not isinstance(checks, list):
        raise ValueError('checks 必须是数组')
    check_ids = set()
    for chk in checks:
        _validate_check(chk)
        if chk['id'] in check_ids: raise ValueError('验证记录标识重复')
        check_ids.add(chk['id'])
    _check_json(doc)
    size = len(json.dumps(doc, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    if size > MAX_BYTES:
        raise ValueError(f'文档序列化后 {size} 字节，超过上限 {MAX_BYTES} 字节')
    if strict:
        blockers = [issue for issue in inspect_document(doc)['issues'] if issue['blocking']]
        if blockers:
            detail = '；'.join(f"[{b['record']}/{b['code']}] {b['message']}" for b in blockers)
            raise ValueError(f'严格校验未通过（阻断性问题）：{detail}')
    return doc


def dependencies(record):
    deps = set()
    for ref in record.get('refs') or []:
        if isinstance(ref, dict) and isinstance(ref.get('id'), str):
            deps.add(ref['id'])
    data = record.get('data') or {}
    kind = record.get('kind')
    if isinstance(data, dict):
        if kind in ('route', 'fragment') and isinstance(data.get('steps'), list):
            deps.update(sid for sid in data['steps'] if isinstance(sid, str))
        if kind == 'branch':
            for field in ('anchor', 'route'):
                if isinstance(data.get(field), str):
                    deps.add(data[field])
    return sorted(deps)


def semantic(record):
    data = record.get('data') or {}
    # Existing route notes contain real restrictions. Only the explicitly editorial
    # field may be ignored; unrecognized future fields conservatively invalidate.
    body = data
    refs = [{'id': ref.get('id'), 'relation': ref.get('relation', '')}
            for ref in record.get('refs') or [] if isinstance(ref, dict)]
    refs.sort(key=lambda ref: (str(ref['id']), str(ref['relation'])))
    value = {key: item for key, item in record.items() if key not in ('id', 'title', 'tags', 'revision', 'editor_note')}
    value.update(kind=record.get('kind'), deleted=bool(record.get('deleted', False)), data=body, refs=refs)
    return digest(value)


def inputs_for(document, target):
    records = document.get('records') or {}
    result, seen, queue = {}, set(), [target]
    while queue:
        rid = queue.pop()
        if rid in seen:
            continue
        seen.add(rid)
        rec = records.get(rid)
        if rec is None:
            result[rid] = 'missing'
        else:
            result[rid] = semantic(rec)
            queue.extend(dep for dep in dependencies(rec) if dep not in seen)
    package = document.get('package', {})
    context = {key: value for key, value in package.items() if key not in ('id', 'name', 'theme', 'version', 'app_min', 'editor_note')}
    # '$' cannot begin a record ID, so this external dependency cannot collide with an entity.
    result['$environment'] = digest(context)
    return {rid: result[rid] for rid in sorted(result)}


def check_state(document, check):
    records = document.get('records') or {}
    if not isinstance(check.get('target'), str) or check['target'] not in records: return 'stale'
    current = inputs_for(document, check.get('target'))
    saved = check.get('inputs')
    if not isinstance(saved, dict) or saved != current:
        return 'stale'
    for rid in current:
        if rid == '$environment': continue
        rec = records.get(rid)
        if rec is None or rec.get('deleted', False):
            return 'stale'
    return check.get('status')


def _cycle_nodes(records):
    remaining = set(records)
    deps = {rid: {d for d in dependencies(rec) if d in records} for rid, rec in records.items()}
    changed = True
    while changed:
        changed = False
        for rid in [r for r in remaining if not (deps[r] & remaining)]:
            remaining.discard(rid)
            changed = True
    return remaining


def inspect_document(document, cards=None):
    records = document.get('records') or {}
    issues = []

    def issue(rid, code, message, blocking):
        issues.append({'record': rid, 'code': code, 'message': message, 'blocking': blocking})

    counts = {kind: 0 for kind in KINDS}
    for rid, rec in records.items():
        if rec.get('deleted'): continue
        kind = rec.get('kind')
        if kind in counts:
            counts[kind] += 1
        for ref in rec.get('refs') or []:
            if not isinstance(ref, dict):
                continue
            ref_id = ref.get('id')
            if ref_id not in records:
                issue(rid, 'ref-unresolved', f'引用的记录 {ref_id!r} 不存在于本文档', True)
            elif records[ref_id].get('deleted', False):
                issue(rid, 'ref-tombstone', f'引用的记录 {ref_id!r} 已移除，请补充有效来源或调整依赖；历史仍保留', True)
        data = rec.get('data') or {}
        if not isinstance(data, dict):
            continue
        if kind in ('route', 'fragment'):
            steps = data.get('steps')
            if not isinstance(steps, list) or not steps:
                issue(rid, 'steps-missing', '路线/片段缺少 steps 步骤列表或为空', True)
            else:
                for sid in steps:
                    if sid not in records:
                        issue(rid, 'step-unresolved', f'步骤 {sid!r} 不存在于本文档', True)
                    elif records[sid].get('kind') != 'step':
                        issue(rid, 'step-kind', f'步骤 {sid!r} 的类型应为 step，实际为 {records[sid].get("kind")!r}', True)
                    elif records[sid].get('deleted', False):
                        issue(rid, 'step-tombstone', f'引用的步骤 {sid!r} 已移除', True)
        if kind == 'branch':
            anchor, route = data.get('anchor'), data.get('route')
            if not anchor: issue(rid, 'anchor-missing', '妥协缺少具体步骤锚点，请人工确认原始时点', True)
            if not route: issue(rid, 'route-missing', '妥协缺少所属路线', True)
            if isinstance(anchor, str):
                if anchor not in records:
                    issue(rid, 'anchor-unresolved', f'锚点步骤 {anchor!r} 不存在', True)
                elif records[anchor].get('kind') != 'step':
                    issue(rid, 'anchor-kind', f'锚点 {anchor!r} 应为 step 类型', True)
                elif records[anchor].get('deleted', False):
                    issue(rid, 'anchor-tombstone', f'锚点 {anchor!r} 已移除', True)
            if isinstance(route, str):
                if route not in records:
                    issue(rid, 'route-unresolved', f'所属路线 {route!r} 不存在', True)
                elif records[route].get('kind') != 'route':
                    issue(rid, 'route-kind', f'{route!r} 应为 route 类型', True)
                elif records[route].get('deleted', False):
                    issue(rid, 'route-tombstone', f'所属路线 {route!r} 已移除', True)
            if anchor and route in records and records[route].get('kind') == 'route' and anchor not in records[route].get('data', {}).get('steps', []):
                issue(rid, 'anchor-outside-route', '妥协锚点不属于所选路线的步骤', True)
        if kind == 'build':
            if not data.get('main') or not isinstance(data.get('extra'), list) or 'side' not in data:
                issue(rid, 'build-incomplete', '构筑需要主卡、额外与副卡信息；未披露副卡请选择未知', True)
            elif not 40 <= len(data['main']) <= 60 or len(data['extra']) > 15 or len(data.get('side') or []) > 15:
                issue(rid, 'build-count', '构筑张数不符合通常范围，请按声明的规则环境核对；尚未验证禁限合法性', False)
        if kind == 'source' and ('content' not in data or data['content'] in (None, '')):
            issue(rid, 'source-content-missing', 'source 记录缺少原始内容 content（仅警告，草稿允许）', False)
        if kind == 'step':
            for field in ('action', 'result'):
                value = data.get(field)
                if not isinstance(value, str) or not value.strip():
                    issue(rid, f'step-{field}-empty', f'步骤缺少必要的 {field} 描述（草稿允许，发布前应补全）', False)
    for rid in sorted(_cycle_nodes({key: rec for key, rec in records.items() if not rec.get('deleted')})):
        issue(rid, 'cycle', '该条目存在循环依赖或依赖了循环内容，需先修正引用', True)
    if cards is not None:
        known = set(cards.keys()) if isinstance(cards, dict) else set()
        for rid, rec in records.items():
            if rec.get('deleted'): continue
            data = rec.get('data') or {}
            if not isinstance(data, dict):
                continue
            found = []
            if rec.get('kind') == 'build':
                found += data.get('main') or []
                found += data.get('extra') or []
                if isinstance(data.get('side'), list):
                    found += data['side']
            elif rec.get('kind') in ('step', 'endboard'):
                found += data.get('cards') or []
            if isinstance(data.get('opening'), dict) and isinstance(data['opening'].get('cards'), list):
                found += data['opening']['cards']
            missing = sorted({c for c in found if _is_int(c) and c not in known})
            if missing:
                issue(rid, 'card-missing', f'以下卡牌代码不在目录中：{missing}（不影响浏览，非阻断）', False)
    enriched = []
    for chk in document.get('checks') or []:
        if not isinstance(chk, dict):
            continue
        item = dict(chk)
        item['state'] = check_state(document, chk)
        enriched.append(item)
    return {
        'issues': issues,
        'counts': counts,
        'checks': enriched,
        'capabilities': {'browse': True, 'calculate': False, 'execute': False},
    }


def impact(before, after):
    b_recs = before.get('records') or {}
    a_recs = after.get('records') or {}
    ids = set(b_recs) | set(a_recs)
    changed, semantic_changed = [], []
    for rid in sorted(ids):
        b, a = b_recs.get(rid), a_recs.get(rid)
        if b != a:
            changed.append(rid)
        if (semantic(b) if b is not None else None) != (semantic(a) if a is not None else None):
            semantic_changed.append(rid)
    affected = set(semantic_changed)
    environment_changed = inputs_for(before, '')['$environment'] != inputs_for(after, '')['$environment']
    if environment_changed: affected.update(ids)
    for recs in (b_recs, a_recs):
        reverse = {}
        for rid, rec in recs.items():
            for dep in dependencies(rec):
                reverse.setdefault(dep, set()).add(rid)
        frontier = list(affected)
        while frontier:
            for dependent in reverse.get(frontier.pop(), ()):
                if dependent not in affected:
                    affected.add(dependent)
                    frontier.append(dependent)
    reused = [rid for rid in sorted(ids)
              if rid in b_recs and rid in a_recs
              and semantic(b_recs[rid]) == semantic(a_recs[rid])
              and rid not in affected]
    checks_stale = [chk.get('id') for chk in (after.get('checks') or [])
                    if isinstance(chk, dict) and check_state(after, chk) == 'stale']
    return {
        'changed': changed,
        'semantic_changed': semantic_changed,
        'affected': sorted(affected),
        'reused': reused,
        'checks_stale': checks_stale,
        'environment_changed': environment_changed,
    }


def merge_value(base, local, incoming, path=''):
    if local == incoming:
        value = local
    elif local == base:
        value = incoming
    elif incoming == base:
        value = local
    elif isinstance(base, dict) and isinstance(local, dict) and isinstance(incoming, dict):
        merged, conflicts = {}, []
        for key in sorted(set(base) | set(local) | set(incoming)):
            v, c = merge_value(base.get(key, _MISSING), local.get(key, _MISSING),
                               incoming.get(key, _MISSING),
                               f'{path}.{key}' if path else key)
            if v is not _MISSING:
                merged[key] = v
            conflicts.extend(c)
        return merged, conflicts
    else:
        return (deepcopy(local) if local is not _MISSING else _MISSING), [path]
    return (deepcopy(value) if value is not _MISSING else _MISSING), []
