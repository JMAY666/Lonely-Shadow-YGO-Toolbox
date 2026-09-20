"""Read-only, dated opponent compositions. No personal deck or TAG writes."""
from copy import deepcopy
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
import json
import re

def load_catalog():
    return json.loads((Path(__file__).parent/'opponents.json').read_text('utf-8'))

def require(condition, message):
    if not condition: raise ValueError('对手卡组资料：' + message)

def identifier(value):
    require(isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._-]{0,159}',value), '编号无效')
    return value

def iso(value):
    try: date.fromisoformat(value)
    except (TypeError,ValueError): raise ValueError('对手卡组资料：日期无效') from None
    return value

def references(values, available):
    require(isinstance(values,list) and bool(values) and all(v in available for v in values),'来源或TAG引用缺失')
    return list(dict.fromkeys(values))

def card_rows(rows, maximum, minimum=0):
    require(isinstance(rows,list),'卡牌列表无效')
    result=[]; seen=set()
    for row in rows:
        code,quantity=row.get('code'),row.get('quantity')
        require(type(code) is int and 0<code<2**32 and code not in seen,'卡号重复或无效')
        require(type(quantity) is int and 1<=quantity<=3,'卡牌张数无效')
        seen.add(code);result.append(deepcopy(row))
    require(minimum<=sum(row['quantity'] for row in result)<=maximum,'卡组张数不完整')
    return result

def validate_catalog(raw):
    require(raw.get('version')==1,'资料版本不受支持')
    identifier(raw.get('revision'));iso(raw.get('checked_at'))
    value=deepcopy(raw)
    sources={}
    for source in value['sources']:
        key=identifier(source['id']);require(key not in sources,'来源编号重复')
        parsed=urlsplit(source['url'])
        require(parsed.scheme in ('https','http') and parsed.hostname and not parsed.username and not parsed.password,'来源必须为公开HTTP(S)链接')
        require(source['kind'] in ('statistics','decklist','card_text','route'),'来源类型无效')
        sources[key]=source
    tags={tag['id']:tag for tag in value['tags']}
    require(len(tags)==len(value['tags']),'TAG编号重复')
    periods={}; populations={}
    for period in value['periods']:
        key=identifier(period['id']);require(key not in periods,'统计期编号重复')
        require(period['format'] in ('OCG','Master Duel'),'环境无效')
        require(iso(period['start'])<=iso(period['end']),'统计期起止无效')
        total=period['sample_size']
        require(type(total) is int and total>0,'样本分母须为已核实的正整数')
        references(period['source_ids'],sources)
        counts={}
        for group in period['breakdown']:
            family=identifier(group['archetype']);count=group['count']
            require(family not in counts and type(count) is int and 0<count<=total,'牌型数量或分母无效')
            counts[family]=count
        require(sum(counts.values())<=total,'牌型样本总数超过分母')
        period['other_count']=total-sum(counts.values())
        populations[key]=counts;periods[key]=period
    deck_ids=set()
    for deck in value['decks']:
        key=identifier(deck['id']);require(key not in deck_ids,'构筑编号重复');deck_ids.add(key)
        require(deck['period_id'] in periods,'构筑缺少统计期')
        require(deck['archetype'] in populations[deck['period_id']],'构筑牌型未包含在来源统计中')
        references(deck['tag_ids'],tags);references(deck['source_ids'],sources)
        if deck.get('reported_date'):iso(deck['reported_date'])
        deck['main']=card_rows(deck['main'],60,40)
        deck['extra']=card_rows(deck['extra'],15)
        if deck['side'] is not None:deck['side']=card_rows(deck['side'],15)
        combined={}
        for row in deck['main']+deck['extra']+(deck['side'] or []):
            combined[row['code']]=combined.get(row['code'],0)+row['quantity']
        require(all(n<=3 for n in combined.values()),'主额外副卡组同一卡合计超过3张')
        available={row['code'] for row in deck['main']+deck['extra']}
        available_counts={row['code']:row['quantity'] for row in deck['main']+deck['extra']}
        hand={row['code']:row['quantity'] for row in deck['main']}
        routes=deck['routes'];require(isinstance(routes,list) and len(routes)>=2,'每份构筑至少需要两条展开路线')
        route_ids=set(); route_signatures=set()
        for route in routes:
            route_id=identifier(route['id']);require(route_id not in route_ids,'路线编号重复');route_ids.add(route_id)
            require(route.get('validation')=='card_text_reviewed','路线只能标明卡文条件推演，不能宣称引擎验证')
            references(route['source_ids'],sources)
            opening=route['opening'];required=card_rows(opening['cards'],6)
            other=opening.get('other_cards',0)
            require(type(other) is int and 0<=other<=5 and sum(c['quantity'] for c in required)+other<=6,'起手资源数量无效')
            require(all(row['code'] in hand and row['quantity']<=hand[row['code']] for row in required),'路线起手不在本构筑或数量不足')
            steps=route['steps'];require(isinstance(steps,list) and len(steps)>=2,'路线缺少操作步骤')
            step_ids=set()
            for step in steps:
                step_id=identifier(step['id']);require(step_id not in step_ids,'步骤编号重复');step_ids.add(step_id)
                require(isinstance(step['cards'],list) and bool(step['cards']) and all(type(code) is int and code in available for code in step['cards']),'路线引用了构筑外卡牌')
                require(isinstance(step.get('action'),str) and step['action'].strip() and isinstance(step.get('result'),str) and step['result'].strip(),'路线动作与结果不完整')
            endboard=card_rows(route['endboard'],30)
            require(bool(endboard) and all(c['code'] in available and c['quantity']<=available_counts[c['code']] for c in endboard),'终场引用或数量不属于当前构筑')
            signature=json.dumps([required,steps],ensure_ascii=False,sort_keys=True)
            require(signature not in route_signatures,'两条路线不能完全重复');route_signatures.add(signature)
    return value

