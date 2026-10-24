"""Protocol constants for the Womier SK80.

The SK80 shares the SONiX/Aula command set.  Values in this module were
verified against the connected keyboard (VID 05AC, PID 024F) and against the
vendor's own KeyboardLayout.xml.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# USB identifiers
# ---------------------------------------------------------------------------

VENDOR_ID = 0x05AC
PRODUCT_ID = 0x024F

CONFIG_INTERFACE = 3       # HID feature reports (usage page 0xFF13)
LCD_INTERFACE = 2          # LCD data (usage page 0xFF68)

REPORT_SIZE = 64
CMD_DELAY = 0.035          # seconds; vendor config.xml cmd_delaytime

PAGE_SIZE = 4096
LCD_WIDTH = 160
LCD_HEIGHT = 96
LCD_HEADER_SIZE = 256
LCD_MAX_FRAMES = 255
LCD_SAFE_FRAMES = 141      # firmware starts corrupting menus above this

# ---------------------------------------------------------------------------
# Lighting
# ---------------------------------------------------------------------------

#: (id, English name) in the order used by the vendor software.
LIGHTING_MODES = [
    (0, "Off"),
    (1, "Static"),
    (2, "Single On"),
    (3, "Single Off"),
    (4, "Glittering"),
    (5, "Falling"),
    (6, "Colourful"),
    (7, "Breath"),
    (8, "Spectrum"),
    (9, "Outward"),
    (10, "Scrolling"),
    (11, "Rolling"),
    (12, "Rotating"),
    (13, "Explode"),
    (14, "Launch"),
    (15, "Ripples"),
    (16, "Flowing"),
    (17, "Pulsating"),
    (18, "Tilt"),
    (19, "Shuttle"),
    (20, "Inwards"),
    (21, "Floweriness"),
]

MODE_NAMES = dict(LIGHTING_MODES)
MODE_IDS = {name.lower(): mode for mode, name in LIGHTING_MODES}

#: Modes for which the colour field is meaningful.
COLOR_MODES = set(range(1, 22)) - {6, 8}  # Colourful / Spectrum are rainbow only

DIRECTIONS = [(0, "Forward"), (1, "Reverse")]

# ---------------------------------------------------------------------------
# Remapping
# ---------------------------------------------------------------------------

#: Remap action type bytes.
ACTION_NONE = 0x00
ACTION_SPECIAL = 0x01
ACTION_KEY = 0x02
ACTION_CONSUMER = 0x03
ACTION_PROFILE = 0x05
ACTION_MACRO = 0x06
ACTION_MOUSE = 0x07

ACTION_NAMES = {
    ACTION_NONE: "Disabled",
    ACTION_SPECIAL: "Special",
    ACTION_KEY: "Key / Combo",
    ACTION_CONSUMER: "Multimedia",
    ACTION_MOUSE: "Mouse",
}

#: Special functions: name -> (param1, param2).
SPECIAL_FUNCTIONS = {
    "numlock": (0x01, 0x01),
    "scrolllock": (0x01, 0x04),
    "capslock": (0x01, 0x02),
    "insert": (0x01, 0x03),
    "calculator": (0x03, 0x01),
    "lockpc": (0x03, 0xFF),
    "alttab": (0x01, 0x08),
    "system": (0x01, 0x10),
}

SPECIAL_LABELS = {
    "numlock": "Num Lock",
    "scrolllock": "Scroll Lock",
    "capslock": "Caps Lock",
    "insert": "Insert toggle",
    "calculator": "Calculator",
    "lockpc": "Lock PC",
    "alttab": "Alt+Tab",
    "system": "System function",
}

#: Consumer (multimedia) controls: name -> HID Consumer Page usage.
CONSUMER_KEYS = {
    "play": 0xCD,
    "stop": 0xB7,
    "prev": 0xB6,
    "next": 0xB5,
    "volup": 0xE9,
    "voldown": 0xEA,
    "mute": 0xE2,
}

CONSUMER_LABELS = {
    "play": "Play / Pause",
    "stop": "Stop",
    "prev": "Previous track",
    "next": "Next track",
    "volup": "Volume up",
    "voldown": "Volume down",
    "mute": "Mute",
}

#: Mouse actions: name -> (param1, param2, param3).
MOUSE_ACTIONS = {
    "lclick": (0x01, 0x00, 0x00),
    "rclick": (0x02, 0x00, 0x00),
    "mclick": (0x04, 0x00, 0x00),
    "scrollup": (0x00, 0x01, 0x00),
    "scrolldn": (0x00, 0xFF, 0x00),
}

MOUSE_LABELS = {
    "lclick": "Left click",
    "rclick": "Right click",
    "mclick": "Middle click",
    "scrollup": "Scroll up",
    "scrolldn": "Scroll down",
}

#: Modifier bit flags, in USB HID order.
MODIFIERS = [
    ("Ctrl", 0x01),
    ("Shift", 0x02),
    ("Alt", 0x04),
    ("Win", 0x08),
    ("RCtrl", 0x10),
    ("RShift", 0x20),
    ("RAlt", 0x40),
    ("RWin", 0x80),
]

#: Modifier HID usage -> bit flag.
HID_MODIFIER_BITS = {
    0xE0: 0x01,  # Left Ctrl
    0xE1: 0x02,  # Left Shift
    0xE2: 0x04,  # Left Alt
    0xE3: 0x08,  # Left GUI
    0xE4: 0x10,  # Right Ctrl
    0xE5: 0x20,  # Right Shift
    0xE6: 0x40,  # Right Alt
    0xE7: 0x80,  # Right GUI
}

#: Target keys available in the remap editor.  These are HID Usage Page 0x07
#: keyboard codes.  The SK80 layout is a subset; the numpad entries are
#: included because the firmware accepts them as remap targets.
HID_KEYS = {
    "esc": 0x29,
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D,
    "f5": 0x3E, "f6": 0x3F, "f7": 0x40, "f8": 0x41,
    "f9": 0x42, "f10": 0x43, "f11": 0x44, "f12": 0x45,
    "f13": 0x68, "f14": 0x69, "f15": 0x6A, "f16": 0x6B,
    "f17": 0x6C, "f18": 0x6D, "f19": 0x6E, "f20": 0x6F,
    "f21": 0x70, "f22": 0x71, "f23": 0x72, "f24": 0x73,
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48,

    "grave": 0x35,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "minus": 0x2D, "equal": 0x2E, "backspace": 0x2A,
    "insert": 0x49, "home": 0x4A, "pageup": 0x4B,
    "numlock": 0x53, "numslash": 0x54, "numstar": 0x55,
    "numminus": 0x56,

    "tab": 0x2B,
    "q": 0x14, "w": 0x1A, "e": 0x08, "r": 0x15, "t": 0x17,
    "y": 0x1C, "u": 0x18, "i": 0x0C, "o": 0x12, "p": 0x13,
    "lbracket": 0x2F, "rbracket": 0x30, "backslash": 0x31,
    "delete": 0x4C, "end": 0x4D, "pagedown": 0x4E,
    "num7": 0x5F, "num8": 0x60, "num9": 0x61, "numplus": 0x57,

    "capslock": 0x39,
    "a": 0x04, "s": 0x16, "d": 0x07, "f": 0x09, "g": 0x0A,
    "h": 0x0B, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "semicolon": 0x33, "quote": 0x34, "enter": 0x28,
    "num4": 0x5C, "num5": 0x5D, "num6": 0x5E,

    "lshift": 0xE1,
    "z": 0x1D, "x": 0x1B, "c": 0x06, "v": 0x19, "b": 0x05,
    "n": 0x11, "m": 0x10,
    "comma": 0x36, "dot": 0x37, "slash": 0x38,
    "rshift": 0xE5, "up": 0x52,
    "num1": 0x59, "num2": 0x5A, "num3": 0x5B, "numenter": 0x58,

    "lctrl": 0xE0, "lwin": 0xE3, "lalt": 0xE2,
    "space": 0x2C, "ralt": 0xE6, "rctrl": 0xE4, "rwin": 0xE7,
    "menu": 0x65, "fn": 0xAF,
    "left": 0x50, "down": 0x51, "right": 0x4F,
    "num0": 0x62, "numdot": 0x63,

    # Common system keys.
    "power": 0x66, "sleep": 0x67, "wake": 0x68,
    "mute": 0x7F, "volup": 0x80, "voldown": 0x81,
    "browser_back": 0x224, "browser_forward": 0x225,
    "browser_refresh": 0x227, "browser_stop": 0x226,
    "browser_home": 0x223, "browser_search": 0x221,
}

#: Friendly labels for the remap target picker.
HID_KEY_LABELS = {
    "grave": "` ~", "minus": "- _", "equal": "= +",
    "lbracket": "[ {", "rbracket": "] }", "backslash": "\\ |",
    "semicolon": "; :", "quote": "' \"", "comma": ", <",
    "dot": ". >", "slash": "/ ?",
    "esc": "Esc", "backspace": "Backspace", "capslock": "Caps Lock",
    "lshift": "Left Shift", "rshift": "Right Shift",
    "lctrl": "Left Ctrl", "rctrl": "Right Ctrl",
    "lalt": "Left Alt", "ralt": "Right Alt",
    "lwin": "Left Win", "rwin": "Right Win", "menu": "Menu",
    "pageup": "Page Up", "pagedown": "Page Down",
    "insert": "Insert", "delete": "Delete", "home": "Home", "end": "End",
    "printscreen": "Print Screen", "scrolllock": "Scroll Lock", "pause": "Pause",
    "numlock": "Num Lock", "numslash": "Num /", "numstar": "Num *",
    "numminus": "Num -", "numplus": "Num +", "numenter": "Num Enter",
    "numdot": "Num .", "num0": "Num 0", "num1": "Num 1", "num2": "Num 2",
    "num3": "Num 3", "num4": "Num 4", "num5": "Num 5", "num6": "Num 6",
    "num7": "Num 7", "num8": "Num 8", "num9": "Num 9",
    "up": "↑ Up", "down": "↓ Down", "left": "← Left", "right": "→ Right",
    "space": "Space", "enter": "Enter", "tab": "Tab", "fn": "Fn",
    "volup": "Volume Up", "voldown": "Volume Down", "mute": "Mute",
    "power": "Power", "sleep": "Sleep", "wake": "Wake",
}


def hid_key_label(name: str) -> str:
    if name in HID_KEY_LABELS:
        return HID_KEY_LABELS[name]
    if len(name) == 1:
        return name.upper()
    if name.startswith("f") and name[1:].isdigit():
        return name.upper()
    return name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Per-key colour presets
# ---------------------------------------------------------------------------

COLOR_PRESETS = [
    ("Red", (255, 0, 0)),
    ("Orange", (255, 96, 0)),
    ("Yellow", (255, 200, 0)),
    ("Green", (0, 255, 0)),
    ("Cyan", (0, 255, 200)),
    ("Blue", (0, 64, 255)),
    ("Purple", (160, 0, 255)),
    ("Pink", (255, 0, 160)),
    ("White", (255, 255, 255)),
]
