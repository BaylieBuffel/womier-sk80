"""USB protocol implementation for the Womier SK80.

Configuration commands use 64-byte HID feature reports on USB interface 3.
The LCD data path uses the kernel ``hidraw`` node for interface 2, because
interface 2 is bound to ``usbhid`` and is not available as a vendor interface
through libusb.

The command set is the SONiX/Aula protocol used by the vendor's Windows
software.  Every method below was validated against a physical SK80.
"""

from __future__ import annotations

import glob
import os
import select
import time
from datetime import datetime
from typing import Callable, Iterable, Mapping, Optional, Sequence

import usb.core
import usb.util

from . import constants as C


class SK80Error(Exception):
    """Base class for SK80 errors."""


class DeviceNotFound(SK80Error):
    """The keyboard is not connected (or not accessible)."""


class ProtocolError(SK80Error):
    """A USB transfer or the keyboard's response was invalid."""


def find_lcd_hidraw(
    vendor_id: int = C.VENDOR_ID, product_id: int = C.PRODUCT_ID
) -> Optional[str]:
    """Return the ``/dev/hidraw*`` node for the LCD vendor interface.

    The SK80's LCD interface is USB interface 2.  Its hidraw node is found by
    matching the USB VID/PID and reading ``bInterfaceNumber`` from sysfs.
    ``SK80_HIDRAW`` overrides the search when set.
    """
    override = os.environ.get("SK80_HIDRAW")
    if override:
        return override

    for sys_path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_path, "device", "uevent"), encoding="utf-8") as fh:
                uevent = fh.read()
        except OSError:
            continue

        vendor = product = None
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                parts = line.split("=", 1)[1].split(":")
                if len(parts) == 3:
                    try:
                        vendor = int(parts[1], 16)
                        product = int(parts[2], 16)
                    except ValueError:
                        pass
                break
        if vendor != vendor_id or product != product_id:
            continue

        # /sys/class/hidraw/hidrawN/device -> .../1-4.2:1.2/0003:VID:PID.NNNN
        real = os.path.realpath(os.path.join(sys_path, "device"))
        iface_file = os.path.join(os.path.dirname(real), "bInterfaceNumber")
        try:
            with open(iface_file, encoding="ascii") as fh:
                iface = int(fh.read().strip(), 16)
        except (OSError, ValueError):
            continue
        if iface == C.LCD_INTERFACE:
            return "/dev/" + os.path.basename(sys_path)

    return None


