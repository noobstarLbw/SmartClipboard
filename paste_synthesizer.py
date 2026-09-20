"""
粘贴合成执行层 (Paste Synthesizer)

负责将用户所选条目原子化写入剪贴板，并将焦点精准归还目标前台窗口，
根据目标窗口类型智能选择最佳按键合成协议（常规窗口 Ctrl+V / 终端环境 Shift+Insert），
利用携带防自拦截魔数签名的按键序列完成透明化粘贴。
"""

import ctypes
from ctypes import wintypes
import logging
import os
import threading
import time
from typing import Optional, Set

from config import (
    SYNTHETIC_PASTE_MAGIC,
    VK_CONTROL,
    VK_V,
    VK_SHIFT,
    VK_MENU,
    VK_INSERT,
    KEYEVENTF_KEYUP,
    KEYEVENTF_EXTENDEDKEY,
    TERMINAL_PASTE_WITH_SHIFT_INSERT,
)
from models import ClipboardItem, ClipboardItemType
from win32_clipboard import set_clipboard_text, set_clipboard_image

logger = logging.getLogger("SmartClipboard.Synthesizer")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 显式声明 Win32 API 签名
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.keybd_event.restype = None

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wintypes.BOOL


# 常见主流终端的 Win32 窗口类名集合
TERMINAL_WINDOW_CLASSES: Set[str] = {
    "ConsoleWindowClass",             # Windows 原生控制台宿主 (CMD, PowerShell, conhost.exe)
    "CASCADIA_HOSTING_WINDOW_CLASS",  # 现代 Windows Terminal (wt.exe, WindowsTerminal.exe)
    "mintty",                         # Git Bash / MSYS2 / Cygwin
    "VirtualConsoleClass",            # ConEmu / Cmder
    "PuTTY",                          # PuTTY SSH 客户端
    "Alacritty",                      # Alacritty 终端
    "Ghostty",                        # Ghostty 终端
    "WezTerm",                        # WezTerm 终端
    "Termius",                        # Termius
    "Kitty",                          # KiTTY
}

# 常见主流终端的可执行文件进程名集合 (小写)
TERMINAL_PROCESS_NAMES: Set[str] = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "conhost.exe",
    "windowsterminal.exe",
    "wt.exe",
    "mintty.exe",
    "bash.exe",
    "wsl.exe",
    "wslhost.exe",
    "putty.exe",
    "kitty.exe",
    "alacritty.exe",
    "wezterm-gui.exe",
    "termius.exe",
}


