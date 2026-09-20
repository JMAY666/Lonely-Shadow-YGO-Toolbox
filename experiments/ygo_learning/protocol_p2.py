"""Frozen P2 pilot-family partition and machine-evaluable structural goals.

This module only constructs the partition.  It never runs a policy, teacher,
native engine, or holdout trajectory.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / ".local/ygo-agent-pilot"
P1 = ROOT / ".local/ygo-learning/p0b-p1"
SCHEMA = "ygo_learning_protocol_p2_v1"
SAMPLING_SEED = 20260920
ENGINE_SEED = 42
SCENARIOS = (
    "no_extra_response",
    "one_ash",
    "resource_tight",
    "actual_draw",
    "preserve_resources",
)
SPLIT_COUNTS = {"train": 24, "validation": 8, "holdout": 8}

# Frozen public IDs from the pinned TenyiSword asset.  They classify starting
# hands only; no teacher outcome is consulted.
RESOURCE_ACCESS_IDS = frozenset({20001443, 55273560, 56495147, 93490856})
ACTUAL_DRAW_REVEAL_IDS = frozenset({
    14821890, 20001443, 23431858, 56465981, 56495147,
    87052196, 93490856, 93850690, 98159737,
})
PRESERVE_RESOURCE_IDS = frozenset({
    10045474, 14558127, 23434538, 24224830, 27204311, 97268402,
})
ALLOWED_SYNCHRO_IDS = frozenset({
    5041348, 9464441, 42632209, 43202238, 47710198,
    60465049, 69248256, 83755611, 84815190, 96633955,
})
GOAL_VIEW_SCHEMA = "p2_goal_card_view_v1"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _normalized_hand(hand):
    if not isinstance(hand, (list, tuple)) or not hand or any(not _is_int(code) or code <= 0 for code in hand):
        raise ValueError("Each exclusion must be a non-empty normalized hand of positive card IDs")
    return tuple(sorted(hand))


def _normalize_deck(deck):
    if not isinstance(deck, dict) or set(deck) != {"main", "extra", "side"}:
        raise ValueError("Deck must contain exactly main, extra and side")
    result = {}
    for zone in ("main", "extra", "side"):
        cards = deck[zone]
        if not isinstance(cards, (list, tuple)) or any(not _is_int(code) or code <= 0 for code in cards):
            raise ValueError(f"Deck {zone} must contain positive integer card IDs")
        result[zone] = list(cards)
    if len(result["main"]) != 40 or len(result["extra"]) != 15 or result["side"]:
        raise ValueError("P2 requires the frozen 40-card main, 15-card extra and empty side deck")
    return result


def _all_hand_multisets(main):
    # combinations() accounts for physical duplicate copies; the set collapses
    # permutations and identical-copy choices into one family key.
    return sorted(set(itertools.combinations(sorted(main), 5)))


def _qualifies(hand, scenario):
    if scenario == "resource_tight":
        return sum(code in RESOURCE_ACCESS_IDS for code in hand) == 1
    if scenario == "actual_draw":
        remaining = Counter(hand)
        if remaining[20001443] == 0:
            return False
        remaining[20001443] -= 1
        return any(count > 0 and code in ACTUAL_DRAW_REVEAL_IDS for code, count in remaining.items())
    if scenario == "preserve_resources":
        return sum(code in PRESERVE_RESOURCE_IDS for code in hand) >= 2
    return True


def _goal(extra, scenario):
    # These catalog-verified original identities are also required to be in the
    # frozen public extra deck. Evaluation does not infer current card type.
    synchros = ALLOWED_SYNCHRO_IDS.intersection(extra)
    return {
        "kind": "first_turn_synchro_resources_v1",
        "allowed_synchro_codes": sorted(synchros),
        "minimum_face_up_enabled_synchro": 1,
        "minimum_retained_hand_cards": 2 if scenario == "preserve_resources" else 1,
        "minimum_actual_draw_count": 1 if scenario == "actual_draw" else 0,
    }


def _rank(seed, scenario, hand):
    return hashlib.sha256(f"{seed}:{scenario}:".encode("ascii") + _canonical(hand)).digest()


def build_protocol(deck, exclusions, provenance, *, sampling_seed=SAMPLING_SEED, code_hash):
    """Build a deterministic P2 partition without reading the local runtime."""
    frozen_deck = _normalize_deck(deck)
    if not _is_int(sampling_seed) or sampling_seed < 0:
        raise ValueError("sampling_seed must be a non-negative integer")
    if not isinstance(code_hash, str) or len(code_hash) != 64:
        raise ValueError("code_hash must be a SHA-256 hex digest")
    if not isinstance(provenance, list):
        raise ValueError("provenance must be a list")
    for source in provenance:
        if not isinstance(source, dict) or not isinstance(source.get("path"), str) or not isinstance(source.get("kind"), str):
            raise ValueError("Each provenance row needs path and kind")
        digest = source.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Each provenance row needs a SHA-256 digest")

    excluded = {_normalized_hand(hand) for hand in exclusions}
    available = [hand for hand in _all_hand_multisets(frozen_deck["main"]) if hand not in excluded]
    selected = {}
    used = set()
    # Narrow rules claim candidates before the two unrestricted response strata.
    selection_order = ("actual_draw", "resource_tight", "preserve_resources", "no_extra_response", "one_ash")
    for scenario in selection_order:
        candidates = [hand for hand in available if hand not in used and _qualifies(hand, scenario)]
        candidates.sort(key=lambda hand: (_rank(sampling_seed, scenario, hand), hand))
        if len(candidates) < 40:
            raise ValueError(f"Scenario {scenario} does not have 40 qualified unique hands after exclusions")
        selected[scenario] = candidates[:40]
        used.update(selected[scenario])

    families = []
    calibration_ids = []
    for scenario in SCENARIOS:
        goal = _goal(frozen_deck["extra"], scenario)
        for index, hand in enumerate(selected[scenario], 1):
            if index <= 24:
                split = "train"
            elif index <= 32:
                split = "validation"
            else:
                split = "holdout"
            family = {
                "id": f"p2-{scenario}-{index:02d}",
                "hand": list(hand),
                "scenario": scenario,
                "split": split,
                "goal": deepcopy(goal),
                "engine_seed": ENGINE_SEED,
            }
            families.append(family)
            if index <= 4:
                calibration_ids.append(family["id"])

    protocol = {
        "schema": SCHEMA,
        "sampling_seed": sampling_seed,
        "code_sha256": code_hash,
        "deck": frozen_deck,
        "families": families,
        "calibration_ids": calibration_ids,
        "provenance": deepcopy(provenance),
        "limits": {
            "family_count": 200,
            "families_per_scenario": 40,
            "split_per_scenario": deepcopy(SPLIT_COUNTS),
            "calibration_train_per_scenario": 4,
            "engine_seed": ENGINE_SEED,
            "draw_order": "uniform_existing_draw_opening_once_then_exact_retry_reuse",
            "draw_order_policy_visibility": "hidden_digest_only",
            "outcome_exclusions": 0,
        },
    }
    protocol["fingerprint"] = _digest(protocol)
    _validate_protocol(protocol)
    return protocol


def _validate_goal(goal):
    if not isinstance(goal, dict) or goal.get("kind") != "first_turn_synchro_resources_v1":
        raise ValueError("Unknown P2 goal")
    codes = goal.get("allowed_synchro_codes")
    if not isinstance(codes, list) or not codes or codes != sorted(set(codes)) or any(not _is_int(c) for c in codes):
        raise ValueError("Malformed allowed synchro IDs")
    for key in ("minimum_face_up_enabled_synchro", "minimum_retained_hand_cards", "minimum_actual_draw_count"):
        if not _is_int(goal.get(key)) or goal[key] < 0:
            raise ValueError(f"Malformed goal threshold: {key}")


def _validate_protocol(protocol):
    if not isinstance(protocol, dict) or protocol.get("schema") != SCHEMA:
        raise ValueError("Unknown P2 protocol schema")
    fingerprint = protocol.get("fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("Missing protocol fingerprint")
    content = {key: value for key, value in protocol.items() if key != "fingerprint"}
    if _digest(content) != fingerprint:
        raise ValueError("Protocol fingerprint differs from frozen content")
    frozen_deck = _normalize_deck(protocol.get("deck"))
    available = Counter(frozen_deck["main"])
    if not isinstance(protocol.get("code_sha256"), str) or len(protocol["code_sha256"]) != 64:
        raise ValueError("Malformed protocol code identity")
    families = protocol.get("families")
    if not isinstance(families, list) or len(families) != 200:
        raise ValueError("P2 protocol must contain 200 families")
    identifiers = set()
    hands = set()
    counts = Counter()
    for family in families:
        if not isinstance(family, dict) or set(family) != {"id", "hand", "scenario", "split", "goal", "engine_seed"}:
            raise ValueError("Malformed P2 family")
        if not isinstance(family["id"], str) or family["id"] in identifiers:
            raise ValueError("Duplicate or malformed family ID")
        identifiers.add(family["id"])
        hand = _normalized_hand(family["hand"])
        if len(hand) != 5 or list(hand) != family["hand"] or hand in hands:
            raise ValueError("Family hands must be unique normalized five-card multisets")
        if any(count > available[code] for code, count in Counter(hand).items()):
            raise ValueError("Family hand is impossible for the frozen deck")
        hands.add(hand)
        if family["scenario"] not in SCENARIOS or family["split"] not in SPLIT_COUNTS:
            raise ValueError("Unknown family scenario or split")
        if not _qualifies(hand, family["scenario"]):
            raise ValueError("Family does not satisfy its structural stratum")
        if family["engine_seed"] != ENGINE_SEED:
            raise ValueError("P2 native engine seed must remain 42")
        _validate_goal(family["goal"])
        if family["goal"] != _goal(protocol["deck"]["extra"], family["scenario"]):
            raise ValueError("Family goal differs from its frozen scenario template")
        counts[(family["scenario"], family["split"])] += 1
    expected = {(scenario, split): count for scenario in SCENARIOS for split, count in SPLIT_COUNTS.items()}
    if counts != Counter(expected):
        raise ValueError("P2 scenario split counts differ")
    calibration = protocol.get("calibration_ids")
    if not isinstance(calibration, list) or len(calibration) != 20 or len(set(calibration)) != 20:
        raise ValueError("P2 requires 20 unique calibration IDs")
    by_id = {family["id"]: family for family in families}
    if any(identifier not in by_id or by_id[identifier]["split"] != "train" for identifier in calibration):
        raise ValueError("Calibration IDs must identify training families")
    if Counter(by_id[identifier]["scenario"] for identifier in calibration) != Counter({scenario: 4 for scenario in SCENARIOS}):
        raise ValueError("Calibration IDs must contain four families per scenario")
    limits = protocol.get("limits")
    if not isinstance(limits, dict) or limits.get("engine_seed") != ENGINE_SEED or limits.get("outcome_exclusions") != 0:
        raise ValueError("Malformed P2 limits")
    provenance = protocol.get("provenance")
    if not isinstance(provenance, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("path"), str)
        or not isinstance(row.get("kind"), str) or not isinstance(row.get("sha256"), str)
        or len(row["sha256"]) != 64 for row in provenance
    ):
        raise ValueError("Malformed P2 provenance")


def load_protocol(path: Path):
    """Load a freeze only when its content, code and source files still match."""
    try:
        protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("P2 protocol is missing or malformed") from error
    _validate_protocol(protocol)
    if protocol["code_sha256"] != _sha256(Path(__file__)):
        raise ValueError("P2 protocol code SHA differs from the current protocol builder")
    checked = {}
    for source in protocol["provenance"]:
        source_path = ROOT.joinpath(*source["path"].replace("\\", "/").split("/")).resolve()
        if not source_path.is_relative_to(ROOT.resolve()) or not source_path.is_file():
            raise ValueError("P2 protocol provenance source is missing or outside the repository")
        actual = checked.get(source_path)
        if actual is None:
            actual = checked[source_path] = _sha256(source_path)
        if actual != source["sha256"]:
            raise ValueError(f"P2 protocol provenance hash differs: {source['path']}")
    return protocol


def calibration_families(protocol):
    """Return the 20 preregistered training families in frozen order."""
    _validate_protocol(protocol)
    by_id = {family["id"]: family for family in protocol["families"]}
    return [deepcopy(by_id[identifier]) for identifier in protocol["calibration_ids"]]


def evaluate_goal(observation, goal, *, completed: bool, actual_draw_count: int):
    """Evaluate a P2 structural goal against a player-visible v2 observation.

    Malformed or incomplete inputs return a closed failure rather than raising or
    inferring hidden/dynamic facts.
    """
    empty = {
        "completed": int(completed is True),
        "face_up_enabled_synchro": 0,
        "retained_hand_cards": 0,
        "actual_draw_count": actual_draw_count if _is_int(actual_draw_count) and actual_draw_count >= 0 else 0,
    }
    try:
        _validate_goal(goal)
        if completed is not True or not _is_int(actual_draw_count) or actual_draw_count < 0:
            return {"vector": empty, "success": False}
        if not isinstance(observation, dict) or observation.get("schema") != GOAL_VIEW_SCHEMA or not isinstance(observation.get("cards"), list):
            raise ValueError("incomplete")
        allowed = set(goal["allowed_synchro_codes"])
        synchros = retained = 0
        for card in observation["cards"]:
            if not isinstance(card, dict) or not _is_int(card.get("controller")) or not _is_int(card.get("location")):
                raise ValueError("incomplete")
            controller, location = card["controller"], card["location"]
            if controller == 0 and location == 2:
                if card.get("identity_known") is not True or not _is_int(card.get("code")):
                    raise ValueError("incomplete")
                retained += 1
            if controller == 0 and location == 4:
                required = (card.get("position"), card.get("identity_known"), card.get("code"), card.get("disabled"))
                if not _is_int(required[0]) or required[1] is not True or not _is_int(required[2]) or not isinstance(required[3], bool):
                    raise ValueError("incomplete")
                if required[2] in allowed and required[0] & 5 and not required[3]:
                    synchros += 1
        vector = {
            "completed": 1,
            "face_up_enabled_synchro": synchros,
            "retained_hand_cards": retained,
            "actual_draw_count": actual_draw_count,
        }
        success = (
            synchros >= goal["minimum_face_up_enabled_synchro"]
            and retained >= goal["minimum_retained_hand_cards"]
            and actual_draw_count >= goal["minimum_actual_draw_count"]
        )
        return {"vector": vector, "success": success}
    except (KeyError, TypeError, ValueError):
        return {"vector": empty, "success": False, "failure": "incomplete_observation"}


def _checked_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Required public P1 source is missing or malformed: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Required public P1 source is malformed: {path}")
    return value


def _relative_public_path(path):
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("P2 provenance source escapes the repository") from error


def _add_provenance(rows, path, kind, expected=None):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Required public P2 source is missing: {path}")
    actual = _sha256(path)
    if expected is not None and actual != expected:
        raise ValueError(f"Required public P2 source hash differs: {_relative_public_path(path)}")
    row = {"path": _relative_public_path(path), "sha256": actual, "kind": kind}
    if row not in rows:
        rows.append(row)
    return actual


def _source_path(relative):
    if not isinstance(relative, str):
        raise ValueError("P1 source path is malformed")
    path = ROOT.joinpath(*relative.replace("\\", "/").split("/")).resolve()
    if not path.is_relative_to(P1.resolve()):
        raise ValueError("P1 exclusion source is outside the known public experiment directory")
    return path


def _initial_hand_from_steps(record, path):
    steps = record.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"P1 steps are malformed: {_relative_public_path(path)}")
    if not steps:
        return None
    before = steps[0].get("before") if isinstance(steps[0], dict) else None
    cards = before.get("state", {}).get("cards") if isinstance(before, dict) else None
    if not isinstance(cards, list):
        raise ValueError(f"P1 initial step is malformed: {_relative_public_path(path)}")
    hand = []
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError(f"P1 initial cards are malformed: {_relative_public_path(path)}")
        if card.get("controller") == 0 and card.get("location") == 2:
            code = card.get("code")
            if not _is_int(code) or code <= 0:
                raise ValueError(f"P1 initial own hand identity is unavailable: {_relative_public_path(path)}")
            hand.append(code)
    return hand or None


def _collect_exclusions():
    exclusions = [
        [20001443, 93490856, 23431858, 14558127, 10045474],
        [20001443, 23431858, 14558127, 97268402, 10045474],
    ]
    provenance = []
    _add_provenance(provenance, ROOT / "experiments/ygo_agent/run.py", "original_poc_hands")

    data_manifests = sorted(P1.glob("data-v2-*/manifest.json"))
    development_manifests = sorted(P1.glob("development-*/manifest.json"))
    if not data_manifests or not development_manifests:
        raise ValueError("Required P1 data-v2 and development manifests are missing")
    for path in data_manifests:
        manifest = _checked_json(path)
        _add_provenance(provenance, path, "p1_data_v2_manifest")
        hands = manifest.get("source_hands")
        files = manifest.get("source_files")
        if not isinstance(hands, list) or not isinstance(files, list) or len(hands) != len(files):
            raise ValueError(f"P1 data-v2 manifest is malformed: {_relative_public_path(path)}")
        for hand in hands:
            exclusions.append(list(_normalized_hand(hand)))
        for source in files:
            if not isinstance(source, dict) or not isinstance(source.get("sha256"), str):
                raise ValueError(f"P1 source file row is malformed: {_relative_public_path(path)}")
            source_path = _source_path(source.get("file"))
            _add_provenance(provenance, source_path, "p1_data_v2_source", source["sha256"])
    for path in development_manifests:
        manifest = _checked_json(path)
        _add_provenance(provenance, path, "p1_development_manifest")
        hands = manifest.get("hands")
        if not isinstance(hands, list) or manifest.get("count") != len(hands):
            raise ValueError(f"P1 development manifest is malformed: {_relative_public_path(path)}")
        for hand in hands:
            normalized = _normalized_hand(hand)
            if len(normalized) != 5:
                raise ValueError(f"P1 development hand is malformed: {_relative_public_path(path)}")
            exclusions.append(list(normalized))

    reports = []
    for path in sorted(P1.glob("report-*/summary.json")):
        report = _checked_json(path)
        if (report.get("status"), report.get("mechanism_cases"), report.get("controlled_demonstrations")) == ("passed", 60, 5):
            reports.append((path, report))
    if not reports:
        raise ValueError("Published passing P1 mechanism/demonstration report is missing")
    report_path, report = reports[-1]
    _add_provenance(provenance, report_path, "p1_published_report")
    selected = []
    for source in report.get("source_checks", []):
        relative = source.get("file") if isinstance(source, dict) else None
        if not isinstance(relative, str) or not ("/mechanisms-" in relative or "/demonstrations-" in relative):
            continue
        expected = source.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("P1 report source hash is malformed")
        selected.append((relative, expected))
    if len(selected) != 65:
        raise ValueError("Published P1 report must identify 60 mechanism and 5 demonstration sources")
    for relative, expected in selected:
        path = _source_path(relative)
        record = _checked_json(path)
        _add_provenance(provenance, path, "p1_mechanism_or_demonstration", expected)
        if record.get("status") != "passed":
            raise ValueError(f"P1 exclusion source did not pass: {relative}")
        hand = _initial_hand_from_steps(record, path)
        if hand:
            exclusions.append(list(_normalized_hand(hand)))
    return exclusions, provenance


def create_protocol(output: Path):
    """Create the local protocol exclusively, or reuse only an identical verified file."""
    from experiments.ygo_agent.run import read_deck

    lock_path = ROOT / "experiments/ygo_agent/assets.lock.json"
    lock = _checked_json(lock_path)
    record = next((item for item in lock.get("files", []) if item.get("path") == "TenyiSword.ydk"), None)
    if not record or not isinstance(record.get("sha256"), str):
        raise ValueError("Pinned TenyiSword asset record is missing")
    deck_path = PILOT / "TenyiSword.ydk"
    if _sha256(deck_path) != record["sha256"]:
        raise ValueError("Frozen public TenyiSword deck differs from assets.lock.json")
    exclusions, provenance = _collect_exclusions()
    _add_provenance(provenance, lock_path, "asset_lock")
    _add_provenance(provenance, deck_path, "frozen_public_deck", record["sha256"])
    expected = build_protocol(
        read_deck(deck_path), exclusions, provenance,
        sampling_seed=SAMPLING_SEED, code_hash=_sha256(Path(__file__)),
    )
    output = Path(output)
    if output.exists():
        existing = load_protocol(output)
        if existing != expected:
            raise FileExistsError("Existing P2 protocol is valid but differs from current frozen sources")
        return existing
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
    try:
        with output.open("x", encoding="utf-8", newline="\n") as target:
            target.write(payload)
    except FileExistsError:
        existing = load_protocol(output)
        if existing != expected:
            raise FileExistsError("Concurrent P2 protocol creation produced different content")
        return existing
    return load_protocol(output)


__all__ = [
    "ACTUAL_DRAW_REVEAL_IDS", "ALLOWED_SYNCHRO_IDS", "ENGINE_SEED", "PRESERVE_RESOURCE_IDS",
    "RESOURCE_ACCESS_IDS", "SAMPLING_SEED", "SCENARIOS", "build_protocol",
    "calibration_families", "create_protocol", "evaluate_goal", "load_protocol",
]