class SK80:
    """An open connection to the keyboard."""

    def __init__(self, device=None):
        if device is None:
            device = usb.core.find(idVendor=C.VENDOR_ID, idProduct=C.PRODUCT_ID)
        if device is None:
            raise DeviceNotFound(
                "Womier SK80 not found (VID 05ac, PID 024f). "
                "Check the USB cable and the udev rule."
            )
        self.dev = device
        self.delay = C.CMD_DELAY
        self._lcd_path: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass

    def __enter__(self) -> "SK80":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @classmethod
    def is_connected(cls) -> bool:
        try:
            return usb.core.find(idVendor=C.VENDOR_ID, idProduct=C.PRODUCT_ID) is not None
        except Exception:
            return False

    @property
    def lcd_path(self) -> Optional[str]:
        if self._lcd_path is None:
            self._lcd_path = find_lcd_hidraw()
        return self._lcd_path

    # -- low-level transfers ----------------------------------------------

    def _set_report(self, packet: bytes) -> None:
        if len(packet) > C.REPORT_SIZE:
            raise ValueError("feature report must be <= 64 bytes")
        buf = bytearray(C.REPORT_SIZE)
        buf[: len(packet)] = packet
        try:
            self.dev.ctrl_transfer(0x21, 0x09, 0x0300, C.CONFIG_INTERFACE, buf, timeout=1000)
        except usb.core.USBError as exc:
            raise ProtocolError(f"SET_REPORT failed: {exc}") from exc

    def _get_report(self) -> bytes:
        last: Optional[Exception] = None
        for _attempt in range(2):
            try:
                data = self.dev.ctrl_transfer(
                    0xA1, 0x01, 0x0300, C.CONFIG_INTERFACE, C.REPORT_SIZE, timeout=1000
                )
                return bytes(data)
            except usb.core.USBError as exc:
                last = exc
                time.sleep(0.02)
        raise ProtocolError(f"GET_REPORT failed: {last}")

    def _cmd(self, payload: Sequence[int], readback: bool = True, end_trailer: bool = True) -> bytes:
        """Send one command and optionally read the 64-byte acknowledgement."""
        packet = bytearray(C.REPORT_SIZE)
        raw = bytes(payload)
        packet[: len(raw)] = raw[: C.REPORT_SIZE]
        if end_trailer:
            packet[62] = 0xAA
            packet[63] = 0x55
        self._set_report(packet)
        time.sleep(self.delay)
        if not readback:
            return b""
        response = self._get_report()
        time.sleep(self.delay)
        return response

    def _multi(self, data: bytes, readback: bool = False) -> None:
        """Send a byte buffer as consecutive 64-byte feature reports."""
        if not data:
            return
        for offset in range(0, len(data), C.REPORT_SIZE):
            chunk = data[offset : offset + C.REPORT_SIZE]
            packet = bytearray(C.REPORT_SIZE)
            packet[: len(chunk)] = chunk
            self._set_report(packet)
            time.sleep(self.delay)
        if readback:
            self._get_report()
            time.sleep(self.delay)

    def begin(self) -> bytes:
        return self._cmd(b"\x04\x18")

    def apply(self) -> bytes:
        return self._cmd(b"\x04\x02")

    def finalize(self, readback: bool = False) -> bytes:
        return self._cmd(b"\x04\xf0", readback=readback)

    # -- lighting ----------------------------------------------------------

    def set_lighting(
        self,
        mode: int,
        r: int = 255,
        g: int = 255,
        b: int = 255,
        brightness: int = 5,
        speed: int = 5,
        direction: int = 0,
        colorful: bool = False,
    ) -> None:
        """Set the main backlight effect."""
        mode = int(mode)
        if not 0 <= mode <= 21:
            raise ValueError("mode must be 0..21")
        brightness = max(0, min(5, int(brightness)))
        speed = max(0, min(5, int(speed)))
        direction = 1 if direction else 0

        self.begin()

        init = bytearray(C.REPORT_SIZE)
        init[0] = 0x04
        init[1] = 0x13
        init[8] = 0x01
        self._cmd(init)

        data = bytearray(C.REPORT_SIZE)
        data[0] = mode
        if mode != 0:
            data[1] = r & 0xFF
            data[2] = g & 0xFF
            data[3] = b & 0xFF
            data[8] = 1 if colorful else 0
            data[9] = brightness
            data[10] = speed
            data[11] = direction
        data[14] = 0x55
        data[15] = 0xAA
        self._cmd(data, readback=False)

        self.apply()
        self.finalize(readback=False)

    def turn_off(self) -> None:
        self.set_lighting(0)

    # -- per-key RGB -------------------------------------------------------

    def set_per_key(
        self,
        colors: Mapping[int, tuple[int, int, int]],
        brightness: int = 5,
    ) -> None:
        """Set individual keys by ``light_index``.

        Any key that is not present in *colors* is turned off.  The keyboard
        receives a complete 576-byte table on every call.
        """
        brightness = max(0, min(5, int(brightness)))

        # The firmware needs this LED-strip preamble before accepting the
        # per-key table.
        self.begin()
        init = bytearray(C.REPORT_SIZE)
        init[0] = 0x04
        init[1] = 0x13
        init[8] = 0x01
        self._cmd(init)

        preamble = bytearray(C.REPORT_SIZE)
        preamble[0] = 0x80
        preamble[9] = brightness
        preamble[14] = 0x55
        preamble[15] = 0xAA
        self._cmd(preamble, readback=False)
        self.apply()
        self.finalize(readback=False)

        self.begin()
        init = bytearray(C.REPORT_SIZE)
        init[0] = 0x04
        init[1] = 0x23
        init[8] = 0x09
        self._cmd(init)

        table = bytearray(0x240)
        for index, rgb in colors.items():
            index = int(index)
            if index <= 0 or index * 4 + 3 >= len(table) - 2:
                continue
            off = index * 4
            table[off] = index & 0xFF
            table[off + 1] = int(rgb[0]) & 0xFF
            table[off + 2] = int(rgb[1]) & 0xFF
            table[off + 3] = int(rgb[2]) & 0xFF
        table[-2] = 0x55
        table[-1] = 0xAA

        self._multi(bytes(table), readback=True)
        self.apply()
        self.finalize(readback=True)

    # -- key remapping -----------------------------------------------------

    def set_remap(
        self,
        remaps: Mapping[int, tuple[int, int, int, int]],
        fn_layer: bool = False,
    ) -> None:
        """Replace the remap table for the normal or Fn layer.

        ``remaps`` maps a physical ``key_index`` to a 4-byte slot:
        ``(action, param1, param2, param3)``.  Keys not present keep their
        default behavior.
        """
        self.begin()

        init = bytearray(C.REPORT_SIZE)
        init[0] = 0x04
        init[1] = 0x27 if fn_layer else 0x11
        init[8] = 0x09
        self._cmd(init)

        table = bytearray(0x240)
        for index, slot in remaps.items():
            index = int(index)
            if index <= 0 or index * 4 + 3 >= len(table) - 2:
                continue
            values = list(slot) + [0, 0, 0, 0]
            off = index * 4
            table[off : off + 4] = bytes(v & 0xFF for v in values[:4])
        # uint16 0x55AA, little-endian on the wire.
        table[-2] = 0xAA
        table[-1] = 0x55

        self._multi(bytes(table), readback=False)
        self.apply()
        self.finalize(readback=True)

    def reset_remap(self, fn_layer: bool = False) -> None:
        self.set_remap({}, fn_layer=fn_layer)

    # -- clock -------------------------------------------------------------

    def set_clock(self, when: Optional[datetime] = None) -> None:
        """Synchronise the LCD clock."""
        when = when or datetime.now()

        # Match the vendor's clock transaction: the begin/init/apply packets
        # have zero padding, while only the date/time data packet carries the
        # AA 55 trailer.
        self._cmd(b"\x04\x18", end_trailer=False)

        init = bytearray(C.REPORT_SIZE)
        init[0] = 0x04
        init[1] = 0x28
        init[8] = 0x01
        self._cmd(init, end_trailer=False)

        data = bytearray(C.REPORT_SIZE)
        data[0] = 0x00
        data[1] = 0x01
        data[2] = 0x5A
        data[3] = when.year % 2000
        data[4] = when.month
        data[5] = when.day
        data[6] = when.hour
        data[7] = when.minute
        data[8] = when.second
        # The vendor's SK80 clock packet leaves bytes 9+ zero; the firmware
        # derives the weekday from the date.  _cmd adds the AA 55 trailer.
        self._cmd(data, readback=True)

        self._cmd(b"\x04\x02", end_trailer=False)

    # -- LCD ---------------------------------------------------------------

    def upload_screen(
        self,
        buffer: bytes,
        slot: int = 1,
        progress: Optional[Callable[[int, int], None]] = None,
        ack_timeout: float = 0.3,
    ) -> int:
        """Upload a pre-built LCD buffer (header + RGB565 frames).

        Returns the number of 4096-byte pages sent.
        """
        if not buffer or len(buffer) % C.PAGE_SIZE:
            raise ValueError("LCD buffer must be a positive multiple of 4096 bytes")
        page_count = len(buffer) // C.PAGE_SIZE
        if not 1 <= page_count <= 0xFFFF:
            raise ValueError("invalid LCD page count")

        hidraw = self.lcd_path
        if not hidraw:
            raise DeviceNotFound(
                "LCD hidraw node not found. Is the keyboard's interface 2 bound? "
                "Try setting SK80_HIDRAW=/dev/hidrawN."
            )
        try:
            fd = os.open(hidraw, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            raise ProtocolError(f"cannot open {hidraw}: {exc}") from exc

        try:
            self.begin()

            header = bytearray(C.REPORT_SIZE)
            header[0] = 0x04
            header[1] = 0x72
            header[2] = slot & 0xFF
            header[8] = page_count & 0xFF
            header[9] = (page_count >> 8) & 0xFF
            self._cmd(header)

            for page_index in range(page_count):
                page = buffer[page_index * C.PAGE_SIZE : (page_index + 1) * C.PAGE_SIZE]
                self._write_all(fd, page, ack_timeout)
                self._read_ack(fd, ack_timeout)
                if progress is not None:
                    progress(page_index + 1, page_count)

            self.apply()
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

        return page_count

    @staticmethod
    def _write_all(fd: int, data: bytes, timeout: float) -> None:
        offset = 0
        while offset < len(data):
            try:
                written = os.write(fd, data[offset:])
            except BlockingIOError:
                _, ready, _ = select.select([], [fd], [], timeout)
                if not ready:
                    raise ProtocolError("timed out writing LCD page")
                continue
            except OSError as exc:
                raise ProtocolError(f"LCD write failed: {exc}") from exc
            if written <= 0:
                raise ProtocolError("LCD write returned 0 bytes")
            offset += written

    @staticmethod
    def _read_ack(fd: int, timeout: float) -> Optional[bytes]:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        try:
            return os.read(fd, 64)
        except OSError:
            return None
