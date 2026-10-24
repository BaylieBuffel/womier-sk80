"""Small persistent settings store.

The keyboard is write-only: it cannot report its current lighting mode, key
colours or remap table.  The vendor software therefore keeps those settings in
a local database.  We do the same with a JSON file under
``$XDG_CONFIG_HOME/sk80/settings.json``.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

APP_NAME = "sk80"

DEFAULT_SETTINGS: dict[str, Any] = {
    "lighting": {
        "mode": 1,
        "color": [255, 0, 0],
        "brightness": 5,
        "speed": 5,
        "direction": 0,
        "colorful": False,
    },
    "per_key": {
        "brightness": 5,
        "colors": {},
    },
    "remap": {
        "normal": {},
        "fn": {},
    },
    "screen": {
        "fit": "cover",
        "last_path": "",
        "delay_ms": 1000,
    },
    "clock": {},
}


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / APP_NAME / "settings.json"


def _deep_merge(base: dict, extra: Mapping) -> dict:
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_path()
        self.data = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            _deep_merge(self.data, raw)
        self._normalise()

    def _normalise(self) -> None:
        lighting = self.data.setdefault("lighting", {})
        lighting["mode"] = int(lighting.get("mode", 1)) % 22
        color = lighting.get("color", [255, 0, 0])
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            color = [255, 0, 0]
        lighting["color"] = [max(0, min(255, int(c))) for c in color]
        lighting["brightness"] = max(0, min(5, int(lighting.get("brightness", 5))))
        lighting["speed"] = max(0, min(5, int(lighting.get("speed", 5))))
        lighting["direction"] = 1 if lighting.get("direction") else 0
        lighting["colorful"] = bool(lighting.get("colorful", False))

        per_key = self.data.setdefault("per_key", {})
        per_key["brightness"] = max(0, min(5, int(per_key.get("brightness", 5))))
        colors = per_key.get("colors", {})
        if not isinstance(colors, dict):
            colors = {}
        clean: dict[str, list[int]] = {}
        for key, value in colors.items():
            try:
                index = int(key)
                rgb = [max(0, min(255, int(c))) for c in value]
                if len(rgb) == 3 and 0 < index < 144:
                    clean[str(index)] = rgb
            except (TypeError, ValueError):
                continue
        per_key["colors"] = clean

        remap = self.data.setdefault("remap", {})
        for layer in ("normal", "fn"):
            table = remap.get(layer, {})
            if not isinstance(table, dict):
                table = {}
            cleaned: dict[str, list[int]] = {}
            for key, value in table.items():
                try:
                    index = int(key)
                    slot = [int(v) & 0xFF for v in value]
                    if len(slot) == 4 and 0 < index < 144:
                        cleaned[str(index)] = slot
                except (TypeError, ValueError):
                    continue
            remap[layer] = cleaned

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # -- convenience -------------------------------------------------------

    @property
    def lighting(self) -> dict:
        return self.data["lighting"]

    @property
    def per_key(self) -> dict:
        return self.data["per_key"]

    def colors(self) -> dict[int, tuple[int, int, int]]:
        result: dict[int, tuple[int, int, int]] = {}
        for key, value in self.per_key.get("colors", {}).items():
            result[int(key)] = tuple(value)  # type: ignore[assignment]
        return result

    def set_colors(self, colors: Mapping[int, tuple[int, int, int]]) -> None:
        self.per_key["colors"] = {
            str(index): [int(c) for c in rgb] for index, rgb in sorted(colors.items())
        }

    def remap_table(self, layer: str = "normal") -> dict[int, tuple[int, int, int, int]]:
        result: dict[int, tuple[int, int, int, int]] = {}
        for key, value in self.data["remap"].get(layer, {}).items():
            result[int(key)] = tuple(value)  # type: ignore[assignment]
        return result

    def set_remap_table(
        self, table: Mapping[int, tuple[int, int, int, int]], layer: str = "normal"
    ) -> None:
        self.data["remap"][layer] = {
            str(index): [int(v) for v in slot] for index, slot in sorted(table.items())
        }
