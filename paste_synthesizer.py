"""
粘贴合成执行层 (Paste Synthesizer)

负责将用户所选条目原子化写入剪贴板，并将焦点精准归还目标前台窗口，
随后发送带有防自拦截魔数签名的合成 Ctrl+V 按键事件，完成透明化粘贴。
"""

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from typing import Optional

from config import SYNTHETIC_PASTE_MAGIC, VK_CONTROL, VK_V
from models import ClipboardItem, ClipboardItemType
from win32_clipboard import set_clipboard_text, set_clipboard_image

logger = logging.getLogger("SmartClipboard.Synthesizer")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

KEYEVENTF_KEYUP = 0x0002

user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.keybd_event.restype = None

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL


def activate_target_window(hwnd: int) -> bool:
    """
    鲁棒地将指定窗口句柄激活并置为前台焦点窗口
    
    采用 Win32 AttachThreadInput 线程输入关联技术，
    绕过 Windows 10/11 的跨进程前台焦点锁定限制。
    """
    if not hwnd or not user32.IsWindow(hwnd):
        logger.warning(f"Invalid target hwnd: {hwnd}")
        return False

    current_tid = kernel32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    if current_tid != target_tid and target_tid != 0:
        user32.AttachThreadInput(current_tid, target_tid, True)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.AttachThreadInput(current_tid, target_tid, False)
    else:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)

    return True


def execute_paste(item: ClipboardItem, target_hwnd: int, on_before_write: Optional[callable] = None, on_after_paste: Optional[callable] = None) -> None:
    """
    在独立后台线程中执行异步安全粘贴
    
    避免主 UI 线程因等待窗口焦点就绪或剪贴板 I/O 产生卡顿。
    """
    def _paste_worker():
        try:
            logger.info(f"Executing paste for item: {item.id}, target hwnd: {target_hwnd}")

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

            # 4. 发送注入了魔数签名的 Ctrl + V 键盘组合事件
            magic = SYNTHETIC_PASTE_MAGIC
            user32.keybd_event(VK_CONTROL, 0, 0, magic)
            user32.keybd_event(VK_V, 0, 0, magic)
            user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, magic)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, magic)

            logger.info("Synthesized Ctrl+V key event sent successfully")

            # 5. 等待目标应用完成读取后再解除防重入忽略
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"Error executing paste: {e}", exc_info=True)
        finally:
            if on_after_paste:
                on_after_paste()

    threading.Thread(target=_paste_worker, daemon=True, name="PasteWorkerThread").start()
