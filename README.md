# Womier SK80 — native Linux control

A native Linux driver and GUI for the **Womier SK80** 75% mechanical keyboard
with the small LCD screen.  It controls the backlight, per-key RGB, key
remapping, the LCD image/GIF and the LCD clock over USB — no Wine, no Windows
VM, and no vendor software required.

The keyboard was driven by Womier's Windows software. That installer is
proprietary and is **not** part of this repository; nothing here uses or
modifies it. The protocol below was worked out by watching what it sent.

![status](https://img.shields.io/badge/device-05ac%3A024f-blue)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

## Features

- **Lighting** — all 22 firmware effects, colour, brightness, speed and
  direction, including static and rainbow modes.
- **Per-key RGB** — paint individual keys with a click, or set them from the
  command line.
- **Key remapping** — normal and Fn layers, single keys, modifier combos,
  multimedia keys, mouse buttons and special functions.
- **LCD screen** — upload a 160×96 image or animated GIF, with fit/crop modes
  and a live preview.
- **LCD clock** — write the keyboard's real-time clock (the wired SK80's
  documented OLED pages do not include a clock screen; see below).
- **Two front ends** — a PySide6 desktop GUI and a scriptable `sk80ctl` CLI.
- **Local settings** — the keyboard is write-only, so the current state is
  stored in `~/.config/sk80/settings.json`.

## Requirements

