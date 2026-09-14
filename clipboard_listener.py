"""
剪贴板事件监听层 (Clipboard Event Listener)

利用 Windows 原生 AddClipboardFormatListener 事件通知机制，
在独立的后台消息泵线程中接收 WM_CLIPBOARDUPDATE，实现 0 轮询开销的剪贴板捕获。
"""

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from typing import Optional

from storage import ClipboardHistoryManager
from win32_clipboard import (
    get_clipboard_text,
    get_clipboard_image,
    is_text_available,
    is_image_available,
)

logger = logging.getLogger("SmartClipboard.Listener")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_CLIPBOARDUPDATE = 0x031D
WM_DESTROY = 0x0002
HWND_MESSAGE = wintypes.HWND(-3)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# 确保 DefWindowProcW 签名 64 位精准
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t

user32.AddClipboardFormatListener.argtypes = [wintypes.HWND]
user32.AddClipboardFormatListener.restype = wintypes.BOOL

user32.RemoveClipboardFormatListener.argtypes = [wintypes.HWND]
user32.RemoveClipboardFormatListener.restype = wintypes.BOOL

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class ClipboardListener:
    """
    基于 Win32 消息循环的高性能剪贴板监听器
    """

    def __init__(self, storage: ClipboardHistoryManager):
        self.storage = storage
        self._thread: Optional[threading.Thread] = None
        self._hwnd: Optional[int] = None
        self._wnd_proc_ref = None  # 必须持有 WNDPROC 引用，防止被 Python GC 回收导致崩溃
        self._is_running = False
        self._ignore_internal_event = False  # 内部写入剪贴板时的防重入标识

    def set_ignore_internal_event(self, ignore: bool) -> None:
        """标记当前操作是否为应用内部写入剪贴板"""
        self._ignore_internal_event = ignore

    def start(self) -> None:
        """启动后台监听线程"""
        if self._is_running:
            return

        self._is_running = True
        self._thread = threading.Thread(target=self._run_message_loop, daemon=True, name="ClipboardListenerThread")
        self._thread.start()
        logger.info("Clipboard listener thread started")

    def stop(self) -> None:
        """安全停止监听线程并注销 Win32 资源"""
        if not self._is_running:
            return

        self._is_running = False
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Clipboard listener stopped")

    def _on_clipboard_update(self) -> None:
        """处理剪贴板更新事件"""
        if self._ignore_internal_event:
            logger.debug("Skipping update from internal synthetic write")
            return

        # 稍微延时 10ms，避免极少数极端情况下复制程序尚未写入完毕导致的读取竞争
        time.sleep(0.01)

        try:
            # 优先检查图片
            if is_image_available():
                img = get_clipboard_image()
                if img:
                    logger.debug(f"Captured image update: {img.size}")
                    self.storage.add_image(img)
                    return

            # 检查文本
            if is_text_available():
                text = get_clipboard_text()
                if text and text.strip():
                    logger.debug(f"Captured text update: {len(text)} chars")
                    self.storage.add_text(text)
                    return

        except Exception as e:
            logger.error(f"Error handling clipboard update: {e}", exc_info=True)

    def _run_message_loop(self) -> None:
        """Win32 消息泵主循环"""
        def _wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_CLIPBOARDUPDATE:
                self._on_clipboard_update()
                return 0
            elif msg == WM_DESTROY:
                user32.RemoveClipboardFormatListener(hwnd)
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc_ref = WNDPROC(_wnd_proc)
        h_inst = kernel32.GetModuleHandleW(None)
        class_name = f"SmartClipboardWatcher_{id(self)}"

        wc = WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc_ref
        wc.lpszClassName = class_name
        wc.hInstance = h_inst

        reg_atom = user32.RegisterClassW(ctypes.byref(wc))
        if not reg_atom:
            logger.error(f"Failed to register window class for clipboard watcher: {kernel32.GetLastError()}")
            return

        # 创建 Message-Only 窗口
        self._hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "SmartClipboardWatcher",
            0,
            0,
            0,
            0,
            0,
            HWND_MESSAGE,
            0,
            h_inst,
            0
        )

        if not self._hwnd:
            logger.error(f"Failed to create watcher window: {kernel32.GetLastError()}")
            return

        if not user32.AddClipboardFormatListener(self._hwnd):
            logger.error(f"AddClipboardFormatListener failed: {kernel32.GetLastError()}")
            return

        logger.info(f"Clipboard format listener registered successfully with hwnd: {self._hwnd}")

        # 标准消息循环
        msg = wintypes.MSG()
        while self._is_running:
            # 使用 GetMessageW 阻塞等待消息，空闲时完全挂起线程，0% CPU
            ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        logger.info("Clipboard message loop terminated cleanly")
