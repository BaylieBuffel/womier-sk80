#!/usr/bin/env bash
# Install the udev rule and user-facing launchers for the Womier SK80.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
RULE_SRC="$ROOT/udev/99-womier-sk80.rules"
RULE_DST="/etc/udev/rules.d/99-womier-sk80.rules"

echo "==> Checking Python dependencies"
python3 - <<'PY'
import importlib
import sys

missing = []
for module, package in (("usb", "pyusb"), ("PIL", "Pillow"), ("PySide6", "PySide6")):
    try:
        importlib.import_module(module)
    except Exception:
        missing.append(package)

if missing:
    print("Missing Python package(s): " + ", ".join(missing))
    print("Install them with:")
    print("  python3 -m pip install --user " + " ".join(missing))
    print("Or use your distribution's packages (python-pyusb, python-pillow, pyside6).")
    sys.exit(1)

print("Python dependencies are available.")
PY

echo "==> Installing udev rule"
# A file of the same name in /etc/ shadows the one the package installs in
# /usr/lib/, and then a fixed rule never reaches this machine.  When the
# package is installed, its rule is the one to keep.
if [[ -f /usr/lib/udev/rules.d/99-womier-sk80.rules ]]; then
    echo "    already provided by the womier-sk80 package; leaving it alone"
elif command -v sudo >/dev/null 2>&1; then
    sudo install -Dm644 "$RULE_SRC" "$RULE_DST"
else
    echo "sudo not found.  Copy this file manually as root:"
    echo "  $RULE_SRC -> $RULE_DST"
fi

# Reload whether or not a rule was copied: the package's rule needs this too,
# and the devices only pick up new permissions when their nodes are re-created.
if command -v sudo >/dev/null 2>&1; then
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=usb --subsystem-match=hidraw || true
else
    echo "Then run: udevadm control --reload-rules && udevadm trigger"
fi
echo

# The package installs both launchers into /usr/bin; a symlink here would
# only shadow a packaged upgrade with this checkout.
if command -v pacman >/dev/null 2>&1 && pacman -Q womier-sk80 >/dev/null 2>&1; then
    echo "==> The womier-sk80 package is installed; its launchers are used"
else
    echo "==> Installing launchers into $BIN_DIR"
    mkdir -p "$BIN_DIR"
    ln -sf "$ROOT/bin/sk80ctl" "$BIN_DIR/sk80ctl"
    ln -sf "$ROOT/bin/sk80-gui" "$BIN_DIR/sk80-gui"
fi

echo
echo "Done.  Unplug and reconnect the keyboard so the new permissions apply."
echo "Check the connection with:  sk80ctl status"
echo "Launch the GUI with:        sk80-gui"
