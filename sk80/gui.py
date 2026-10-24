"""PySide6 graphical interface for the Womier SK80."""

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image
from PySide6.QtCore import (
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__, constants as C, screen
from .config import Store
from .layout import KEYS, KEY_BY_INDEX
from .protocol import SK80, find_lcd_hidraw

# ---------------------------------------------------------------------------
# background tasks
# ---------------------------------------------------------------------------


def task_lighting(signals, cfg: dict):
    with SK80() as dev:
        dev.set_lighting(**cfg)
    return cfg


def task_per_key(signals, colors: dict[int, tuple[int, int, int]], brightness: int):
    with SK80() as dev:
        dev.set_per_key(colors, brightness=brightness)
    return len(colors)


def task_remap(signals, table: dict[int, tuple[int, int, int, int]], fn_layer: bool):
    with SK80() as dev:
        dev.set_remap(table, fn_layer=fn_layer)
    return len(table)


def task_clock(signals, when: datetime):
    with SK80() as dev:
        dev.set_clock(when)
    return when


def task_upload(signals, buffer: bytes, slot: int):
    with SK80() as dev:
        pages = dev.upload_screen(
            buffer, slot=slot, progress=lambda sent, total: signals.progress.emit(sent, total)
        )
    return pages


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)


class Worker(QRunnable):
    def __init__(self, fn: Callable):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(self.signals)
        except Exception as exc:  # noqa: BLE001 - reported in the UI
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.finished.emit(result)


class TaskRunner(QObject):
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, fn, on_done=None, on_error=None, on_progress=None) -> bool:
        if self._busy:
            return False
        worker = Worker(fn)
        if on_done is not None:
            worker.signals.finished.connect(on_done)
        if on_error is not None:
            worker.signals.failed.connect(on_error)
        if on_progress is not None:
            worker.signals.progress.connect(on_progress)
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        self._busy = True
        self.busyChanged.emit(True)
        self.pool.start(worker)
        return True

    @Slot()
    def _finished(self, *_args) -> None:
        self._busy = False
        self.busyChanged.emit(False)

    @Slot()
    def _failed(self, *_args) -> None:
        self._busy = False
        self.busyChanged.emit(False)


# ---------------------------------------------------------------------------
# helpers and small widgets
# ---------------------------------------------------------------------------


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


def contrast_text(color: QColor) -> str:
    return "#071018" if color.lightness() > 150 else "#ffffff"


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)


