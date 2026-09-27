"""Read-only newest-series queue; release eligibility is separate from effect review."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from card_annotations import digest
from card_release_dates import ReleaseDates, valid_date


def eligibility(code, card, releases, as_of):
    if card['type'] & 0x4000:
        return 'token'
    source = card.get('source', '').lower().replace('\\', '/')
    if 'superpre' in source or '/patches/' in source:
        return 'preview_source'
    key = str(code)
    if key not in releases.document['cards']:
        key = str(releases.document.get('aliases', {}).get(key, ''))
    ocg, tcg = releases.document['cards'].get(key, ['', ''])
    if not ocg:
        return 'tcg_only_or_ocg_date_unknown' if tcg else 'release_date_unknown'
    if ocg > as_of:
        return 'ocg_not_released'
    return None


def build_queue(catalog, series, formal, releases, as_of):
    valid_date(as_of)
    excluded = {}
    covered = set()
    for code, card in catalog.cards.items():
        reason = eligibility(code, card, releases, as_of)
        if reason:
            excluded[code] = reason
        entry = formal.get(str(code), {})
        if (entry.get('text_digest') == digest(card['desc'])
                and entry.get('review', {}).get('status') == 'reviewed'
                and entry.get('review', {}).get('origin') == 'manual'):
            covered.add(code)
    rows = []
    for key, members in series.members.items():
        if key == 'unassigned':
            continue
        release = series.releases.get(key, {})
        allowed = members - excluded.keys()
        rows.append({'id': key, 'name': series.definitions[key]['name'],
                     'first_release': release.get('date', ''),
                     'date_coverage': [release.get('known_cards', 0), len(members)],
                     'eligible_codes': sorted(allowed),
                     'remaining_codes': sorted(allowed - covered),
                     'excluded': [{'code': c, 'reason': excluded[c]} for c in sorted(members & excluded.keys())]})
    # Missing dates never outrank known releases; same-date series use stable IDs.
    rows.sort(key=lambda r: r['id'])
    rows.sort(key=lambda r: r['first_release'], reverse=True)
    return {'as_of': as_of, 'release_snapshot': releases.document['retrieved_on'],
            'scope': 'OCG released candidates only; dates are screening evidence, not official rule review.',
            'series': rows,
            'excluded_counts': {reason: sum(v == reason for v in excluded.values()) for reason in sorted(set(excluded.values()))},
            'unassigned_remaining': sorted(series.members.get('unassigned', set()) - excluded.keys() - covered)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--as-of', default=date.today().isoformat())
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from app import Catalog
    from card_series import CardSeries
    from plan_tags import builtin_tags
    catalog = Catalog(args.runtime)
    series = CardSeries(catalog, builtin_tags(args.runtime))
    formal = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))['cards']
    result = build_queue(catalog, series, formal, ReleaseDates(), args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError('Use a new snapshot path; existing queue evidence is preserved')
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'series': len(result['series']), 'excluded_counts': result['excluded_counts'],
                      'next': next((r for r in result['series'] if r['remaining_codes'] and r['first_release']), None)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
