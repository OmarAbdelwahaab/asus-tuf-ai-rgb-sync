import ctypes
import struct
import atexit
from typing import Optional, Tuple
from config import load_config

class AsusTufKeyboard:
    """
    Direct hardware interface for ASUS TUF Gaming built-in RGB keyboard
    using the Windows ATKACPI kernel driver.
    """
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    FILE_ATTRIBUTE_NORMAL = 0x80

    CONTROL_CODE = 0x0022240C
    DEVS = 0x53564544
    DSTS = 0x53545344

    TUF_KB = 0x00100056
    TUF_KB2 = 0x0010005a
    TUF_KB_BRIGHTNESS = 0x00050021

    MODE_STATIC = 0
    MODE_BREATHING = 1
    MODE_COLOR_CYCLE = 2
    MODE_STROBE = 10

    SPEED_SLOW = 0
    SPEED_NORMAL = 1
    SPEED_FAST = 2

    def __init__(self):
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.handle = None
        self._last_state: Optional[Tuple[int, int, int, int, int]] = None
        self._open_handle()
        atexit.register(self.restore_default_on_exit)

    def _open_handle(self) -> bool:
        if self.handle and self.handle != -1 and self.handle != 0xFFFFFFFFFFFFFFFF:
            return True
        self.handle = self.kernel32.CreateFileW(
            r'\\.\\ATKACPI',
            self.GENERIC_READ | self.GENERIC_WRITE,
            self.FILE_SHARE_READ | self.FILE_SHARE_WRITE,
            None,
            self.OPEN_EXISTING,
            self.FILE_ATTRIBUTE_NORMAL,
            None
        )
        return self.handle != -1 and self.handle != 0xFFFFFFFFFFFFFFFF

    def close(self):
        if self.handle and self.handle != -1 and self.handle != 0xFFFFFFFFFFFFFFFF:
            try:
                self.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None

    def _device_set(self, device_id: int, params: bytes) -> int:
        if not self._open_handle():
            return -1
        args = struct.pack('<I', device_id) + params
        acpi_buf = struct.pack('<II', self.DEVS, len(args)) + args
        out_buf = ctypes.create_string_buffer(16)
        returned = ctypes.c_ulong()
        res = self.kernel32.DeviceIoControl(
            self.handle,
            self.CONTROL_CODE,
            acpi_buf,
            len(acpi_buf),
            out_buf,
            len(out_buf),
            ctypes.byref(returned),
            None
        )
        if not res:
            # Handle might have become invalid across sleep or power state
            self.close()
            if self._open_handle():
                res = self.kernel32.DeviceIoControl(
                    self.handle,
                    self.CONTROL_CODE,
                    acpi_buf,
                    len(acpi_buf),
                    out_buf,
                    len(out_buf),
                    ctypes.byref(returned),
                    None
                )
            if not res:
                return -1
        return struct.unpack('<i', out_buf.raw[:4])[0]

    def set_rgb(self, mode: int, r: int, g: int, b: int, speed: int = SPEED_NORMAL, force: bool = False) -> bool:
        """
        Sets the RGB keyboard mode and color.
        Caches state to avoid redundant ACPI IOCTL calls.
        """
        state_key = (mode, r, g, b, speed)
        if not force and self._last_state == state_key:
            return True

        setting = bytes([0xb4, mode, r, g, b, speed])
        res = self._device_set(self.TUF_KB, setting)
        success = False
        if res == 1:
            success = True
        else:
            # Fallback for models requiring TUF_KB2 sequencing
            res2 = self._device_set(self.TUF_KB2, bytes([0xb3, mode, r, g, b, speed]))
            res3 = self._device_set(self.TUF_KB2, bytes([0xb4, mode, r, g, b, speed]))
            success = (res2 == 1 or res3 == 1)

        if success:
            self._last_state = state_key
        return success

    def set_working(self, force: bool = False) -> bool:
        """Breathing mode in Pure Red (255, 0, 0)"""
        cfg = load_config()
        c = cfg.get("colors", {}).get("working", {})
        mode = c.get("mode", self.MODE_BREATHING)
        rgb = c.get("rgb", [255, 0, 0])
        speed = c.get("speed", self.SPEED_NORMAL)
        return self.set_rgb(mode, rgb[0], rgb[1], rgb[2], speed, force=force)

    def set_waiting_approval(self, force: bool = False) -> bool:
        """Solid mode in Pure Yellow (255, 255, 0)"""
        cfg = load_config()
        c = cfg.get("colors", {}).get("waiting_approval", {})
        mode = c.get("mode", self.MODE_STATIC)
        rgb = c.get("rgb", [255, 255, 0])
        speed = c.get("speed", self.SPEED_NORMAL)
        return self.set_rgb(mode, rgb[0], rgb[1], rgb[2], speed, force=force)

    def set_default(self, force: bool = False) -> bool:
        """Restores default idle static profile"""
        cfg = load_config()
        c = cfg.get("colors", {}).get("default_idle", {})
        mode = c.get("mode", self.MODE_STATIC)
        rgb = c.get("rgb", [0, 220, 255])
        speed = c.get("speed", self.SPEED_NORMAL)
        return self.set_rgb(mode, rgb[0], rgb[1], rgb[2], speed, force=force)

    def restore_default_on_exit(self):
        try:
            self.set_default(force=True)
            self.close()
        except Exception:
            pass

if __name__ == "__main__":
    import time
    kb = AsusTufKeyboard()
    print("Testing set_working (Breathing Pure 255 Red)...")
    kb.set_working(force=True)
    time.sleep(2)
    print("Testing set_waiting_approval (Solid Pure 255 Yellow)...")
    kb.set_waiting_approval(force=True)
    time.sleep(2)
    print("Testing set_default (Default profile)...")
    kb.set_default(force=True)
    print("Hardware lighting self-test complete.")
