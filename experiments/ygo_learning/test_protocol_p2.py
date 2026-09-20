"""Focused P2 family partition and structural-goal tests."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.ygo_learning.protocol_p2 import (
    ACTUAL_DRAW_REVEAL_IDS,
    PRESERVE_RESOURCE_IDS,
    RESOURCE_ACCESS_IDS,
    build_protocol,
    calibration_families,
    evaluate_goal,
    load_protocol,
)
import experiments.ygo_learning.protocol_p2 as protocol_p2


PUBLIC_MAIN = (
    [6728559]
    + [10045474] * 3
    + [14558127] * 3
    + [14821890] * 2
    + [20001443] * 3
    + [23431858]
    + [23434538] * 3
    + [24224830] * 2
    + [27204311]
    + [35261759] * 2
    + [55273560] * 3
    + [56465981] * 3
    + [56495147] * 3
    + [87052196] * 2
    + [93490856] * 3
    + [93850690]
    + [97268402] * 3
    + [98159737]
)
PUBLIC_EXTRA = [
    5041348, 9464441, 32519092, 32519092, 32519092, 42632209, 43202238,
    47710198, 60465049, 69248256, 69248256, 78917791, 83755611, 84815190,
    96633955,
]


def fixture_protocol():
    excluded = [[20001443, 93490856, 23431858, 14558127, 10045474]]
    return build_protocol(
        {"main": PUBLIC_MAIN, "extra": PUBLIC_EXTRA, "side": []},
        excluded,
        [],
        sampling_seed=20260920,
        code_hash=hashlib.sha256(Path(protocol_p2.__file__).read_bytes()).hexdigest(),
    )


class ProtocolPartitionTests(unittest.TestCase):
    def test_builds_deterministic_disjoint_stratified_families(self):
        protocol = fixture_protocol()
        again = fixture_protocol()
        self.assertEqual(protocol, again)
        self.assertEqual(len(protocol["families"]), 200)

        by_scenario = defaultdict(list)
        hands = []
        for family in protocol["families"]:
            by_scenario[family["scenario"]].append(family)
            self.assertEqual(family["hand"], sorted(family["hand"]))
            self.assertEqual(family["engine_seed"], 42)
            hands.append(tuple(family["hand"]))
        self.assertEqual(len(set(hands)), 200)
        self.assertNotIn(tuple(sorted([20001443, 93490856, 23431858, 14558127, 10045474])), hands)

        self.assertEqual(set(by_scenario), {
            "no_extra_response", "one_ash", "resource_tight", "actual_draw", "preserve_resources"
        })
        for families in by_scenario.values():
            self.assertEqual(len(families), 40)
            self.assertEqual(Counter(f["split"] for f in families), {
                "train": 24, "validation": 8, "holdout": 8
            })

        for family in by_scenario["resource_tight"]:
            self.assertEqual(sum(code in RESOURCE_ACCESS_IDS for code in family["hand"]), 1)
        for family in by_scenario["actual_draw"]:
            self.assertIn(20001443, family["hand"])
            revealable = Counter(family["hand"])
            revealable[20001443] -= 1
            self.assertTrue(any(count and code in ACTUAL_DRAW_REVEAL_IDS for code, count in revealable.items()))
        for family in by_scenario["preserve_resources"]:
            self.assertGreaterEqual(sum(code in PRESERVE_RESOURCE_IDS for code in family["hand"]), 2)

        calibration = calibration_families(protocol)
        self.assertEqual(len(calibration), 20)
        self.assertTrue(all(family["split"] == "train" for family in calibration))
        self.assertEqual(Counter(family["scenario"] for family in calibration), {
            "no_extra_response": 4, "one_ash": 4, "resource_tight": 4,
            "actual_draw": 4, "preserve_resources": 4,
        })

    def test_rejects_malformed_inputs_and_insufficient_qualified_hands(self):
        with self.assertRaisesRegex(ValueError, "normalized hand"):
            build_protocol(
                {"main": PUBLIC_MAIN, "extra": PUBLIC_EXTRA, "side": []},
                [[True, 2, 3, 4, 5]], [], sampling_seed=1, code_hash="b" * 64,
            )
        with self.assertRaisesRegex(ValueError, "40 qualified"):
            build_protocol(
                {"main": [20001443] * 5 + [1] * 35, "extra": PUBLIC_EXTRA, "side": []},
                [], [], sampling_seed=1, code_hash="b" * 64,
            )

    def test_load_rejects_content_changed_after_freeze(self):
        protocol = fixture_protocol()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "protocol.json"
            path.write_text(json.dumps(protocol), encoding="utf-8")
            self.assertEqual(load_protocol(path), protocol)
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["families"][0]["hand"][0] += 1
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                load_protocol(path)

    def test_load_rejects_changed_code_or_provenance_source(self):
        protocol = fixture_protocol()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "protocol.json"
            changed_code = json.loads(json.dumps(protocol))
            changed_code["code_sha256"] = "c" * 64
            changed_code["fingerprint"] = hashlib.sha256(json.dumps(
                {key: value for key, value in changed_code.items() if key != "fingerprint"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            path.write_text(json.dumps(changed_code), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "code SHA"):
                load_protocol(path)

            changed_source = json.loads(json.dumps(protocol))
            changed_source["provenance"] = [{
                "path": "docs/ai-learning-p2-protocol.md",
                "sha256": "d" * 64,
                "kind": "fixture",
            }]
            changed_source["fingerprint"] = hashlib.sha256(json.dumps(
                {key: value for key, value in changed_source.items() if key != "fingerprint"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            path.write_text(json.dumps(changed_source), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provenance"):
                load_protocol(path)


def observation(*, position=1, disabled=False, hand_cards=1, include_disabled=True):
    synchro = {
        "controller": 0, "location": 4, "position": position,
        "identity_known": True, "code": 69248256,
    }
    if include_disabled:
        synchro["disabled"] = disabled
    cards = [synchro]
    cards.extend({
        "controller": 0, "location": 2, "position": 0,
        "identity_known": True, "code": 14558127,
    } for _ in range(hand_cards))
    return {"schema": "p2_goal_card_view_v1", "cards": cards}


BASE_GOAL = {
    "kind": "first_turn_synchro_resources_v1",
    "allowed_synchro_codes": [69248256, 84815190],
    "minimum_face_up_enabled_synchro": 1,
    "minimum_retained_hand_cards": 1,
    "minimum_actual_draw_count": 0,
}


class GoalEvaluationTests(unittest.TestCase):
    def test_positive_complete_visible_enabled_faceup_synchro_and_resource(self):
        result = evaluate_goal(observation(), BASE_GOAL, completed=True, actual_draw_count=0)
        self.assertTrue(result["success"])
        self.assertEqual(result["vector"], {
            "completed": 1,
            "face_up_enabled_synchro": 1,
            "retained_hand_cards": 1,
            "actual_draw_count": 0,
        })

    def test_complete_disabled_facedown_and_resource_cases_fail_independently(self):
        cases = (
            (observation(), False, 0),
            (observation(disabled=True), True, 0),
            (observation(position=2), True, 0),
            (observation(hand_cards=0), True, 0),
        )
        for observed, completed, draws in cases:
            with self.subTest(observed=observed, completed=completed):
                self.assertFalse(evaluate_goal(
                    observed, BASE_GOAL, completed=completed, actual_draw_count=draws
                )["success"])

    def test_preserve_and_actual_draw_thresholds_are_structural(self):
        preserve = {**BASE_GOAL, "minimum_retained_hand_cards": 2}
        self.assertFalse(evaluate_goal(
            observation(hand_cards=1), preserve, completed=True, actual_draw_count=3
        )["success"])
        self.assertTrue(evaluate_goal(
            observation(hand_cards=2), preserve, completed=True, actual_draw_count=0
        )["success"])

        draw = {**BASE_GOAL, "minimum_actual_draw_count": 1}
        self.assertFalse(evaluate_goal(
            observation(), draw, completed=True, actual_draw_count=0
        )["success"])
        self.assertTrue(evaluate_goal(
            observation(), draw, completed=True, actual_draw_count=1
        )["success"])

    def test_incomplete_or_unknown_observation_fails_closed(self):
        result = evaluate_goal(
            observation(include_disabled=False), BASE_GOAL, completed=True, actual_draw_count=0
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["failure"], "incomplete_observation")
        self.assertFalse(evaluate_goal(
            {"schema": "wrong", "cards": []}, BASE_GOAL, completed=True, actual_draw_count=0
        )["success"])
        self.assertFalse(evaluate_goal(
            observation(), BASE_GOAL, completed=True, actual_draw_count=-1
        )["success"])


if __name__ == "__main__":
    unittest.main()
