"""Command-line interface for the Womier SK80."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from . import __version__, constants as C, screen
from .config import Store
from .layout import KEYS, KEY_BY_INDEX, get_key
from .protocol import SK80, DeviceNotFound, ProtocolError, find_lcd_hidraw


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def parse_color(value: str) -> tuple[int, int, int]:
    text = value.strip().lower().lstrip("#")
    for name, rgb in C.COLOR_PRESETS:
        if text == name.lower():
            return rgb
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise argparse.ArgumentTypeError("colour must be RRGGBB, #RRGGBB, or a preset name")
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid colour: {value}") from exc


def parse_mode(value: str) -> int:
    text = " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())
    if text.isdigit():
        mode = int(text)
        if 0 <= mode <= 21:
            return mode
    if text in C.MODE_IDS:
        return C.MODE_IDS[text]
    names = ", ".join(name for _mode, name in C.LIGHTING_MODES)
    raise argparse.ArgumentTypeError(f"unknown mode {value!r}; choose one of: {names}")


def parse_key(value: str):
    key = get_key(value)
    if key is None and value.strip().isdigit():
        key = KEY_BY_INDEX.get(int(value))
    if key is None:
        raise argparse.ArgumentTypeError(f"unknown key {value!r}")
    return key


def _modifier_mask(names: Iterable[str]) -> tuple[int, list[str]]:
    lookup = {name.lower(): bit for name, bit in C.MODIFIERS}
    mask = 0
    used: list[str] = []
    for name in names:
        name = name.strip().lower()
        if not name:
            continue
        if name not in lookup:
            raise ValueError(f"unknown modifier {name!r}")
        mask |= lookup[name]
        used.append(name.capitalize())
    return mask, used


def parse_target(value: str) -> tuple[tuple[int, int, int, int], str]:
    """Parse a remap target into ``(action, p1, p2, p3)`` and a label."""
    text = value.strip()
    lower = text.lower()

    if lower in {"none", "disabled", "off"}:
        return (C.ACTION_NONE, 0, 0, 0), "Disabled"

    if ":" in text:
        kind, arg = text.split(":", 1)
        kind = kind.strip().lower()
        arg = arg.strip()
        if kind in {"media", "consumer"}:
            key = arg.lower()
            if key not in C.CONSUMER_KEYS:
                raise ValueError(
                    "unknown multimedia key; choose: " + ", ".join(C.CONSUMER_KEYS)
                )
            return (C.ACTION_CONSUMER, C.CONSUMER_KEYS[key], 0, 0), C.CONSUMER_LABELS[key]
        if kind == "mouse":
            key = arg.lower()
            if key not in C.MOUSE_ACTIONS:
                raise ValueError("unknown mouse action; choose: " + ", ".join(C.MOUSE_ACTIONS))
            p1, p2, p3 = C.MOUSE_ACTIONS[key]
            return (C.ACTION_MOUSE, p1, p2, p3), C.MOUSE_LABELS[key]
        if kind == "special":
            key = arg.lower()
            if key not in C.SPECIAL_FUNCTIONS:
                raise ValueError(
                    "unknown special function; choose: " + ", ".join(C.SPECIAL_FUNCTIONS)
                )
            p1, p2 = C.SPECIAL_FUNCTIONS[key]
            return (C.ACTION_SPECIAL, p1, p2, 0), C.SPECIAL_LABELS[key]
        if kind in {"key", "hid"}:
            text = arg
            lower = text.lower()
        else:
            raise ValueError(f"unknown target type {kind!r}")

    if "+" in text:
        parts = [part for part in text.split("+") if part]
        if len(parts) < 2:
            raise ValueError(f"invalid combo {value!r}")
        mask, _used = _modifier_mask(parts[:-1])
        target_name = parts[-1]
        if target_name.lower() in {"", "none"}:
            return (C.ACTION_KEY, mask, 0, 0), "+".join(
                name for name, bit in C.MODIFIERS if mask & bit
            )
        target = C.HID_KEYS.get(target_name.lower())
        if target is None:
            key = get_key(target_name)
            if key is None:
                raise ValueError(f"unknown key {target_name!r} in combo")
            target = key.code
        return (C.ACTION_KEY, mask, target, 0), _describe_combo(mask, target)

    # A lone modifier remaps the key to that modifier.
    modifier_bits = {name.lower(): bit for name, bit in C.MODIFIERS}
    if lower in modifier_bits:
        bit = modifier_bits[lower]
        return (C.ACTION_KEY, bit, 0, 0), lower.capitalize()

    target = C.HID_KEYS.get(lower)
    if target is None:
        key = get_key(text)
        if key is None:
            raise ValueError(f"unknown target key {value!r}")
        target = key.code
    return (C.ACTION_KEY, 0, target, 0), C.hid_key_label(lower)


def _describe_combo(mask: int, target: int) -> str:
    names = [name for name, bit in C.MODIFIERS if mask & bit]
    if target:
        names.append(_target_key_name(target))
    return "+".join(names)


def _target_key_name(code: int) -> str:
    for name, value in C.HID_KEYS.items():
        if value == code:
            return C.hid_key_label(name)
    return f"0x{code:02x}"


def describe_slot(slot: tuple[int, int, int, int]) -> str:
    action, p1, p2, p3 = slot
    if action == C.ACTION_NONE:
        return "Disabled"
    if action == C.ACTION_SPECIAL:
        for name, params in C.SPECIAL_FUNCTIONS.items():
            if params == (p1, p2):
                return "Special: " + C.SPECIAL_LABELS[name]
        return f"Special 0x{p1:02x}/0x{p2:02x}"
    if action == C.ACTION_KEY:
        if p2 == 0:
            names = [name for name, bit in C.MODIFIERS if p1 & bit]
            return "+".join(names) if names else "None"
        return _describe_combo(p1, p2)
    if action == C.ACTION_CONSUMER:
        for name, code in C.CONSUMER_KEYS.items():
            if code == p1:
                return "Media: " + C.CONSUMER_LABELS[name]
        return f"Media 0x{p1:02x}"
    if action == C.ACTION_MOUSE:
        for name, params in C.MOUSE_ACTIONS.items():
            if params == (p1, p2, p3):
                return "Mouse: " + C.MOUSE_LABELS[name]
        return f"Mouse 0x{p1:02x}/0x{p2:02x}/0x{p3:02x}"
    return f"Action {action} ({p1:02x} {p2:02x} {p3:02x})"


def _store(args) -> Store:
    return Store(getattr(args, "config", None))


def _print_device(dev: SK80) -> None:
    print("Device: Womier SK80")
    print(f"  USB ID:       {C.VENDOR_ID:04x}:{C.PRODUCT_ID:04x}")
    print(f"  Bus/address:  {dev.dev.bus:03d}/{dev.dev.address:03d}")
    try:
        print(f"  Manufacturer: {dev.dev.manufacturer}")
        print(f"  Product:      {dev.dev.product}")
    except Exception:
        pass
    print(f"  LCD node:     {dev.lcd_path or 'not found'}")


def _progress(sent: int, total: int) -> None:
    if total <= 20 or sent == total or sent % max(1, total // 20) == 0:
        pct = sent * 100 // total
        print(f"\r  uploading: {sent}/{total} pages ({pct}%)", end="", flush=True)
        if sent == total:
            print()


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_status(args) -> int:
    store = _store(args)
    print(f"Womier SK80 control {__version__}")
    print(f"  Settings file: {store.path}")
    if not SK80.is_connected():
        print("  Status:        keyboard NOT connected")
        hidraw = find_lcd_hidraw()
        print(f"  LCD node:      {hidraw or 'not found'}")
        return 1
    with SK80() as dev:
        _print_device(dev)
    print("  Status:        connected")
    light = store.lighting
    print(
        "  Lighting:      {mode} rgb={color} brightness={brightness} speed={speed}".format(
            mode=C.MODE_NAMES.get(light["mode"], light["mode"]),
            color="#%02x%02x%02x" % tuple(light["color"]),
            brightness=light["brightness"],
            speed=light["speed"],
        )
    )
    print(f"  Per-key:       {len(store.per_key['colors'])} key(s) configured")
    print(
        "  Remaps:        {} normal, {} Fn".format(
            len(store.data["remap"]["normal"]), len(store.data["remap"]["fn"])
        )
    )
    return 0


def cmd_lighting(args) -> int:
    store = _store(args)
    light = store.lighting
    if args.off:
        light["mode"] = 0
    elif args.mode is not None:
        light["mode"] = args.mode
    if args.color is not None:
        light["color"] = list(args.color)
    if args.brightness is not None:
        light["brightness"] = args.brightness
    if args.speed is not None:
        light["speed"] = args.speed
    if args.direction is not None:
        light["direction"] = 0 if args.direction == "forward" else 1
    if args.rainbow:
        light["colorful"] = True
    if args.single_color:
        light["colorful"] = False

    r, g, b = light["color"]
    with SK80() as dev:
        dev.set_lighting(
            light["mode"],
            r=r,
            g=g,
            b=b,
            brightness=light["brightness"],
            speed=light["speed"],
            direction=light["direction"],
            colorful=light["colorful"],
        )
    store.save()
    print(
        "Applied {mode} (colour #{r:02x}{g:02x}{b:02x}, brightness {brightness}, speed {speed})".format(
            mode=C.MODE_NAMES.get(light["mode"], light["mode"]),
            r=r, g=g, b=b,
            brightness=light["brightness"],
            speed=light["speed"],
        )
    )
    return 0


def cmd_perkey(args) -> int:
    store = _store(args)
    colors = store.colors()

    if args.clear:
        colors.clear()
    if args.all is not None:
        for key in KEYS:
            colors[key.light_index] = args.all
    for item in args.set or []:
        if "=" not in item:
            raise SystemExit(f"--set expects KEY=RRGGBB, got {item!r}")
        key_name, color_text = item.split("=", 1)
        key = get_key(key_name)
        if key is None:
            raise SystemExit(f"unknown key {key_name!r}")
        colors[key.light_index] = parse_color(color_text)
    for item in args.off or []:
        key = get_key(item)
        if key is None:
            raise SystemExit(f"unknown key {item!r}")
        colors.pop(key.light_index, None)

    brightness = args.brightness if args.brightness is not None else store.per_key["brightness"]
    with SK80() as dev:
        dev.set_per_key(colors, brightness=brightness)
    store.set_colors(colors)
    store.per_key["brightness"] = brightness
    store.save()
    print(f"Applied per-key colours to {len(colors)} key(s) (brightness {brightness}).")
    return 0


def cmd_remap(args) -> int:
    store = _store(args)
    layer = "fn" if args.fn else "normal"
    table = store.remap_table(layer)

    if args.reset:
        table.clear()
    for item in args.clear or []:
        key = parse_key(item)
        table.pop(key.key_index, None)
    for item in args.set or []:
        if "=" not in item:
            raise SystemExit(f"--set expects KEY=TARGET, got {item!r}")
        key_name, target_text = item.split("=", 1)
        key = parse_key(key_name)
        try:
            slot, label = parse_target(target_text)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        table[key.key_index] = slot
        print(f"  {key.name} -> {label}")

    if args.list:
        if not table:
            print(f"No {layer} remaps.")
        for index, slot in sorted(table.items()):
            key = KEY_BY_INDEX.get(index)
            print(f"  {(key.name if key else index)!s:12} {describe_slot(slot)}")
        return 0

    with SK80() as dev:
        dev.set_remap(table, fn_layer=args.fn)
    store.set_remap_table(table, layer)
    store.save()
    print(f"Applied {len(table)} remap(s) to the {layer} layer.")
    return 0


def cmd_screen(args) -> int:
    if args.solid:
        frames = screen.solid_frames(args.solid, delay_ms=args.delay)
        source = "solid colour"
    elif args.black:
        frames = screen.solid_frames((0, 0, 0), delay_ms=args.delay)
        source = "black"
    else:
        if not args.path:
            raise SystemExit("screen: provide an image/GIF path, or use --solid/--black")
        path = Path(args.path).expanduser()
        if not path.is_file():
            raise SystemExit(f"screen: {path} not found")
        frames = screen.load_frames(
            path, fit=args.fit, resample=args.resample, default_delay_ms=args.delay
        )
        source = path.name

    if len(frames) > C.LCD_SAFE_FRAMES:
        print(
            f"warning: {len(frames)} frames; the firmware is known to corrupt its "
            f"menu above {C.LCD_SAFE_FRAMES} frames.",
            file=sys.stderr,
        )
    buffer = screen.build_buffer(frames)
    print(
        f"Uploading {source}: {len(frames)} frame(s), "
        f"{screen.total_duration(frames)} ms, {len(buffer) // C.PAGE_SIZE} pages"
    )
    with SK80() as dev:
        dev.upload_screen(buffer, slot=args.slot, progress=_progress)
    print(
        "To show this animation, select the picture-playback mode on the keyboard "
        "(Fn shortcut)."
    )
    return 0


def cmd_clock(args) -> int:
    when = None
    if args.set:
        try:
            when = datetime.strptime(args.set, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                when = datetime.strptime(args.set, "%Y-%m-%d %H:%M")
            except ValueError as exc:
                raise SystemExit("--set expects 'YYYY-MM-DD HH:MM[:SS]'") from exc
    when = when or datetime.now()
    with SK80() as dev:
        dev.set_clock(when)
    print("Clock data sent: " + when.strftime("%Y-%m-%d %H:%M:%S"))
    print(
        "note: the wired SK80's documented OLED pages do not include a clock; "
        "this writes the keyboard's RTC for firmware/models that expose one."
    )
    return 0


def cmd_keys(args) -> int:
    print(f"{'name':14} {'key':>4} {'light':>5}  {'HID':>4}")
    for key in KEYS:
        print(
            f"{key.name:14} {key.key_index:4d} {key.light_index:5d}  0x{key.code:02x}"
        )
    return 0


def cmd_info(args) -> int:
    print("Lighting modes:")
    for mode, name in C.LIGHTING_MODES:
        print(f"  {mode:2d}  {name}")
    print("\nMultimedia targets: " + ", ".join(C.CONSUMER_KEYS))
    print("Mouse targets:      " + ", ".join(C.MOUSE_ACTIONS))
    print("Special targets:    " + ", ".join(C.SPECIAL_FUNCTIONS))
    print("\nRemap targets can be: key name, modifier+key (ctrl+c),")
    print("media:volup, mouse:lclick, special:calculator, or disabled.")
    return 0


def cmd_gui(args) -> int:
    from .gui import main as gui_main

    return gui_main()


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sk80ctl",
        description="Native Linux control tool for the Womier SK80 keyboard.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config", metavar="PATH", help="use an alternative settings JSON file"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="show connection and saved settings")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("lighting", help="set the main backlight effect")
    p.add_argument("--mode", type=parse_mode, help="mode name or 0-21")
    p.add_argument("--color", type=parse_color, help="RRGGBB or preset name")
    p.add_argument("--brightness", type=int, choices=range(0, 6), help="0-5")
    p.add_argument("--speed", type=int, choices=range(0, 6), help="0-5")
    p.add_argument("--direction", choices=["forward", "reverse"])
    p.add_argument("--rainbow", action="store_true", help="use rainbow colours")
    p.add_argument("--single-color", action="store_true", help="use the selected colour")
    p.add_argument("--off", action="store_true", help="turn the backlight off")
    p.set_defaults(func=cmd_lighting)

    p = sub.add_parser("perkey", help="set individual key colours")
    p.add_argument("--set", action="append", metavar="KEY=RRGGBB", help="repeatable")
    p.add_argument("--off", action="append", metavar="KEY", help="turn a key off")
    p.add_argument("--all", type=parse_color, help="set every key to one colour")
    p.add_argument("--clear", action="store_true", help="clear all key colours")
    p.add_argument("--brightness", type=int, choices=range(0, 6), help="0-5")
    p.set_defaults(func=cmd_perkey)

    p = sub.add_parser("remap", help="remap keys")
    p.add_argument("--set", action="append", metavar="KEY=TARGET", help="repeatable")
    p.add_argument("--clear", action="append", metavar="KEY", help="remove a remap")
    p.add_argument("--reset", action="store_true", help="clear the whole layer")
    p.add_argument("--fn", action="store_true", help="edit the Fn layer")
    p.add_argument("--list", action="store_true", help="show saved remaps without applying")
    p.set_defaults(func=cmd_remap)

    p = sub.add_parser("screen", help="upload an image or GIF to the LCD")
    p.add_argument("path", nargs="?", help="image or animated GIF")
    p.add_argument("--slot", type=int, default=1, help="image slot (default 1)")
    p.add_argument("--fit", choices=["cover", "contain", "stretch"], default="cover")
    p.add_argument("--resample", choices=["nearest", "bilinear", "bicubic", "lanczos"], default="lanczos")
    p.add_argument("--delay", type=int, default=1000, help="static image delay in ms")
    p.add_argument("--solid", type=parse_color, help="upload a solid colour instead")
    p.add_argument("--black", action="store_true", help="upload a black frame")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("clock", help="write the keyboard's real-time clock")
    p.add_argument("--set", metavar="'YYYY-MM-DD HH:MM[:SS]'", help="use a specific time")
    p.set_defaults(func=cmd_clock)

    p = sub.add_parser("keys", help="list physical keys and their indices")
    p.set_defaults(func=cmd_keys)

    p = sub.add_parser("info", help="list supported modes and remap targets")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("gui", help="launch the graphical interface")
    p.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except DeviceNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ProtocolError as exc:
        print(f"USB error: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