def is_current_process_admin() -> bool:
    """查询当前 SmartClipboard 进程是否拥有管理员权限"""
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_window_class_name(hwnd: int) -> str:
    """获取指定窗口的 Win32 类名"""
    if not hwnd or not user32.IsWindow(hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_process_name_by_hwnd(hwnd: int) -> Optional[str]:
    """通过窗口句柄查询其所属进程的主执行文件名 (例如 powershell.exe)"""
    if not hwnd or not user32.IsWindow(hwnd):
        return None

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None

    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h_proc:
        return None

    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return None
    except Exception as e:
        logger.debug(f"Failed to query process image name for PID {pid.value}: {e}")
        return None
    finally:
        kernel32.CloseHandle(h_proc)


def is_terminal_window(hwnd: int) -> bool:
    """
    智能检测指定窗口是否属于终端 / 控制台类应用程序
    
    综合运用窗口类名快速匹配与进程可执行文件名称深度解析双重技术，
    覆盖 Windows Terminal、Git Bash (mintty)、CMD、PowerShell、WSL、PuTTY 等几乎所有场景。
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return False

    # 1. 窗口类名快速命中
    cls_name = get_window_class_name(hwnd)
    if cls_name in TERMINAL_WINDOW_CLASSES:
        return True

    # 2. 进程可执行文件名深度匹配
    exe_name = get_process_name_by_hwnd(hwnd)
    if exe_name and exe_name.lower() in TERMINAL_PROCESS_NAMES:
        return True

    return False


def activate_target_window(hwnd: int) -> bool:
    """
    鲁棒地将指定窗口句柄激活并置为前台焦点窗口
    
    采用 Win32 经典前台锁定穿透技术：
    1. 若窗口最小化，先通过 ShowWindow(SW_RESTORE) 恢复窗口；
    2. 模拟按下与释放 VK_MENU (Alt) 键，重置 Windows SPI 前台锁超时计数器；
    3. 获取当前真实前台线程 TID 与目标线程 TID，调用 AttachThreadInput 精准关联；
    4. 调用 SetForegroundWindow 与 BringWindowToTop 将目标窗口强制前置；
    5. 解除线程关联以防死锁。
    """
    if not hwnd or not user32.IsWindow(hwnd):
        logger.warning(f"Invalid target hwnd: {hwnd}")
        return False

    # 若窗口最小化，先予以恢复
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    fg_hwnd = user32.GetForegroundWindow()
    if fg_hwnd == hwnd:
        return True

    # 经典 Alt 键穿透 Windows 前台锁定
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    attached = False
    if fg_tid and target_tid and fg_tid != target_tid:
        attached = bool(user32.AttachThreadInput(fg_tid, target_tid, True))

    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fg_tid, target_tid, False)

    return user32.GetForegroundWindow() == hwnd


def execute_paste(
    item: ClipboardItem,
    target_hwnd: int,
    on_before_write: Optional[callable] = None,
    on_after_paste: Optional[callable] = None,
) -> None:
    """
    在独立后台线程中执行异步安全粘贴
    
    避免主 UI 线程因等待窗口焦点就绪或剪贴板 I/O 产生卡顿。
    根据目标窗口类型智能选择最佳按键合成协议（常规窗口 Ctrl+V / 终端环境 Shift+Insert）。
    """
    def _paste_worker():
        try:
            is_terminal = is_terminal_window(target_hwnd)
            logger.info(
                f"Executing paste for item: {item.id}, target hwnd: {target_hwnd} "
                f"(is_terminal={is_terminal})"
            )

            if on_before_write:
                on_before_write()

            # 1. 将内容置换入系统剪贴板
            success = False
            if item.item_type == ClipboardItemType.TEXT and item.content_text is not None:
                success = set_clipboard_text(item.content_text)
            elif item.item_type == ClipboardItemType.IMAGE and item.content_image is not None:
                success = set_clipboard_image(item.content_image)

            if not success:
                logger.error("Failed to write item data to clipboard before pasting")
                return

            # 2. 激活目标应用程序窗口
            activate_target_window(target_hwnd)

            # 3. 防御性等待 50 毫秒，确保 OS 窗口管理器完成焦点切换
            time.sleep(0.05)

            # 4. 根据目标窗口类型智能合成按键
            magic = SYNTHETIC_PASTE_MAGIC

            if is_terminal and TERMINAL_PASTE_WITH_SHIFT_INSERT:
                # 终端环境：发送全平台终极兼容的 Shift + Insert 组合键 (Insert 为扩展键)
                logger.info(
                    "Target window is a terminal. Synthesizing Shift + Insert for universal terminal paste."
                )
                scan_shift = user32.MapVirtualKeyW(VK_SHIFT, 0) or 0x2A
                scan_insert = user32.MapVirtualKeyW(VK_INSERT, 0) or 0x52

                user32.keybd_event(VK_SHIFT, scan_shift, 0, magic)
                user32.keybd_event(VK_INSERT, scan_insert, KEYEVENTF_EXTENDEDKEY, magic)
                user32.keybd_event(VK_INSERT, scan_insert, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, magic)
                user32.keybd_event(VK_SHIFT, scan_shift, KEYEVENTF_KEYUP, magic)
                logger.info("Synthesized Shift+Insert key event sent successfully")
            else:
                # 常规 GUI 环境：发送带有硬件扫描码的 Ctrl + V 键盘组合事件
                scan_ctrl = user32.MapVirtualKeyW(VK_CONTROL, 0) or 0x1D
                scan_v = user32.MapVirtualKeyW(VK_V, 0) or 0x2F

                user32.keybd_event(VK_CONTROL, scan_ctrl, 0, magic)
                user32.keybd_event(VK_V, scan_v, 0, magic)
                user32.keybd_event(VK_V, scan_v, KEYEVENTF_KEYUP, magic)
                user32.keybd_event(VK_CONTROL, scan_ctrl, KEYEVENTF_KEYUP, magic)
                logger.info("Synthesized Ctrl+V key event sent successfully")

            # 5. 等待目标应用完成读取后再解除防重入忽略
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"Error executing paste: {e}", exc_info=True)
        finally:
            if on_after_paste:
                on_after_paste()

    threading.Thread(target=_paste_worker, daemon=True, name="PasteWorkerThread").start()