class SectionTitle(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


class LabeledSlider(QWidget):
    valueChanged = Signal(int)

    def __init__(self, label: str, minimum: int = 0, maximum: int = 5, value: int = 5, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.label = QLabel(label)
        self.label.setFixedWidth(78)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(1)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value_label = QLabel(str(value))
        self.value_label.setFixedWidth(22)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setObjectName("Muted")
        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._changed)

    def _changed(self, value: int) -> None:
        self.value_label.setText(str(value))
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(value)


class ColorButton(QPushButton):
    colorChanged = Signal(QColor)

    def __init__(self, color: QColor | tuple[int, int, int] | list[int] = (255, 0, 0), parent=None):
        super().__init__(parent)
        self._color = QColor(*color) if isinstance(color, (tuple, list)) else QColor(color)
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> QColor:
        return QColor(self._color)

    def setColor(self, color: QColor | tuple[int, int, int] | list[int]) -> None:
        self._color = QColor(*color) if isinstance(color, (tuple, list)) else QColor(color)
        self._refresh()
        self.colorChanged.emit(self.color())

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Choose colour")
        if chosen.isValid():
            self.setColor(chosen)

    def _refresh(self) -> None:
        text = self._color.name().upper()
        self.setText(text)
        self.setStyleSheet(
            "QPushButton {"
            f" background: {self._color.name()};"
            f" color: {contrast_text(self._color)};"
            " border: 1px solid rgba(255,255,255,0.18);"
            " border-radius: 8px; font-weight: 700; padding: 6px 12px;"
            "}"
            "QPushButton:hover { border: 1px solid #4cc2ff; }"
            "QPushButton:disabled { background: #171b24; color: #5b6478; }"
        )


class PresetButtons(QWidget):
    colorPicked = Signal(QColor)

    def __init__(self, columns: int = 9, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for index, (name, rgb) in enumerate(C.COLOR_PRESETS):
            red, green, blue = rgb
            button = QPushButton()
            button.setFixedSize(24, 24)
            button.setToolTip(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton {"
                f" background: rgb({red},{green},{blue});"
                " border-radius: 12px; border: 1px solid rgba(255,255,255,0.22);"
                "}"
                "QPushButton:hover { border: 2px solid #ffffff; }"
            )
            button.clicked.connect(
                lambda checked=False, c=QColor(red, green, blue): self.colorPicked.emit(c)
            )
            layout.addWidget(button, index // columns, index % columns)
        layout.setColumnStretch(columns, 1)


class KeyboardWidget(QWidget):
    """Draws the physical SK80 layout and supports painting or selection."""

    keyPainted = Signal(int, object)
    keySelected = Signal(object)

    def __init__(self, mode: str = "paint", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.colors: dict[int, QColor] = {}
        self.remapped: set[int] = set()
        self.selected = None
        self.current_color = QColor("#ff0000")
        self._painting = False
        self.setMinimumSize(440, 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(760, 300)

    def set_colors(self, colors: dict[int, QColor]) -> None:
        self.colors = {int(k): QColor(v) for k, v in colors.items()}
        self.update()

    def set_current_color(self, color: QColor) -> None:
        self.current_color = QColor(color)

    def set_selected(self, key) -> None:
        self.selected = key
        self.update()

    def set_remapped(self, light_indices: set[int]) -> None:
        self.remapped = set(light_indices)
        self.update()

    def _key_rects(self):
        if not KEYS:
            return []
        min_x = min(k.rect[0] for k in KEYS)
        max_x = max(k.rect[0] + k.rect[2] for k in KEYS)
        min_y = min(k.rect[1] for k in KEYS)
        max_y = max(k.rect[1] + k.rect[3] for k in KEYS)
        margin = 8.0
        scale = min(
            (self.width() - 2 * margin) / max(1, max_x - min_x),
            (self.height() - 2 * margin) / max(1, max_y - min_y),
        )
        offset_x = (self.width() - (max_x - min_x) * scale) / 2 - min_x * scale
        offset_y = (self.height() - (max_y - min_y) * scale) / 2 - min_y * scale
        result = []
        for key in KEYS:
            x, y, w, h = key.rect
            result.append(
                (
                    key,
                    QRectF(
                        x * scale + offset_x,
                        y * scale + offset_y,
                        w * scale,
                        h * scale,
                    ),
                )
            )
        return result

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for key, rect in self._key_rects():
            if rect.width() < 2 or rect.height() < 2:
                continue

            base = QColor("#232837")
            fill = QColor(base)
            text_color = QColor("#aeb7c9")
            pen = QPen(QColor("#2c3345"), 1.0)
            radius = max(3.0, min(6.0, rect.height() * 0.18))

            if self.mode == "paint":
                if key.light_index in self.colors:
                    fill = QColor(self.colors[key.light_index])
                    text_color = QColor(contrast_text(fill))
            else:
                if key.light_index in self.remapped:
                    fill = QColor("#2b2116")
                    text_color = QColor("#ffc27a")
                    pen = QPen(QColor("#e09a4a"), 1.8)
                if self.selected is not None and self.selected.light_index == key.light_index:
                    fill = QColor("#17354a")
                    text_color = QColor("#d9f4ff")
                    pen = QPen(QColor("#4cc2ff"), 2.0)

            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, radius, radius)

            font = QFont("Noto Sans", 8)
            font.setWeight(QFont.Weight.DemiBold)
            if rect.width() < 34:
                font.setPointSizeF(7.0)
            elif len(key.label) > 3:
                font.setPointSizeF(7.2)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, key.label)

        painter.end()

    def _hit(self, point: QPointF):
        for key, rect in reversed(self._key_rects()):
            if rect.contains(point):
                return key
        return None

    def mousePressEvent(self, event) -> None:
        key = self._hit(event.position())
        if key is None:
            return
        if event.button() == Qt.MouseButton.RightButton and self.mode == "paint":
            self.colors.pop(key.light_index, None)
            self.update()
            self.keyPainted.emit(key.light_index, None)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.mode == "select":
            self.selected = key
            self.update()
            self.keySelected.emit(key)
        else:
            self._painting = True
            self._paint(key)

    def mouseMoveEvent(self, event) -> None:
        if not self._painting or self.mode != "paint":
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        key = self._hit(event.position())
        if key is not None:
            current = self.colors.get(key.light_index)
            if current is None or current != self.current_color:
                self._paint(key)

    def mouseReleaseEvent(self, event) -> None:
        self._painting = False

    def _paint(self, key) -> None:
        color = QColor(self.current_color)
        self.colors[key.light_index] = color
        self.update()
        self.keyPainted.emit(key.light_index, color)


class LightingPreview(QWidget):
    """Small animated keyboard strip used as a live effect preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = 1
        self.color = QColor("#ff0000")
        self.colorful = False
        self.speed = 5
        self._phase = 0
        self.setMinimumHeight(118)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_config(self, mode: int, color: QColor, colorful: bool, speed: int) -> None:
        self.mode = int(mode)
        self.color = QColor(color)
        self.colorful = bool(colorful)
        self.speed = max(0, min(5, int(speed)))
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 1 + self.speed) % 100000
        if self.mode != 0:
            self.update()

    def _key_color(self, index: int, count: int) -> QColor:
        if self.mode == 0:
            return QColor("#20242f")
        if self.mode in (6, 8) or self.colorful:
            hue = int((index * 22 + self._phase * 3) % 360)
            return QColor.fromHsv(hue, 235, 255)
        if self.mode == 7:  # Breath
            color = QColor(self.color)
            alpha = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(self._phase / 8))
            color.setAlphaF(alpha)
            return color
        if self.mode in (2, 3):  # Single on / single off
            lit = int(self._phase / 8) % count
            return QColor(self.color) if index == lit else QColor("#20242f")
        if self.mode in (4, 5, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21):
            color = QColor(self.color)
            hue = (color.hsvHue() if color.hsvHue() >= 0 else 0)
            hue = (hue + index * 6 + self._phase * 2) % 360
            value = 150 + int(105 * (0.5 + 0.5 * math.sin(index * 0.7 + self._phase / 5)))
            return QColor.fromHsv(hue, 220, min(255, value))
        return QColor(self.color)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#151a25"))
        gradient.setColorAt(1.0, QColor("#0e1118"))
        painter.setPen(QPen(QColor("#232a3a"), 1.0))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 10, 10)

        font = QFont("Noto Sans", 9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#8a95aa"))
        painter.drawText(
            QRectF(16, 8, self.width() - 32, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            C.MODE_NAMES.get(self.mode, "Lighting"),
        )

        count = 16
        margin = 16.0
        gap = 5.0
        key_height = 32.0
        key_width = (self.width() - 2 * margin - gap * (count - 1)) / count
        y = self.height() / 2 - key_height / 2 + 12
        for index in range(count):
            x = margin + index * (key_width + gap)
            color = self._key_color(index, count)
            painter.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, y, key_width, key_height), 4, 4)

        painter.end()


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------


class LightingPage(QWidget):
    def __init__(self, store: Store, run_task: Callable, parent=None):
        super().__init__(parent)
        self.store = store
        self.run_task = run_task

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addWidget(
            PageHeader(
                "Lighting",
                "Choose a backlight effect, then tune its colour, brightness and speed.",
            )
        )

        content = QHBoxLayout()
        content.setSpacing(16)

        left = Card()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(10)
        left_layout.addWidget(SectionTitle("EFFECT"))
        self.mode_list = QListWidget()
        self.mode_list.setFixedWidth(236)
        self.mode_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.mode_list.setCursor(Qt.CursorShape.PointingHandCursor)
        for mode, name in C.LIGHTING_MODES:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, mode)
            self.mode_list.addItem(item)
        left_layout.addWidget(self.mode_list)
        content.addWidget(left, 0)

        right = QVBoxLayout()
        right.setSpacing(16)

        preview_card = Card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        self.preview = LightingPreview()
        preview_layout.addWidget(self.preview)
        right.addWidget(preview_card)

        controls = Card()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(18, 16, 18, 16)
        controls_layout.setSpacing(10)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Colour"))
        self.color_button = ColorButton(store.lighting["color"])
        self.color_button.setMinimumWidth(130)
        color_row.addWidget(self.color_button)
        color_row.addStretch(1)
        controls_layout.addLayout(color_row)

        self.presets = PresetButtons()
        controls_layout.addWidget(self.presets)

        self.rainbow = QCheckBox("Rainbow (ignore the selected colour)")
        controls_layout.addWidget(self.rainbow)
        controls_layout.addSpacing(4)

        self.brightness = LabeledSlider("Brightness", 0, 5, store.lighting["brightness"])
        self.speed = LabeledSlider("Speed", 0, 5, store.lighting["speed"])
        controls_layout.addWidget(self.brightness)
        controls_layout.addWidget(self.speed)

        direction_row = QHBoxLayout()
        direction_row.addWidget(QLabel("Direction"))
        self.direction = QComboBox()
        for value, name in C.DIRECTIONS:
            self.direction.addItem(name, value)
        direction_row.addWidget(self.direction, 1)
        controls_layout.addLayout(direction_row)
        controls_layout.addSpacing(6)

        buttons = QHBoxLayout()
        self.apply_btn = QPushButton("Apply lighting")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.setProperty("busyDisable", True)
        self.apply_btn.setMinimumHeight(36)
        self.off_btn = QPushButton("Turn off")
        self.off_btn.setProperty("busyDisable", True)
        buttons.addWidget(self.apply_btn, 1)
        buttons.addWidget(self.off_btn)
        controls_layout.addLayout(buttons)

        right.addWidget(controls)
        right.addStretch(1)
        content.addLayout(right, 1)
        root.addLayout(content, 1)

        self.mode_list.currentRowChanged.connect(self._on_mode)
        self.color_button.colorChanged.connect(self._on_color)
        self.presets.colorPicked.connect(self.color_button.setColor)
        self.rainbow.toggled.connect(self._update_preview)
        self.brightness.valueChanged.connect(self._update_preview)
        self.speed.valueChanged.connect(self._update_preview)
        self.direction.currentIndexChanged.connect(self._update_preview)
        self.apply_btn.clicked.connect(self._apply)
        self.off_btn.clicked.connect(self._turn_off)

        self.mode_list.setCurrentRow(store.lighting["mode"])
        self.rainbow.setChecked(store.lighting["colorful"])
        self.direction.setCurrentIndex(store.lighting["direction"])
        self._on_mode(self.mode_list.currentRow())

    @property
    def mode(self) -> int:
        item = self.mode_list.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else 1

    def _on_color(self, _color: QColor) -> None:
        self._update_preview()

    def _on_mode(self, row: int) -> None:
        if row < 0:
            return
        mode = self.mode
        color_enabled = mode not in (0, 6, 8)
        self.color_button.setEnabled(color_enabled)
        self.presets.setEnabled(color_enabled)
        self.rainbow.setEnabled(color_enabled)
        self.brightness.setEnabled(mode != 0)
        self.speed.setEnabled(mode != 0)
        self.direction.setEnabled(mode != 0)
        if mode in (6, 8):
            self.rainbow.setChecked(True)
        self._update_preview()

    def _update_preview(self, *_args) -> None:
        self.preview.set_config(
            self.mode,
            self.color_button.color(),
            self.rainbow.isChecked(),
            self.brightness.value(),
        )

    def _config(self) -> dict:
        color = self.color_button.color()
        mode = self.mode
        return {
            "mode": mode,
            "r": color.red(),
            "g": color.green(),
            "b": color.blue(),
            "brightness": self.brightness.value(),
            "speed": self.speed.value(),
            "direction": self.direction.currentData() or 0,
            "colorful": self.rainbow.isChecked() or mode in (6, 8),
        }

    def _apply(self) -> None:
        cfg = self._config()
        self.run_task(
            lambda signals: task_lighting(signals, cfg),
            on_done=lambda _result: self._applied(cfg),
            message="Applying lighting…",
        )

    def _applied(self, cfg: dict) -> None:
        light = self.store.lighting
        light["mode"] = cfg["mode"]
        light["color"] = [cfg["r"], cfg["g"], cfg["b"]]
        light["brightness"] = cfg["brightness"]
        light["speed"] = cfg["speed"]
        light["direction"] = cfg["direction"]
        light["colorful"] = cfg["colorful"]
        self.store.save()
        window = self.window()
        if hasattr(window, "show_status"):
            window.show_status(
                f"Applied {C.MODE_NAMES.get(cfg['mode'], cfg['mode'])} lighting."
            )

    def _turn_off(self) -> None:
        self.mode_list.setCurrentRow(0)
        self._apply()


class PerKeyPage(QWidget):
    def __init__(self, store: Store, run_task: Callable, parent=None):
        super().__init__(parent)
        self.store = store
        self.run_task = run_task
        self.colors = {
            index: QColor(*rgb) for index, rgb in store.colors().items()
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addWidget(
            PageHeader(
                "Per-key RGB",
                "Paint individual keys. Left-click or drag to paint, right-click to turn a key off.",
            )
        )

        toolbar = Card()
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 14, 16, 14)
        toolbar_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Paint colour"))
        default_color = QColor(*store.lighting["color"])
        self.color_button = ColorButton(default_color)
        self.color_button.setMinimumWidth(120)
        top_row.addWidget(self.color_button)
        self.presets = PresetButtons()
        top_row.addWidget(self.presets, 1)
        toolbar_layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        self.brightness = LabeledSlider("Brightness", 0, 5, store.per_key["brightness"])
        bottom_row.addWidget(self.brightness, 1)
        self.fill_btn = QPushButton("Fill all")
        self.clear_btn = QPushButton("Clear")
        self.apply_btn = QPushButton("Apply to keyboard")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.setProperty("busyDisable", True)
        bottom_row.addWidget(self.fill_btn)
        bottom_row.addWidget(self.clear_btn)
        bottom_row.addWidget(self.apply_btn)
        toolbar_layout.addLayout(bottom_row)
        root.addWidget(toolbar)

        keyboard_card = Card()
        keyboard_layout = QVBoxLayout(keyboard_card)
        keyboard_layout.setContentsMargins(14, 12, 14, 12)
        self.keyboard = KeyboardWidget("paint")
        self.keyboard.set_colors(self.colors)
        self.keyboard.set_current_color(default_color)
        keyboard_layout.addWidget(self.keyboard, 1)
        root.addWidget(keyboard_card, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("Muted")
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        hint = QLabel("Changes are stored locally until you apply them.")
        hint.setObjectName("MutedSmall")
        footer.addWidget(hint)
        root.addLayout(footer)

        self.color_button.colorChanged.connect(self.keyboard.set_current_color)
        self.presets.colorPicked.connect(self.color_button.setColor)
        self.keyboard.keyPainted.connect(self._painted)
        self.fill_btn.clicked.connect(self._fill_all)
        self.clear_btn.clicked.connect(self._clear)
        self.apply_btn.clicked.connect(self._apply)
        self._update_count()

    def _painted(self, index: int, color) -> None:
        if color is None:
            self.colors.pop(index, None)
        else:
            self.colors[index] = QColor(color)
        self._update_count()

    def _update_count(self) -> None:
        count = len(self.colors)
        self.count_label.setText(f"{count} key{'s' if count != 1 else ''} painted")

    def _fill_all(self) -> None:
        color = self.color_button.color()
        for key in KEYS:
            self.colors[key.light_index] = QColor(color)
        self.keyboard.set_colors(self.colors)
        self._update_count()

    def _clear(self) -> None:
        self.colors.clear()
        self.keyboard.set_colors(self.colors)
        self._update_count()

    def _apply(self) -> None:
        colors = {
            index: (color.red(), color.green(), color.blue())
            for index, color in self.colors.items()
        }
        brightness = self.brightness.value()
        self.run_task(
            lambda signals: task_per_key(signals, colors, brightness),
            on_done=lambda _result: self._applied(colors, brightness),
            message="Applying per-key colours…",
        )

    def _applied(self, colors: dict, brightness: int) -> None:
        self.store.set_colors(colors)
        self.store.per_key["brightness"] = brightness
        self.store.save()
        window = self.window()
        if hasattr(window, "show_status"):
            window.show_status(f"Applied per-key colours to {len(colors)} key(s).")


class KeymapPage(QWidget):
    def __init__(self, store: Store, run_task: Callable, parent=None):
        super().__init__(parent)
        self.store = store
        self.run_task = run_task
        self.tables = {
            "normal": dict(store.remap_table("normal")),
            "fn": dict(store.remap_table("fn")),
        }
        self.layer = "normal"
        self.selected_key = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        root.addWidget(
            PageHeader(
                "Key Mapping",
                "Remap a physical key to a different key, shortcut, multimedia control or mouse action.",
            )
        )

        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("Layer"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItem("Normal layer", "normal")
        self.layer_combo.addItem("Fn layer", "fn")
        layer_row.addWidget(self.layer_combo)
        self.layer_hint = QLabel("Normal-layer remaps apply during regular typing.")
        self.layer_hint.setObjectName("MutedSmall")
        layer_row.addWidget(self.layer_hint, 1)
        root.addLayout(layer_row)

        content = QHBoxLayout()
        content.setSpacing(16)

        left = Card()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 12)
        left_layout.setSpacing(8)
        left_layout.addWidget(SectionTitle("SELECT A KEY"))
        self.keyboard = KeyboardWidget("select")
        left_layout.addWidget(self.keyboard, 1)
        legend = QLabel("Orange outline = remapped   ·   Blue outline = selected")
        legend.setObjectName("MutedSmall")
        left_layout.addWidget(legend)
        content.addWidget(left, 4)

        right = Card()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 16, 18, 16)
        right_layout.setSpacing(9)

        self.key_title = QLabel("Select a key")
        self.key_title.setObjectName("KeyTitle")
        right_layout.addWidget(self.key_title)
        self.current_label = QLabel("Click a key on the left to edit its remap.")
        self.current_label.setObjectName("Muted")
        self.current_label.setWordWrap(True)
        right_layout.addWidget(self.current_label)

        right_layout.addWidget(SectionTitle("ACTION"))
        self.type_combo = QComboBox()
        self.type_combo.addItem("Disabled (default)", C.ACTION_NONE)
        self.type_combo.addItem("Key / Combo", C.ACTION_KEY)
        self.type_combo.addItem("Multimedia", C.ACTION_CONSUMER)
        self.type_combo.addItem("Mouse", C.ACTION_MOUSE)
        self.type_combo.addItem("Special", C.ACTION_SPECIAL)
        right_layout.addWidget(self.type_combo)

        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(150)

        key_page = QWidget()
        key_layout = QVBoxLayout(key_page)
        key_layout.setContentsMargins(0, 4, 0, 0)
        key_layout.setSpacing(7)
        key_layout.addWidget(QLabel("Target key"))
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.target_combo.addItem("None (modifier only)", 0)
        for name, code in sorted(
            C.HID_KEYS.items(), key=lambda item: C.hid_key_label(item[0]).lower()
        ):
            self.target_combo.addItem(C.hid_key_label(name), code)
        completer = self.target_combo.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
        key_layout.addWidget(self.target_combo)

        mod_grid = QGridLayout()
        mod_grid.setHorizontalSpacing(12)
        mod_grid.setVerticalSpacing(4)
        self.mod_checks: dict[str, QCheckBox] = {}
        labels = {
            "Ctrl": "Ctrl",
            "Shift": "Shift",
            "Alt": "Alt",
            "Win": "Win",
            "RCtrl": "R.Ctrl",
            "RShift": "R.Shift",
            "RAlt": "R.Alt",
            "RWin": "R.Win",
        }
        for index, (name, _bit) in enumerate(C.MODIFIERS):
            check = QCheckBox(labels[name])
            self.mod_checks[name] = check
            mod_grid.addWidget(check, index // 4, index % 4)
        key_layout.addLayout(mod_grid)
        hint = QLabel("Hold modifiers and a target key to create a shortcut, e.g. Ctrl + C.")
        hint.setObjectName("MutedSmall")
        hint.setWordWrap(True)
        key_layout.addWidget(hint)
        self.stack.addWidget(key_page)

        media_page = QWidget()
        media_layout = QVBoxLayout(media_page)
        media_layout.setContentsMargins(0, 4, 0, 0)
        media_layout.addWidget(QLabel("Multimedia action"))
        self.media_combo = QComboBox()
        for name, code in C.CONSUMER_KEYS.items():
            self.media_combo.addItem(C.CONSUMER_LABELS[name], code)
        media_layout.addWidget(self.media_combo)
        media_layout.addStretch(1)
        self.stack.addWidget(media_page)

        mouse_page = QWidget()
        mouse_layout = QVBoxLayout(mouse_page)
        mouse_layout.setContentsMargins(0, 4, 0, 0)
        mouse_layout.addWidget(QLabel("Mouse action"))
        self.mouse_combo = QComboBox()
        for name in C.MOUSE_ACTIONS:
            self.mouse_combo.addItem(C.MOUSE_LABELS[name], name)
        mouse_layout.addWidget(self.mouse_combo)
        mouse_layout.addStretch(1)
        self.stack.addWidget(mouse_page)

        special_page = QWidget()
        special_layout = QVBoxLayout(special_page)
        special_layout.setContentsMargins(0, 4, 0, 0)
        special_layout.addWidget(QLabel("Special function"))
        self.special_combo = QComboBox()
        for name in C.SPECIAL_FUNCTIONS:
            self.special_combo.addItem(C.SPECIAL_LABELS[name], name)
        special_layout.addWidget(self.special_combo)
        special_layout.addStretch(1)
        self.stack.addWidget(special_page)

        right_layout.addWidget(self.stack)

        edit_buttons = QHBoxLayout()
        self.set_btn = QPushButton("Set remap")
        self.set_btn.setObjectName("Primary")
        self.remove_btn = QPushButton("Remove")
        edit_buttons.addWidget(self.set_btn, 1)
        edit_buttons.addWidget(self.remove_btn)
        right_layout.addLayout(edit_buttons)

        right_layout.addWidget(SectionTitle("SAVED REMAPS"))
        self.remap_list = QListWidget()
        self.remap_list.setMaximumHeight(130)
        self.remap_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        right_layout.addWidget(self.remap_list)

        apply_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply remaps")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.setProperty("busyDisable", True)
        self.reset_btn = QPushButton("Reset layer")
        self.reset_btn.setObjectName("Danger")
        self.reset_btn.setProperty("busyDisable", True)
        apply_row.addWidget(self.apply_btn, 1)
        apply_row.addWidget(self.reset_btn)
        right_layout.addLayout(apply_row)
        content.addWidget(right, 3)

        root.addLayout(content, 1)

        self.keyboard.keySelected.connect(self._select_key)
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.set_btn.clicked.connect(self._set_remap)
        self.remove_btn.clicked.connect(self._remove_remap)
        self.apply_btn.clicked.connect(self._apply)
        self.reset_btn.clicked.connect(self._reset)
        self.remap_list.itemClicked.connect(self._list_clicked)

        self._type_changed(0)
        self._refresh_list()
        self._update_highlights()

    def _type_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(max(0, index - 1))

    def _select_key(self, key) -> None:
        self.selected_key = key
        self.keyboard.set_selected(key)
        self.key_title.setText(f"{key.label}  ·  {key.name}")
        slot = self.tables[self.layer].get(key.key_index)
        self._load_slot(slot)
        self.current_label.setText(
            describe_slot(slot) if slot else "No remap — the key keeps its default behavior."
        )

    def _load_slot(self, slot) -> None:
        if not slot or slot[0] == C.ACTION_NONE:
            self.type_combo.setCurrentIndex(0)
            return
        action = slot[0]
        if action == C.ACTION_KEY:
            self.type_combo.setCurrentIndex(1)
            p1, p2 = slot[1], slot[2]
            for name, bit in C.MODIFIERS:
                self.mod_checks[name].setChecked(bool(p1 & bit))
            index = self.target_combo.findData(p2)
            if index >= 0:
                self.target_combo.setCurrentIndex(index)
            else:
                self.target_combo.setEditText(f"0x{p2:02x}")
        elif action == C.ACTION_CONSUMER:
            self.type_combo.setCurrentIndex(2)
            index = self.media_combo.findData(slot[1])
            if index >= 0:
                self.media_combo.setCurrentIndex(index)
        elif action == C.ACTION_MOUSE:
            self.type_combo.setCurrentIndex(3)
            for name, params in C.MOUSE_ACTIONS.items():
                if params == tuple(slot[1:4]):
                    index = self.mouse_combo.findData(name)
                    if index >= 0:
                        self.mouse_combo.setCurrentIndex(index)
                    break
        elif action == C.ACTION_SPECIAL:
            self.type_combo.setCurrentIndex(4)
            for name, params in C.SPECIAL_FUNCTIONS.items():
                if params == tuple(slot[1:3]):
                    index = self.special_combo.findData(name)
                    if index >= 0:
                        self.special_combo.setCurrentIndex(index)
                    break
        else:
            self.type_combo.setCurrentIndex(0)

    def _mod_mask(self) -> int:
        mask = 0
        for name, bit in C.MODIFIERS:
            if self.mod_checks[name].isChecked():
                mask |= bit
        return mask

    def _target_code(self) -> int:
        text = self.target_combo.currentText().strip()
        index = self.target_combo.currentIndex()
        data = self.target_combo.currentData()
        if (
            data is not None
            and 0 <= index < self.target_combo.count()
            and text == self.target_combo.itemText(index).strip()
        ):
            return int(data)
        lower = text.lower()
        if lower in C.HID_KEYS:
            return C.HID_KEYS[lower]
        for name, code in C.HID_KEYS.items():
            if C.hid_key_label(name).lower() == lower:
                return code
        raise ValueError(f"Unknown target key: {text}")

    def _set_remap(self) -> None:
        if self.selected_key is None:
            QMessageBox.information(self, "SK80", "Select a key on the keyboard first.")
            return
        action = int(self.type_combo.currentData())
        index = self.selected_key.key_index
        table = self.tables[self.layer]

        if action == C.ACTION_NONE:
            table.pop(index, None)
        elif action == C.ACTION_KEY:
            try:
                target = self._target_code()
            except ValueError as exc:
                QMessageBox.warning(self, "SK80", str(exc))
                return
            mask = self._mod_mask()
            if target == 0 and mask == 0:
                table.pop(index, None)
            else:
                table[index] = (C.ACTION_KEY, mask, target, 0)
        elif action == C.ACTION_CONSUMER:
            table[index] = (C.ACTION_CONSUMER, int(self.media_combo.currentData()), 0, 0)
        elif action == C.ACTION_MOUSE:
            name = self.mouse_combo.currentData()
            p1, p2, p3 = C.MOUSE_ACTIONS[name]
            table[index] = (C.ACTION_MOUSE, p1, p2, p3)
        elif action == C.ACTION_SPECIAL:
            name = self.special_combo.currentData()
            p1, p2 = C.SPECIAL_FUNCTIONS[name]
            table[index] = (C.ACTION_SPECIAL, p1, p2, 0)

        self._after_edit()
        self._select_key(self.selected_key)

    def _remove_remap(self) -> None:
        if self.selected_key is None:
            return
        self.tables[self.layer].pop(self.selected_key.key_index, None)
        self._after_edit()
        self.type_combo.setCurrentIndex(0)
        self.current_label.setText("No remap — the key keeps its default behavior.")

    def _after_edit(self) -> None:
        self.store.set_remap_table(self.tables[self.layer], self.layer)
        self.store.save()
        self._refresh_list()
        self._update_highlights()

    def _refresh_list(self) -> None:
        self.remap_list.clear()
        table = self.tables[self.layer]
        if not table:
            item = QListWidgetItem("No remaps on this layer")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.remap_list.addItem(item)
            return
        for key_index, slot in sorted(table.items()):
            key = KEY_BY_INDEX.get(key_index)
            name = key.label if key else str(key_index)
            item = QListWidgetItem(f"{name}   →   {describe_slot(slot)}")
            item.setData(Qt.ItemDataRole.UserRole, key_index)
            self.remap_list.addItem(item)

    def _list_clicked(self, item: QListWidgetItem) -> None:
        key_index = item.data(Qt.ItemDataRole.UserRole)
        if key_index is None:
            return
        key = KEY_BY_INDEX.get(int(key_index))
        if key is not None:
            self.keyboard.set_selected(key)
            self._select_key(key)

    def _update_highlights(self) -> None:
        indices = set()
        for key_index in self.tables[self.layer]:
            key = KEY_BY_INDEX.get(key_index)
            if key is not None:
                indices.add(key.light_index)
        self.keyboard.set_remapped(indices)

    def _layer_changed(self, _index: int) -> None:
        self.layer = self.layer_combo.currentData()
        if self.layer == "fn":
            self.layer_hint.setText("Fn-layer remaps apply while the Fn key is held.")
        else:
            self.layer_hint.setText("Normal-layer remaps apply during regular typing.")
        self._update_highlights()
        self._refresh_list()
        if self.selected_key is not None:
            self._select_key(self.selected_key)

    def _apply(self) -> None:
        layer = self.layer
        table = dict(self.tables[layer])
        self.run_task(
            lambda signals: task_remap(signals, table, layer == "fn"),
            on_done=lambda _result: self._applied(table, layer),
            message=f"Applying {layer} remaps…",
        )

    def _applied(self, table: dict, layer: str) -> None:
        self.store.set_remap_table(table, layer)
        self.store.save()
        window = self.window()
        if hasattr(window, "show_status"):
            window.show_status(
                f"Applied {len(table)} remap(s) to the {'Fn' if layer == 'fn' else 'normal'} layer."
            )

    def _reset(self) -> None:
        table = self.tables[self.layer]
        if not table:
            return
        answer = QMessageBox.question(
            self,
            "Reset layer",
            f"Clear all remaps on the {'Fn' if self.layer == 'fn' else 'normal'} layer?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        table.clear()
        self._after_edit()
        self.type_combo.setCurrentIndex(0)


class ScreenPage(QWidget):
    def __init__(self, store: Store, run_task: Callable, parent=None):
        super().__init__(parent)
        self.store = store
        self.run_task = run_task
        self.frames: list[tuple[Image.Image, int]] = []
        self.source_path: Optional[Path] = None
        self.frame_index = 0
        self._playing = True
        self.setAcceptDrops(True)

        self.play_timer = QTimer(self)
        self.play_timer.setSingleShot(True)
        self.play_timer.timeout.connect(self._next_frame)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addWidget(
            PageHeader(
                "LCD Screen",
                "Upload a 160×96 image or animated GIF to the keyboard's LCD.",
            )
        )

        content = QHBoxLayout()
        content.setSpacing(16)

        preview_card = Card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(10)
        preview_layout.addWidget(SectionTitle("PREVIEW"))
        self.preview = QLabel("Drop an image or GIF here")
        self.preview.setObjectName("ScreenPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(480, 288)
        self.preview.setStyleSheet(
            "QLabel#ScreenPreview { background: #05070a; border: 1px solid #232a3a;"
            " border-radius: 8px; color: #596479; }"
        )
        preview_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)

        slider_row = QHBoxLayout()
        self.play_btn = QPushButton("Pause")
        self.play_btn.setFixedWidth(76)
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(0, 0)
        self.play_btn.setEnabled(False)
        self.frame_slider.setEnabled(False)
        slider_row.addWidget(self.play_btn)
        slider_row.addWidget(self.frame_slider, 1)
        preview_layout.addLayout(slider_row)
        self.frame_label = QLabel("No image loaded")
        self.frame_label.setObjectName("Muted")
        preview_layout.addWidget(self.frame_label)
        preview_layout.addStretch(1)
        content.addWidget(preview_card, 1)

        source_card = Card()
        source_layout = QVBoxLayout(source_card)
        source_layout.setContentsMargins(18, 16, 18, 16)
        source_layout.setSpacing(10)

        source_layout.addWidget(SectionTitle("SOURCE"))
        self.file_btn = QPushButton("Choose image or GIF…")
        source_layout.addWidget(self.file_btn)
        self.path_label = QLabel("You can also drag a file onto this window.")
        self.path_label.setObjectName("MutedSmall")
        self.path_label.setWordWrap(True)
        source_layout.addWidget(self.path_label)

        fit_row = QHBoxLayout()
        fit_row.addWidget(QLabel("Fit"))
        self.fit_combo = QComboBox()
        self.fit_combo.addItem("Fill & crop", "cover")
        self.fit_combo.addItem("Fit (letterbox)", "contain")
        self.fit_combo.addItem("Stretch", "stretch")
        fit_row.addWidget(self.fit_combo, 1)
        source_layout.addLayout(fit_row)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Static delay"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(100, 10000)
        self.delay_spin.setSingleStep(100)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setValue(int(store.data["screen"].get("delay_ms", 1000)))
        delay_row.addWidget(self.delay_spin, 1)
        source_layout.addLayout(delay_row)

        self.info_label = QLabel("0 frames")
        self.info_label.setObjectName("Muted")
        source_layout.addWidget(self.info_label)
        self.warn_label = QLabel("")
        self.warn_label.setObjectName("Warn")
        self.warn_label.setWordWrap(True)
        source_layout.addWidget(self.warn_label)
        source_layout.addStretch(1)

        self.upload_btn = QPushButton("Upload to LCD")
        self.upload_btn.setObjectName("Primary")
        self.upload_btn.setProperty("busyDisable", True)
        self.upload_btn.setMinimumHeight(38)
        self.black_btn = QPushButton("Send black frame")
        self.black_btn.setProperty("busyDisable", True)
        source_layout.addWidget(self.upload_btn)
        source_layout.addWidget(self.black_btn)
        content.addWidget(source_card, 0)

        root.addLayout(content, 1)

        self.file_btn.clicked.connect(self._choose_file)
        self.fit_combo.currentIndexChanged.connect(self._reload)
        self.delay_spin.valueChanged.connect(self._delay_changed)
        self.play_btn.clicked.connect(self._toggle_play)
        self.frame_slider.valueChanged.connect(self._scrub)
        self.upload_btn.clicked.connect(self._upload)
        self.black_btn.clicked.connect(self._send_black)

        last = store.data["screen"].get("last_path", "")
        if last and Path(last).is_file():
            self.path_label.setText(last)

    def _fit(self) -> str:
        return self.fit_combo.currentData() or "cover"

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file():
                self.load_path(path)
                event.acceptProposedAction()
                return

    def _choose_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose an image or GIF",
            str(self.source_path.parent if self.source_path else Path.home()),
            "Images and animations (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.apng);;All files (*)",
        )
        if path:
            self.load_path(Path(path))

    def load_path(self, path: Path) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            frames = screen.load_frames(
                path, fit=self._fit(), default_delay_ms=self.delay_spin.value()
            )
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "SK80", f"Could not load {path.name}:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.source_path = path
        self.frames = frames
        self.frame_index = 0
        self.path_label.setText(str(path))
        self.store.data["screen"]["last_path"] = str(path)
        self.store.save()
        self._update_info()
        self._show_frame()
        self._start_playback()

    def _reload(self, *_args) -> None:
        if self.source_path is not None and self.source_path.is_file():
            self.load_path(self.source_path)

    def _delay_changed(self, value: int) -> None:
        self.store.data["screen"]["delay_ms"] = int(value)
        if len(self.frames) == 1:
            image = self.frames[0][0]
            self.frames = [(image, int(value))]
            self._update_info()

    def _update_info(self) -> None:
        if not self.frames:
            self.info_label.setText("0 frames")
            self.warn_label.setText("")
            return
        total = screen.total_duration(self.frames)
        self.info_label.setText(
            f"{len(self.frames)} frame(s) · {total} ms · "
            f"{C.LCD_WIDTH}×{C.LCD_HEIGHT} RGB565"
        )
        if len(self.frames) > C.LCD_SAFE_FRAMES:
            self.warn_label.setText(
                f"⚠ {len(self.frames)} frames may exceed the firmware's safe limit "
                f"({C.LCD_SAFE_FRAMES}). The keyboard menu can become corrupted."
            )
        elif len(self.frames) > 1:
            self.warn_label.setText("Animated uploads can take a while.")
        else:
            self.warn_label.setText("")

    def _start_playback(self) -> None:
        self.play_timer.stop()
        self._playing = True
        self.frame_slider.setEnabled(bool(self.frames))
        if len(self.frames) <= 1:
            self.play_btn.setText("Static")
            self.play_btn.setEnabled(False)
            return
        self.play_btn.setEnabled(True)
        self.play_btn.setText("Pause")
        self.play_timer.start(max(20, self.frames[self.frame_index][1]))

    def _next_frame(self) -> None:
        if not self._playing or len(self.frames) <= 1:
            return
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self._show_frame()
        self.play_timer.start(max(20, self.frames[self.frame_index][1]))

    def _show_frame(self) -> None:
        if not self.frames:
            return
        self.frame_index %= len(self.frames)
        image, delay = self.frames[self.frame_index]
        pixmap = pil_to_pixmap(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setRange(0, len(self.frames) - 1)
        self.frame_slider.setValue(self.frame_index)
        self.frame_slider.blockSignals(False)
        self.frame_label.setText(
            f"Frame {self.frame_index + 1} / {len(self.frames)}   ·   {delay} ms"
        )

    def _toggle_play(self) -> None:
        if len(self.frames) <= 1:
            return
        self._playing = not self._playing
        if self._playing:
            self.play_btn.setText("Pause")
            self.play_timer.start(max(20, self.frames[self.frame_index][1]))
        else:
            self.play_btn.setText("Play")
            self.play_timer.stop()

    def _scrub(self, value: int) -> None:
        if not self.frames:
            return
        self._playing = False
        self.play_btn.setText("Play")
        self.play_timer.stop()
        self.frame_index = max(0, min(value, len(self.frames) - 1))
        self._show_frame()

    def _upload(self) -> None:
        if not self.frames:
            QMessageBox.information(self, "SK80", "Load an image or GIF first.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            buffer = screen.build_buffer(self.frames)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "SK80", f"Could not build the LCD buffer:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.run_task(
            lambda signals: task_upload(signals, buffer, 1),
            on_done=self._uploaded,
            on_progress=self._upload_progress,
            message="Uploading image to the LCD…",
        )

    def _upload_progress(self, sent: int, total: int) -> None:
        self.info_label.setText(f"Uploading page {sent} / {total}…")

    def _uploaded(self, pages: int) -> None:
        self._update_info()
        window = self.window()
        if hasattr(window, "show_status"):
            window.show_status(f"Uploaded {pages} page(s) to the LCD.")

    def _send_black(self) -> None:
        frames = screen.solid_frames((0, 0, 0), delay_ms=1000)
        buffer = screen.build_buffer(frames)
        self.run_task(
            lambda signals: task_upload(signals, buffer, 1),
            on_done=lambda pages: self._uploaded(pages),
            message="Sending black frame…",
        )


class ClockPage(QWidget):
    def __init__(self, store: Store, run_task: Callable, parent=None):
        super().__init__(parent)
        self.store = store
        self.run_task = run_task

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addWidget(
            PageHeader(
                "Clock",
                "Write the keyboard's real-time clock with your computer's time.",
            )
        )

        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 26, 28, 26)
        card_layout.setSpacing(8)

        self.time_label = QLabel("00:00:00")
        self.time_label.setObjectName("BigClock")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_label = QLabel("")
        self.date_label.setObjectName("Muted")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.time_label)
        card_layout.addWidget(self.date_label)
        card_layout.addSpacing(18)

        self.sync_btn = QPushButton("Sync keyboard clock")
        self.sync_btn.setObjectName("Primary")
        self.sync_btn.setProperty("busyDisable", True)
        self.sync_btn.setMinimumHeight(40)
        card_layout.addWidget(self.sync_btn)

        self.last_label = QLabel("Not synced yet")
        self.last_label.setObjectName("MutedSmall")
        self.last_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.last_label)
        root.addWidget(card)

        info = Card()
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(20, 16, 20, 16)
        info_layout.addWidget(SectionTitle("ABOUT THE LCD CLOCK"))
        text = QLabel(
            "The clock is stored inside the keyboard and does not follow your PC "
            "automatically. Sync it after reconnecting the keyboard, after a long "
            "power-off, or when the time zone changes. The protocol sends the date "
            "and time; there is no read-back command.\n\n"
            "Note: the wired SK80's documented OLED pages are Boot, Home and "
            "Functions; they do not include a clock screen. This command still "
            "writes the keyboard's RTC and is useful on firmware/models that "
            "expose a clock display."
        )
        text.setObjectName("Muted")
        text.setWordWrap(True)
        info_layout.addWidget(text)
        root.addWidget(info)
        root.addStretch(1)

        self.sync_btn.clicked.connect(self._sync)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(500)
        self._tick()

    def _tick(self) -> None:
        now = datetime.now()
        self.time_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%A, %d %B %Y"))

    def _sync(self) -> None:
        when = datetime.now()
        self.run_task(
            lambda signals: task_clock(signals, when),
            on_done=lambda result: self._synced(result),
            message="Synchronising the keyboard clock…",
        )

    def _synced(self, when: datetime) -> None:
        self.last_label.setText("Clock data sent at " + when.strftime("%H:%M:%S"))
        window = self.window()
        if hasattr(window, "show_status"):
            window.show_status("Clock data sent to the keyboard.")


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------


def describe_slot(slot: tuple[int, int, int, int]) -> str:
    action, p1, p2, p3 = slot
    if action == C.ACTION_NONE:
        return "Disabled"
    if action == C.ACTION_SPECIAL:
        for name, params in C.SPECIAL_FUNCTIONS.items():
            if params == (p1, p2):
                return C.SPECIAL_LABELS[name]
        return f"Special 0x{p1:02x}/0x{p2:02x}"
    if action == C.ACTION_KEY:
        names = [name for name, bit in C.MODIFIERS if p1 & bit]
        if p2:
            target = f"0x{p2:02x}"
            for name, code in C.HID_KEYS.items():
                if code == p2:
                    target = C.hid_key_label(name)
                    break
            names.append(target)
        return "+".join(names) if names else "None"
    if action == C.ACTION_CONSUMER:
        for name, code in C.CONSUMER_KEYS.items():
            if code == p1:
                return C.CONSUMER_LABELS[name]
        return f"Media 0x{p1:02x}"
    if action == C.ACTION_MOUSE:
        for name, params in C.MOUSE_ACTIONS.items():
            if params == (p1, p2, p3):
                return C.MOUSE_LABELS[name]
        return f"Mouse 0x{p1:02x}/0x{p2:02x}/0x{p3:02x}"
    return f"Action {action}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = Store()
        self.runner = TaskRunner(self)
        self.setWindowTitle("Womier SK80")
        self.setMinimumSize(1120, 720)
        self.resize(1240, 820)

        central = QWidget()
        central.setObjectName("Root")
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(226)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 24, 16, 16)
        sidebar_layout.setSpacing(6)

        brand = QLabel("WOMIER")
        brand.setObjectName("BrandSmall")
        model = QLabel("SK80")
        model.setObjectName("BrandBig")
        subtitle = QLabel("Linux Control")
        subtitle.setObjectName("Muted")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(model)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(22)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        self.pages = [
            LightingPage(self.store, self.run_task),
            PerKeyPage(self.store, self.run_task),
            KeymapPage(self.store, self.run_task),
            ScreenPage(self.store, self.run_task),
            ClockPage(self.store, self.run_task),
        ]
        self.stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        for page in self.pages:
            page.setObjectName("Page")
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.stack.addWidget(page)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_items = [
            "Lighting",
            "Per-key RGB",
            "Key Mapping",
            "LCD Screen",
            "Clock",
        ]
        for index, text in enumerate(nav_items):
            button = QPushButton(text)
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(40)
            self.nav_group.addButton(button, index)
            sidebar_layout.addWidget(button)
            if index == 0:
                button.setChecked(True)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)

        sidebar_layout.addStretch(1)

        connection = QFrame()
        connection.setObjectName("ConnCard")
        connection_layout = QVBoxLayout(connection)
        connection_layout.setContentsMargins(12, 10, 12, 10)
        connection_layout.setSpacing(3)
        status_row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("StatusDot")
        self.connection_label = QLabel("Checking…")
        self.connection_label.setObjectName("ConnLabel")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.connection_label, 1)
        connection_layout.addLayout(status_row)
        self.lcd_label = QLabel("LCD: checking…")
        self.lcd_label.setObjectName("MutedSmall")
        self.lcd_label.setWordWrap(True)
        connection_layout.addWidget(self.lcd_label)
        sidebar_layout.addWidget(connection)

        version = QLabel(f"v{__version__}")
        version.setObjectName("MutedSmall")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(version)

        layout.addWidget(sidebar)
        container = QWidget()
        container.setObjectName("Content")
        container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.stack)
        layout.addWidget(container, 1)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Ready")

        self.runner.busyChanged.connect(self._on_busy)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_device)
        self._poll_timer.start(2500)
        self._poll_device()

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def show_progress(self, sent: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(sent)
        self.progress.show()

    def run_task(
        self,
        fn,
        on_done=None,
        on_error=None,
        on_progress=None,
        message: str = "Working…",
    ) -> bool:
        def wrapped_done(result):
            self.progress.hide()
            if on_done is not None:
                on_done(result)

        def wrapped_error(text: str):
            self.progress.hide()
            if on_error is not None:
                on_error(text)
            else:
                QMessageBox.warning(self, "SK80", text)
            self.statusBar().showMessage("Operation failed.", 8000)

        def wrapped_progress(sent: int, total: int):
            self.show_progress(sent, total)
            if on_progress is not None:
                on_progress(sent, total)

        started = self.runner.run(
            fn,
            on_done=wrapped_done,
            on_error=wrapped_error,
            on_progress=wrapped_progress if on_progress is not None else None,
        )
        if not started:
            self.statusBar().showMessage("Another operation is still running.", 4000)
            return False
        self.statusBar().showMessage(message)
        return True

    def _on_busy(self, busy: bool) -> None:
        for button in self.findChildren(QPushButton):
            if button.property("busyDisable"):
                button.setEnabled(not busy)

    def _poll_device(self) -> None:
        connected = SK80.is_connected()
        hidraw = find_lcd_hidraw()
        if connected:
            self.status_dot.setStyleSheet("color: #5ee6a8;")
            self.connection_label.setText("Connected")
            if hidraw:
                self.lcd_label.setText(f"LCD ready · {hidraw}")
            else:
                self.lcd_label.setText("LCD node not found")
        else:
            self.status_dot.setStyleSheet("color: #ff6b81;")
            self.connection_label.setText("Not connected")
            self.lcd_label.setText("Connect the keyboard by USB")

    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        self.runner.pool.waitForDone(2000)
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# theme and entry point
# ---------------------------------------------------------------------------

STYLESHEET = """
QWidget {
    color: #e7ebf3;
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget#Root, QWidget#Content, QStackedWidget#Pages, QWidget#Page { background: #0f1117; }
QFrame#Sidebar { background: #0b0d13; border-right: 1px solid #1d2230; }
QLabel#BrandSmall { color: #6f7a91; font-size: 11px; font-weight: 700; letter-spacing: 3px; }
QLabel#BrandBig { color: #ffffff; font-size: 34px; font-weight: 800; }
QLabel#Muted { color: #7c879d; }
QLabel#MutedSmall { color: #667088; font-size: 11px; }
QLabel#PageTitle { font-size: 25px; font-weight: 800; color: #ffffff; }
QLabel#PageSubtitle { color: #8a94a8; font-size: 12px; }
QLabel#SectionTitle { color: #aeb8cc; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QLabel#KeyTitle { color: #ffffff; font-size: 20px; font-weight: 700; }
QLabel#Warn { color: #f0a04b; }
QLabel#BigClock { color: #ffffff; font-size: 54px; font-weight: 800; }
QLabel#StatusDot { font-size: 16px; }
QLabel#ConnLabel { color: #cfd6e3; font-weight: 600; }
QFrame#Card { background: #161922; border: 1px solid #222838; border-radius: 14px; }
QFrame#ConnCard { background: #12151d; border: 1px solid #222838; border-radius: 10px; }
QPushButton {
    background: #202533; border: 1px solid #2c3345; border-radius: 8px;
    padding: 7px 14px; color: #dfe5f1;
}
QPushButton:hover { background: #283044; border-color: #3a4560; }
QPushButton:pressed { background: #1a1f2b; }
QPushButton:disabled { color: #5b6478; background: #171b24; border-color: #222838; }
QPushButton#Primary { background: #4cc2ff; border: none; color: #071018; font-weight: 700; }
QPushButton#Primary:hover { background: #6fd0ff; }
QPushButton#Primary:pressed { background: #35a8e6; }
QPushButton#Primary:disabled { background: #24404f; color: #637786; }
QPushButton#Danger { background: #2a1a20; border: 1px solid #4a2633; color: #ff9bb0; }
QPushButton#Danger:hover { background: #3a2029; }
QPushButton#Nav {
    background: transparent; border: none; border-radius: 9px;
    text-align: left; padding: 10px 12px; color: #8d97ab; font-weight: 600;
}
QPushButton#Nav:hover { background: #141822; color: #d7deeb; }
QPushButton#Nav:checked { background: #172536; color: #7fd5ff; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 7px 12px; border-radius: 8px; color: #b9c2d4; }
QListWidget::item:hover { background: #1d2330; }
QListWidget::item:selected { background: #203247; color: #ffffff; }
QComboBox, QSpinBox, QLineEdit {
    background: #1b202b; border: 1px solid #2a3143; border-radius: 8px;
    padding: 6px 10px; selection-background-color: #2b5a78;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #3a4560; }
QComboBox QAbstractItemView {
    background: #1b202b; border: 1px solid #2a3143;
    selection-background-color: #2b5a78;
}
QCheckBox { spacing: 8px; color: #b9c2d4; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #3a4560; background: #171b24;
}
QCheckBox::indicator:checked { background: #4cc2ff; border-color: #4cc2ff; }
QSlider::groove:horizontal { height: 4px; background: #262d3c; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4cc2ff; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #dff5ff; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #ffffff; }
QProgressBar { background: #1b202b; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #4cc2ff; border-radius: 4px; }
QStatusBar { background: #0b0d13; color: #7c879d; border-top: 1px solid #1d2230; }
QToolTip { background: #1b202b; color: #e7ebf3; border: 1px solid #2a3143; padding: 5px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2a3143; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3a4560; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#4cc2ff"))
    painter.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    painter.setPen(QColor("#071018"))
    font = QFont("Noto Sans", 18)
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Womier SK80")
    app.setApplicationDisplayName("Womier SK80")
    app.setOrganizationName("womier")
    app.setStyle("Fusion")
    app.setWindowIcon(make_icon())
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
