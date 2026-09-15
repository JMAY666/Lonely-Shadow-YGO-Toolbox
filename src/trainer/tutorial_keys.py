"""Read only the configured tutorial keys while its background shortcuts are active.

No input injection, keyboard hook, text capture, or storage. The desktop process
stops this helper on focus, suspension and exit; its parent handle also bounds it.
"""
import ctypes
from ctypes import wintypes
import json
import sys
import time


def virtual_key(key):
    keys = {'LEFT': 0x25, 'UP': 0x26, 'RIGHT': 0x27, 'DOWN': 0x28,
            'SPACE': 0x20, 'ENTER': 0x0D, 'HOME': 0x24, 'END': 0x23,
            'PAGEUP': 0x21, 'PAGEDOWN': 0x22}
    if key in keys: return keys[key]
    if len(key) == 1 and key.isascii() and key.isalnum(): return ord(key)
    if key.startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1
    raise ValueError('Unsupported tutorial key')


def pressed_actions(bindings, down):
    modifiers = {'CONTROL': down(0x11), 'ALT': down(0x12), 'SHIFT': down(0x10),
                 'SUPER': down(0x5B) or down(0x5C)}
    result = []
    for action, binding in bindings.items():
        if not binding: continue
        *mods, key = binding.upper().split('+')
        if all(on == (name in mods) for name, on in modifiers.items()) and down(virtual_key(key)):
            result.append(action)
    return result


def main():
    bindings, parent_pid = json.loads(sys.argv[1]), int(sys.argv[2])
    user32, kernel = ctypes.WinDLL('user32'), ctypes.WinDLL('kernel32')
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    parent = kernel.OpenProcess(0x100000, False, parent_pid)
    if not parent: return
    try:
        while kernel.WaitForSingleObject(parent, 0) == 0x102:
            # The high bit is the current physical state; the low bit is ignored.
            actions = pressed_actions(bindings, lambda key: bool(user32.GetAsyncKeyState(key) & 0x8000))
            print(json.dumps(actions), flush=True)
            time.sleep(0.025)
    finally:
        kernel.CloseHandle(parent)


if __name__ == '__main__':
    main()
