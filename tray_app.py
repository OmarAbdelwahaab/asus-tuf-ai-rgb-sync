import ctypes
from ctypes import wintypes
import os
import sys
import subprocess
from typing import Optional, Callable
from autostart import is_autostart_enabled, enable_autostart, disable_autostart
from config import CONFIG_FILE

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32', use_last_error=True)

# Win32 Constants
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

TPM_LEFTALIGN = 0x0000
TPM_BOTTOMALIGN = 0x0020
TPM_RIGHTBUTTON = 0x0002

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
MF_UNCHECKED = 0x0000
MF_GRAYED = 0x0001
MF_DISABLED = 0x0002

IDI_APPLICATION = 32512

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uID', wintypes.UINT),
        ('uFlags', wintypes.UINT),
        ('uCallbackMessage', wintypes.UINT),
        ('hIcon', wintypes.HICON),
        ('szTip', wintypes.WCHAR * 128),
        ('dwState', wintypes.DWORD),
        ('dwStateMask', wintypes.DWORD),
        ('szInfo', wintypes.WCHAR * 256),
        ('uTimeoutOrVersion', wintypes.UINT),
        ('szInfoTitle', wintypes.WCHAR * 64),
        ('dwInfoFlags', wintypes.DWORD),
        ('guidItem', GUID),
        ('hBalloonIcon', wintypes.HICON)
    ]

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM
)

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT),
        ('style', wintypes.UINT),
        ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HCURSOR),
        ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
        ('hIconSm', wintypes.HICON)
    ]

class TrayApp:
    def __init__(self, coordinator, on_exit: Optional[Callable] = None):
        self.coordinator = coordinator
        self.on_exit = on_exit
        self.hwnd: Optional[int] = None
        self.nid = NOTIFYICONDATAW()
        self._wndproc = WNDPROC(self._window_proc)
        self.class_name = "AsusTufAiSyncTrayClass"

    def _create_window(self) -> bool:
        h_inst = kernel32.GetModuleHandleW(None)

        wndclass = WNDCLASSEXW()
        wndclass.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wndclass.style = 0
        wndclass.lpfnWndProc = self._wndproc
        wndclass.hInstance = h_inst
        wndclass.hIcon = user32.LoadIconW(0, IDI_APPLICATION)
        wndclass.lpszClassName = self.class_name

        user32.RegisterClassExW(ctypes.byref(wndclass))

        self.hwnd = user32.CreateWindowExW(
            0,
            self.class_name,
            "AsusTufAiSyncTray",
            0,
            0, 0, 0, 0,
            0, 0, h_inst, 0
        )
        return bool(self.hwnd)

    def _add_tray_icon(self) -> bool:
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd = self.hwnd
        self.nid.uID = 1
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self.nid.uCallbackMessage = WM_TRAYICON
        self.nid.hIcon = user32.LoadIconW(0, IDI_APPLICATION)
        self.nid.szTip = "ASUS TUF AI RGB Sync (Active)"

        return bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid)))

    def update_tooltip(self, tip: str):
        if not self.hwnd:
            return
        self.nid.szTip = tip[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def _remove_tray_icon(self):
        if self.hwnd:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))

    def _show_menu(self):
        h_menu = user32.CreatePopupMenu()

        # Status item (disabled header)
        ag_st = self.coordinator.antigravity_state.value
        cl_st = self.coordinator.claude_state.value
        res_st = self.coordinator.resolved_state.value
        status_text = f"Status: {res_st} (AG: {ag_st}, Claude: {cl_st})"

        user32.AppendMenuW(h_menu, MF_STRING | MF_DISABLED, 100, status_text)
        user32.AppendMenuW(h_menu, MF_SEPARATOR, 101, "")

        # Manual test actions
        user32.AppendMenuW(h_menu, MF_STRING, 201, "Test: Pure 255 Red (Working)")
        user32.AppendMenuW(h_menu, MF_STRING, 202, "Test: Pure 255 Yellow (Waiting)")
        user32.AppendMenuW(h_menu, MF_STRING, 203, "Test: Default Profile (Idle)")
        user32.AppendMenuW(h_menu, MF_SEPARATOR, 204, "")

        # Autostart option
        autostart_flags = MF_STRING | (MF_CHECKED if is_autostart_enabled() else MF_UNCHECKED)
        user32.AppendMenuW(h_menu, autostart_flags, 301, "Start with Windows")

        # Config option
        user32.AppendMenuW(h_menu, MF_STRING, 302, "Open Settings (config.json)")
        user32.AppendMenuW(h_menu, MF_SEPARATOR, 303, "")

        # Exit
        user32.AppendMenuW(h_menu, MF_STRING, 401, "Exit")

        # Position menu at cursor
        pos = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pos))

        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(
            h_menu,
            TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON,
            pos.x, pos.y,
            0, self.hwnd, None
        )
        user32.DestroyMenu(h_menu)

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == WM_RBUTTONUP:
                self._show_menu()
            elif lparam == WM_LBUTTONDBLCLK:
                # Double click opens config
                subprocess.Popen(f'notepad.exe "{CONFIG_FILE}"', shell=True)
            return 0

        elif msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == 201:
                self.coordinator.keyboard.set_working(force=True)
            elif cmd == 202:
                self.coordinator.keyboard.set_waiting_approval(force=True)
            elif cmd == 203:
                self.coordinator.keyboard.set_default(force=True)
            elif cmd == 301:
                if is_autostart_enabled():
                    disable_autostart()
                else:
                    enable_autostart()
            elif cmd == 302:
                subprocess.Popen(f'notepad.exe "{CONFIG_FILE}"', shell=True)
            elif cmd == 401:
                user32.DestroyWindow(self.hwnd)
            return 0

        elif msg == WM_DESTROY:
            self._remove_tray_icon()
            if self.on_exit:
                self.on_exit()
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        if not self._create_window():
            print("Failed to create tray window.")
            return
        if not self._add_tray_icon():
            print("Failed to add tray icon.")
            return

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