def snapshot(store, catalog=None):
    value=validate_catalog(load_catalog() if catalog is None else catalog)
    # Order independently of JSON file layout; each share keeps its own denominator.
    periods=sorted(value['periods'],key=lambda p:(p['end'],p['start'],p['id']),reverse=True)
    period_by_id={p['id']:p for p in periods};order={p['id']:i for i,p in enumerate(periods)}
    decks=[];codes=set()
    for original in value['decks']:
        deck=deepcopy(original);period=period_by_id[deck['period_id']]
        count=next(g['count'] for g in period['breakdown'] if g['archetype']==deck['archetype'])
        deck.update(format=period['format'],sample_count=count,sample_size=period['sample_size'],share=count/period['sample_size'],
                    counts={zone:sum(c['quantity'] for c in deck[zone]) if deck[zone] is not None else None for zone in ('main','extra','side')})
        for zone in ('main','extra','side'):codes.update(c['code'] for c in deck[zone] or [])
        for route in deck['routes']:
            route['ref']=deck['id']+'/'+route['id']
            for step in route['steps']:step['ref']=route['ref']+'/'+step['id']
        decks.append(deck)
    decks.sort(key=lambda d:(order[d['period_id']],-d['share'],d['name'],d['id']))
    vocabulary=store.library.all_tags()
    tags=[{**tag,'name':vocabulary.get(tag['id'],tag)['name'],'aliases':vocabulary.get(tag['id'],tag).get('aliases',[])} for tag in value['tags']]
    cards={str(code):deepcopy(store.catalog.cards[code]) if code in store.catalog.cards else
           {'id':code,'name':value.get('card_names',{}).get(str(code),f'卡库缺失 · {code}'),'desc':'','type':0,'missing':True}
           for code in sorted(codes)}
    return {'version':value['version'],'revision':value['revision'],'checked_at':value['checked_at'],'readonly':True,
            'periods':periods,'decks':decks,'sources':value['sources'],'tags':tags,'cards':cards}