- Linux with USB HID support
- Python 3.10 or newer
- [PyUSB](https://github.com/pyusb/pyusb) 1.2+
- [Pillow](https://python-pillow.org/) 9+
- [PySide6](https://doc.qt.io/qtforpython/) 6.4+ (GUI only)
- NumPy 1.23+ (optional, speeds up GIF conversion)

On Arch Linux, for example:

```bash
sudo pacman -S python-pyusb python-pillow pyside6 python-numpy
```

or with pip:

```bash
python3 -m pip install --user pyusb Pillow PySide6 numpy
```

If your distribution marks Python as externally managed (PEP 668), use the
distribution packages above or install the dependencies in a virtual
environment.

## Quick start

```bash
git clone https://github.com/BaylieBuffel/womier-sk80
cd womier-sk80
```

Run directly from the checkout:

```bash
./bin/sk80ctl status
./bin/sk80-gui
```

### Arch Linux

The `PKGBUILD` builds the wheel straight from the checkout:

```bash
makepkg -si
```

It installs `sk80ctl`, `sk80-gui`, the desktop entry and the udev rule, and
pulls `python-pyusb`, `python-pillow` and `pyside6` in with it.

### Anywhere else

Install the udev rule and launchers:

```bash
./install.sh
```

The installer copies `udev/99-womier-sk80.rules` to `/etc/udev/rules.d/`
unless the package already provides it, reloads udev, and symlinks `sk80ctl`
and `sk80-gui` into `~/.local/bin`.  **Unplug and reconnect the keyboard**
afterwards so the new permissions take effect.

If you prefer a Python package:

```bash
python3 -m pip install .
sk80ctl status
sk80-gui
```

### Device permissions

The keyboard exposes two useful interfaces:

| Interface | Purpose | Access |
|-----------|---------|--------|
| 3 | Configuration feature reports | libusb / PyUSB |
| 2 | LCD pixel data | `/dev/hidrawN` |

The included udev rule uses `TAG+="uaccess"` so the logged-in desktop user
gets access automatically.  On systems without systemd-logind's `uaccess`
support, edit the rule and use `GROUP="plugdev"` instead, then add your user
to that group.

`sk80ctl status` shows the detected LCD node.  If auto-detection fails but
you know the node, override it:

```bash
SK80_HIDRAW=/dev/hidraw10 ./bin/sk80ctl screen picture.png
```

## GUI

Launch with `./bin/sk80-gui` (or `sk80-gui` after installation).  The window
has five pages:

- **Lighting** — pick a mode, colour, brightness, speed and direction.
- **Per-key RGB** — select keys on the layout and paint them; presets and a
  brightness slider are included.
- **Key Mapping** — choose a physical key, then map it to a key, combo,
  multimedia action, mouse action or special function.
- **LCD Screen** — drag in an image/GIF (or use the file chooser), preview the
  animation, choose fit mode, and upload.
- **Clock** — see the current PC time and write it to the keyboard's RTC
  (the wired model may not display a clock page).

The status line at the bottom reports whether the keyboard is connected and
shows the result of the last operation.  Buttons are disabled while a USB
task is running, and progress is shown for LCD uploads.

Because the keyboard cannot report its current state, the GUI and CLI treat
`~/.config/sk80/settings.json` as the source of truth.  If you change
something with the keyboard's onboard shortcuts, the JSON may be stale;
re-apply the setting from the app to synchronise it.

## CLI

```bash
sk80ctl status
sk80ctl keys                  # list physical key names and indices
sk80ctl info                  # list modes, media keys, mouse actions, ...
```

### Lighting

```bash
# Static blue at brightness 4
sk80ctl lighting --mode static --color 0064ff --brightness 4

# Breathing pink, slower
sk80ctl lighting --mode breath --color ff00aa --speed 2

# Rainbow modes ignore the colour field
sk80ctl lighting --mode spectrum

# Turn the backlight off
sk80ctl lighting --off
```

Colours accept `RRGGBB`, `#RRGGBB`, short `RGB`, or a preset name such as
`red`, `green`, `blue`, `cyan`, `purple`, `pink`, `white`, `orange` or
`yellow`.  Mode names are case-insensitive; `sk80ctl info` prints the full
list.

### Per-key RGB

```bash
sk80ctl perkey --set esc=ff0000 --set a=00ff00 --set space=0064ff
sk80ctl perkey --all 202020
sk80ctl perkey --off escape
sk80ctl perkey --clear
sk80ctl perkey --brightness 3
```

`--set` and `--off` can be repeated.  The keyboard receives a complete
576-byte table on every call; keys not listed are turned off.

### Key remapping

```bash
# Make Insert act as Home
sk80ctl remap --set insert=home

# Make Caps Lock act as Escape
sk80ctl remap --set capslock=esc

# Modifier combo
sk80ctl remap --set f12=ctrl+c

# Multimedia and mouse actions
sk80ctl remap --set f11=media:volup
sk80ctl remap --set f10=media:mute
sk80ctl remap --set f9=mouse:lclick

# Special functions
sk80ctl remap --set f8=special:calculator

# Fn layer
sk80ctl remap --fn --set f7=media:play

# Inspect and reset
sk80ctl remap --list
sk80ctl remap --reset
sk80ctl remap --fn --reset
```

Available media targets: `play`, `stop`, `prev`, `next`, `volup`,
`voldown`, `mute`.  Mouse targets: `lclick`, `rclick`, `mclick`,
`scrollup`, `scrolldn`.  Special targets: `numlock`, `scrolllock`,
`capslock`, `insert`, `calculator`, `lockpc`, `alttab`, `system`.
A target can also be a key name such as `a`, `f11`, `home`, `pageup`, or a
combo such as `shift+tab`.

The firmware stores the remap table; the app cannot read it back.  Keep a
copy of your remaps in the settings file, or use `--list` before clearing.

### LCD screen

```bash
# Fill and crop to 160×96
sk80ctl screen picture.png

# Letterbox instead of cropping
sk80ctl screen picture.png --fit contain

# Animated GIF
sk80ctl screen animation.gif --slot 1

# Solid colour / black
sk80ctl screen --solid 0064ff
sk80ctl screen --black
```

The LCD is **160×96 pixels**, RGB565 little-endian.  A 240×135 image (used
by some other Aula/SONiX boards) will appear horizontally sheared.  Uploads
go to slot 1 by default; select the keyboard's picture/display mode with its
Fn shortcut to show the uploaded frame or animation.

The firmware stores each frame delay in 2 ms units, so individual frames are
limited to about 510 ms.  Very long GIFs can be slow to upload and exceed the
firmware's safe limit; the CLI and GUI warn above **141 frames**.

### Clock

```bash
sk80ctl clock
sk80ctl clock --set "2026-10-20 21:30:00"
```

The keyboard's clock is a separate RTC.  It does not follow the PC
automatically, so sync it after reconnecting, after a long power-off, or
after a timezone change.  There is no read-back command; the app can only
write the clock.

**Wired SK80 limitation:** Womier's S-K80 manual documents three OLED pages
— Boot, Home and Functions — and none of them shows a clock.  The clock
packet still matches the vendor's `DeviceDriver.exe` and writes the
keyboard's RTC (the SK80 Pro and some other firmware variants expose a time
display), but on the wired SK80 there may be no visible clock page to
confirm it.  The command is harmless and remains available for compatible
firmware/models.

### GUI from the CLI

```bash
sk80ctl gui
```

## Protocol notes

The SK80 uses the SONiX/Aula command set.  The implementation was validated
against a physical keyboard (`05ac:024f`, manufacturer `SONiX`, product
`Gaming Keyboard`).

- **Configuration**: USB interface 3, 64-byte HID feature reports.
  `SET_REPORT` is `bmRequestType=0x21`, `bRequest=0x09`, `wValue=0x0300`,
  `wIndex=3`; `GET_REPORT` is `0xA1`, `0x01`, `0x0300`, `3`.
- **Command pacing**: 35 ms between reports, matching the vendor's
  `cmd_delaytime`.
- **LCD**: USB interface 2, exposed through `hidraw`.  The buffer starts with
  a 256-byte header (frame count, per-frame delay in 2 ms units) followed by
  160×96 RGB565 little-endian frames (30,720 bytes each), padded to 4,096
  bytes.  One frame occupies eight 4 KiB pages.
- **Lighting**: `04 18` begin, `04 13` init, lighting data report, `04 02`
  apply, `04 f0` finalize.
- **Per-key**: LED-strip preamble, then `04 23` with a 576-byte table
  (`slot = light_index * 4`, bytes `[index, R, G, B]`).
- **Remap**: `04 11` normal or `04 27` Fn, then a 576-byte table
  (`slot = key_index * 4`, bytes `[action, p1, p2, p3]`).
- **Clock**: `04 28` with the date/time report, an `AA 55` trailer, and no
  finalize command.  The vendor's SK80 packet leaves the weekday field zero.
- **Write-only**: lighting, per-key colours, remaps and the clock cannot be
  read back.  That is why this project keeps a local JSON state file.

Key indices come from the vendor's `KeyboardLayout.xml`, which is bundled as
`sk80/data/KeyboardLayout.xml`.  The SK80 has 81 keys and no numpad.

## Troubleshooting

### “Womier SK80 not found”

- Check the cable and use a USB data port, not a charge-only port.
- `lsusb | grep -i 05ac` should show `05ac:024f`.
- Install the udev rule and replug the keyboard.
- If a rule is already installed, check it is still loaded:
  `udevadm control --reload-rules && udevadm trigger --subsystem-match=hidraw`.
- Two rules with the same name in `/etc/udev/rules.d/` and
  `/usr/lib/udev/rules.d/` shadow each other; the one in `/etc/` wins. Keep
  only the package's unless you are deliberately overriding it.
- Try `sudo ./bin/sk80ctl status` only as a diagnostic.  If that works but
  your normal user cannot connect, the udev permissions are the problem.

### LCD node not found / permission denied

- `sk80ctl status` prints the detected node.
- Check `ls -l /dev/hidraw*` and the ACL with `getfacl /dev/hidrawN`.
- Replug after installing the rule.
- Override detection with `SK80_HIDRAW=/dev/hidrawN`.
- Close any other program that has the hidraw node open.

### Upload succeeds but the LCD does not change

- Select the picture/display mode on the keyboard with its Fn shortcut.
- Confirm the source is 160×96 after conversion; do not use a 240×135
  template.
- Re-upload a simple solid colour to verify the data path.

### Remap does not take effect

- The keyboard stores the table; try unplugging and reconnecting.
- Remember that `--fn` edits the Fn layer, not the normal layer.
- Reset the layer with `sk80ctl remap --reset` (or `--fn --reset`).
- Avoid remapping the Fn key itself unless you have a recovery plan.

### Clock is wrong after a while

- The keyboard RTC does not track the PC.  Run `sk80ctl clock` again.
- There is no read-back, so the app cannot verify the result.
- On the wired SK80 the documented OLED pages (Boot, Home, Functions) do
  not include a clock.  If you cannot find a clock page, this is a firmware
  limitation rather than a failed sync; the RTC write still completes.

### GUI problems

- The GUI needs a working Qt platform plugin (Wayland or X11).
- On a tiling compositor the window may be tiled to the full screen; this is
  normal.  The layout also works when resized to about 1240×820.
- If the window is too small, use the compositor's floating/resize controls.

## Project layout

```
bin/sk80ctl              CLI launcher (run from checkout)
bin/sk80-gui             GUI launcher (run from checkout)
sk80/cli.py              argparse CLI
sk80/gui.py              PySide6 GUI
sk80/protocol.py         USB feature-report and LCD protocol
sk80/screen.py           160×96 RGB565 conversion and buffer builder
sk80/layout.py           KeyboardLayout.xml parser and key labels
sk80/constants.py        Modes, HID tables, remap actions
sk80/config.py           Persistent JSON settings
sk80/data/KeyboardLayout.xml
udev/99-womier-sk80.rules
install.sh               udev rule + launcher installer
PKGBUILD                 Arch package, built from this checkout
pyproject.toml
```

## Safety and limitations

- This is reverse-engineered software, not an official Womier product.
- Remapping keys can make the keyboard awkward to use.  Keep `sk80ctl`
  available and reset the layer if something goes wrong.
- The LCD firmware can corrupt its menu if it receives too many animation
  frames.  Stay at or below 141 frames unless you are prepared to recover.
- The keyboard is write-only; the app cannot detect changes made with the
  keyboard's onboard shortcuts.
- Tested with the SK80 on Linux.  Other Aula/SONiX keyboards may share parts
  of the protocol but are not guaranteed to work.

## Credits

Protocol details were derived from the vendor software and from the
SONiX/Aula keyboard protocol documentation used by the Aula F108 Pro
community implementation.  Womier and SK80 are trademarks of their
respective owners; this project is not affiliated with Womier.

## License

MIT — see [LICENSE](LICENSE).
