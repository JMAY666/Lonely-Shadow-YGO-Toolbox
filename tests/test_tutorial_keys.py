from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from tutorial_keys import pressed_actions, virtual_key


class TutorialKeyTests(unittest.TestCase):
    def test_only_configured_actions_and_exact_modifiers_are_reported(self):
        bindings = {'back': 'LEFT', 'forward': 'CONTROL+ALT+F8', 'end': ''}
        self.assertEqual(pressed_actions(bindings, {0x25}.__contains__), ['back'])
        self.assertEqual(pressed_actions(bindings, {0x25, 0x10}.__contains__), [])
        self.assertEqual(pressed_actions(bindings, {0x11, 0x12, 0x77}.__contains__), ['forward'])
        self.assertEqual(pressed_actions(bindings, {0x11, 0x12}.__contains__), [])
        self.assertEqual(pressed_actions(bindings, {ord('P'), 0x26}.__contains__), [])
        self.assertEqual(pressed_actions(bindings, set().__contains__), [])

    def test_supported_key_mapping_including_right_windows_modifier(self):
        self.assertEqual(virtual_key('F24'), 0x87)
        self.assertEqual(virtual_key('PAGEUP'), 0x21)
        self.assertEqual(virtual_key('9'), ord('9'))
        self.assertEqual(pressed_actions({'up': 'SUPER+UP'}, {0x5C, 0x26}.__contains__), ['up'])
        with self.assertRaises(ValueError): virtual_key('F25')
