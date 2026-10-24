"""SK80 key layout.

The layout shipped with the Windows driver (KeyboardLayout.xml) is *not* valid
XML: a few ``name``/``desc`` attributes contain raw ``<``/``>`` characters.
We therefore parse the ``<key .../>`` records with a small, tolerant parser
instead of ElementTree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from typing import Dict, List, Optional

_KEY_RE = re.compile(r"<key\s+(.*?)\s*/>", re.S)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


@dataclass(frozen=True)
class Key:
    """One physical key on the SK80."""

    raw_name: str
    name: str
    desc: str
    code: int          # USB HID usage code (keyboard page)
    key_index: int     # index used by the remap protocol
    light_index: int   # index used by the per-key RGB protocol
    rect: tuple[int, int, int, int]  # x, y, w, h in the driver's 800x300 canvas

    @property
    def label(self) -> str:
        """Short label suitable for a GUI button."""
        labels = {
            "escape": "Esc",
            "backspace": "Back",
            "capslock": "Caps",
            "lshift": "Shift",
            "rshift": "Shift",
            "lctrl": "Ctrl",
            "rctrl": "Ctrl",
            "lalt": "Alt",
            "ralt": "Alt",
            "lwin": "Win",
            "pageup": "PgUp",
            "pagedown": "PgDn",
            "delete": "Del",
            "insert": "Ins",
            "enter": "Enter",
            "space": "Space",
            "grave": "`",
            "semicolon": ";",
            "quote": "'",
            "comma": ",",
            "dot": ".",
            "slash": "/",
            "backslash": "\\",
            "minus": "-",
            "equal": "=",
            "lbracket": "[",
            "rbracket": "]",
            "up": "↑",
            "down": "↓",
            "left": "←",
            "right": "→",
            "fn": "Fn",
        }
        if self.name.startswith("f") and self.name[1:].isdigit():
            return self.name.upper()
        return labels.get(self.name, self.name.upper() if len(self.name) == 1 else self.name)


def _normalise(raw: str, x: int) -> str:
    n = raw.strip()
    lower = n.lower()
    if lower == "esc":
        return "escape"
    if lower in {"caps"}:
        return "capslock"
    if lower == "del":
        return "delete"
    if lower == "page up":
        return "pageup"
    if lower == "page down":
        return "pagedown"
    if lower == "backspace":
        return "backspace"
    if n == "~":
        return "grave"
    if n == "\\|":
        return "backslash"
    if n == ";:":
        return "semicolon"
    if n in {"'\"", "&apos;&quot;", "quote"}:
        return "quote"
    if n == "[":
        return "lbracket"
    if n == "]":
        return "rbracket"
    if n == "-":
        return "minus"
    if n == "=":
        return "equal"
    if n == "<":
        return "comma"
    if n == ">":
        return "dot"
    if n == "?":
        return "slash"
    if lower == "shift":
        return "lshift" if x < 300 else "rshift"
    if lower == "control":
        return "lctrl" if x < 300 else "rctrl"
    if lower == "alt":
        return "lalt" if x < 300 else "ralt"
    if lower == "win":
        return "lwin"
    if n == "↑":
        return "up"
    if n == "↓":
        return "down"
    if n == "←":
        return "left"
    if n == "→":
        return "right"
    if lower == "fn":
        return "fn"
    if lower.startswith("f") and lower[1:].isdigit():
        return lower
    if len(n) == 1:
        return lower
    return lower.replace(" ", "")


def _load() -> List[Key]:
    text = resources.files("sk80.data").joinpath("KeyboardLayout.xml").read_text(
        encoding="utf-8"
    )
    keys: List[Key] = []
    for match in _KEY_RE.finditer(text):
        attrs = dict(_ATTR_RE.findall(match.group(1)))
        try:
            x = int(attrs["rect_left"])
            y = int(attrs["rect_top"])
            w = int(attrs["rect_width"])
            h = int(attrs["rect_height"])
            key = Key(
                raw_name=attrs["name"],
                name=_normalise(attrs["name"], x),
                desc=attrs.get("desc", ""),
                code=int(attrs["code"], 16),
                key_index=int(attrs["key_index"]),
                light_index=int(attrs["light_index"]),
                rect=(x, y, w, h),
            )
        except (KeyError, ValueError):
            continue
        keys.append(key)
    return keys


KEYS: List[Key] = _load()
KEY_BY_NAME: Dict[str, Key] = {k.name: k for k in KEYS}
KEY_BY_INDEX: Dict[int, Key] = {k.key_index: k for k in KEYS}
KEY_BY_LIGHT_INDEX: Dict[int, Key] = {k.light_index: k for k in KEYS}

#: Canvas used by the driver's skin (all ``rect_*`` values are in this space).
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 300


def get_key(name: str) -> Optional[Key]:
    """Look up a key by friendly name (case-insensitive, with aliases)."""
    n = name.strip().lower()
    aliases = {
        "esc": "escape",
        "caps": "capslock",
        "del": "delete",
        "pgup": "pageup",
        "pgdn": "pagedown",
        "`": "grave",
        "\\": "backslash",
        ";": "semicolon",
        "'": "quote",
        ",": "comma",
        ".": "dot",
        "/": "slash",
        "-": "minus",
        "=": "equal",
        "lshift": "lshift",
        "rshift": "rshift",
        "left shift": "lshift",
        "right shift": "rshift",
        "ctrl": "lctrl",
        "control": "lctrl",
        "left ctrl": "lctrl",
        "right ctrl": "rctrl",
        "alt": "lalt",
        "left alt": "lalt",
        "right alt": "ralt",
        "win": "lwin",
        "windows": "lwin",
        "menu": "menu",
    }
    n = aliases.get(n, n)
    return KEY_BY_NAME.get(n)
