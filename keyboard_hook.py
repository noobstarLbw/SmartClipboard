"""
键盘底层拦截层 (Low-Level Keyboard Hook)

基于 Windows WH_KEYBOARD_LL 低级钩子，精准识别与拦截用户手按的 Ctrl+V。
利用 dwExtraInfo 携带的魔数签名放行程序内部合成的按键，实现防自触发与防递归死循环。
"""

import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Callable, Optional

from config import (
    SYNTHETIC_PASTE_MAGIC,
    VK_CONTROL,
    VK_V,
    VK_SHIFT,
    VK_MENU,
    VK_LWIN,
    VK_RWIN,
    INTERCEPT_TERMINAL_CTRL_SHIFT_V,
)
from paste_synthesizer import is_terminal_window


logger = logging.getLogger("SmartClipboard.KeyboardHook")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_USER_QUIT = 0x0400 + 101

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """Win32 低级键盘钩子结构体 (严格匹配 64 位平台)"""
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


# 显式声明 Win32 API 签名
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = wintypes.SHORT

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL


class KeyboardHook:
    """
    低级全局键盘钩子管理器
    """

    def __init__(self, on_trigger_callback: Callable[[int, int, int], None]):
        """
        Args:
            on_trigger_callback: 触发 Ctrl+V 时的回调函数，签名: (cursor_x, cursor_y, foreground_hwnd)
        """
        self.on_trigger_callback = on_trigger_callback
        self._h_hook: Optional[int] = None
        self._hook_proc_ref = None  # 维持引用防止 GC 回收
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._is_enabled = True
        self._is_running = False

    def is_enabled(self) -> bool:
        """查询当前是否启用 Ctrl+V 拦截"""
        return self._is_enabled

    def set_enabled(self, enabled: bool) -> None:
        """动态开启或暂停拦截"""
        self._is_enabled = enabled
        logger.info(f"Keyboard hook interception enabled set to: {enabled}")

    def start(self) -> None:
        """启动键盘钩子监听线程"""
        if self._is_running:
            return

        self._is_running = True
        ready_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run_hook_loop,
            args=(ready_event,),
            daemon=True,
            name="KeyboardHookThread",
        )
        self._thread.start()
        # 等待钩子安装就绪
        ready_event.wait(timeout=2.0)
        logger.info("Keyboard hook thread initialized")

    def stop(self) -> None:
        """安全注销钩子并关闭线程"""
        if not self._is_running:
            return

        self._is_running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_USER_QUIT, 0, 0)
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Keyboard hook stopped")

    def _is_key_pressed(self, vk: int) -> bool:
        """检测指定按键当前是否处于按下状态 (高位为 1)"""
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def _hook_callback(self, n_code: int, w_param: int, l_param: int) -> int:
        """底层键盘钩子回调函数 (执行时间必须在微秒级，禁止任何高耗时阻塞)"""
        if n_code >= 0 and (w_param == WM_KEYDOWN or w_param == WM_SYSKEYDOWN):
            kbd = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

            # 核心防死循环校验：检查是否为程序自身合成的按键
            if kbd.dwExtraInfo == SYNTHETIC_PASTE_MAGIC:
                logger.debug("Passed through synthetic paste event (magic matched)")
                return user32.CallNextHookEx(self._h_hook, n_code, w_param, l_param)

            # 检查拦截总开关
            if self._is_enabled:
                if kbd.vkCode == VK_V:
                    # 判定控制键状态
                    ctrl_down = self._is_key_pressed(VK_CONTROL)
                    alt_down = self._is_key_pressed(VK_MENU)
                    win_down = self._is_key_pressed(VK_LWIN) or self._is_key_pressed(VK_RWIN)
                    shift_down = self._is_key_pressed(VK_SHIFT)

                    if ctrl_down and not alt_down and not win_down:
                        should_intercept = False
                        target_hwnd = user32.GetForegroundWindow()

                        if not shift_down:
                            # 1. 常规用户纯 Ctrl + V (所有窗口通用，包括终端与 GUI)
                            should_intercept = True
                            logger.info("Intercepted genuine user Ctrl+V!")
                        elif shift_down and INTERCEPT_TERMINAL_CTRL_SHIFT_V:
                            # 2. 终端环境专属增强：用户按下 Ctrl + Shift + V 试图在终端中粘贴
                            if is_terminal_window(target_hwnd):
                                should_intercept = True
                                logger.info("Intercepted user Ctrl+Shift+V in terminal window!")

                        if should_intercept:
                            # 瞬间抓取当前光标坐标
                            pt = wintypes.POINT()
                            user32.GetCursorPos(ctypes.byref(pt))

                            # 触发外部回调通知 UI 线程展示浮动框
                            try:
                                self.on_trigger_callback(pt.x, pt.y, target_hwnd)
                            except Exception as e:
                                logger.error(f"Error in on_trigger_callback: {e}", exc_info=True)

                            # 返回 1: 阻断该按键向下传递到前台应用程序
                            return 1


        return user32.CallNextHookEx(self._h_hook, n_code, w_param, l_param)

    def _run_hook_loop(self, ready_event: threading.Event) -> None:
        """钩子线程消息泵"""
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hook_proc_ref = HOOKPROC(self._hook_callback)

        # 在 Windows 中，WH_KEYBOARD_LL 属于全局低级钩子，hMod 传 0
        self._h_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc_ref,
            0,
            0
        )

        if not self._h_hook:
            logger.error(f"Failed to install WH_KEYBOARD_LL hook: {kernel32.GetLastError()}")
            ready_event.set()
            return

        logger.info(f"WH_KEYBOARD_LL hook installed successfully, hook handle: {self._h_hook}")
        ready_event.set()

        msg = wintypes.MSG()
        while self._is_running:
            ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if ret <= 0 or msg.message == WM_USER_QUIT:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._h_hook:
            user32.UnhookWindowsHookEx(self._h_hook)
            self._h_hook = None
            logger.info("WH_KEYBOARD_LL hook uninstalled cleanly")
