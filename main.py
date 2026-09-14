"""
应用程序主程序与装配入口 (Application Main Entry)

负责模块组装、DPI 高清适配、日志流水线、主线程调度与优雅退出管理。
"""

import ctypes
from ctypes import wintypes
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import tkinter as tk
from typing import Optional

# 高清 DPI 适配 (防止高分屏模糊)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from config import THEME
from clipboard_listener import ClipboardListener
from keyboard_hook import KeyboardHook
from models import ClipboardItem
from paste_synthesizer import execute_paste
from storage import ClipboardHistoryManager
from tray_app import TrayApp
from ui_popup import ContextMenuPopup
from win32_clipboard import (
    get_clipboard_text,
    get_clipboard_image,
    is_text_available,
    is_image_available,
)


def setup_logging() -> None:
    """初始化结构化日志系统 (输出至控制台与轮转日志文件)"""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    log_file = os.path.join(base_dir, "clipboard_app.log")
    
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(threadName)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 控制台输出流
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # 磁盘文件轮转输出流 (最大 5MB，保留 2 份备份)
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Failed to create log file handler: {e}")


logger = logging.getLogger("SmartClipboard.Main")


class SmartClipboardApp:
    """智能剪贴板桌面应用总控"""

    def __init__(self):
        logger.info("Initializing Smart Clipboard Manager Application...")

        # 1. 存储核心
        self.storage = ClipboardHistoryManager()

        # 2. 隐藏的 Tkinter 根主循环宿主
        self.root = tk.Tk()
        self.root.withdraw()

        # 3. 仿桌面右键浮窗 UI
        self.ui = ContextMenuPopup(
            root=self.root,
            storage=self.storage,
            on_select_item=self._handle_paste_item
        )

        # 4. 剪贴板事件监听器
        self.listener = ClipboardListener(storage=self.storage)

        # 5. 低级键盘钩子
        self.hook = KeyboardHook(on_trigger_callback=self._on_ctrl_v_triggered)

        # 6. 系统托盘
        self.tray = TrayApp(
            on_show_popup=self._show_ui_from_tray,
            on_toggle_hook=self._toggle_hook,
            is_hook_enabled_getter=self.hook.is_enabled,
            on_clear_history=self.storage.clear_all,
            on_exit_app=self.exit_app
        )

        # 7. 初始预加载当前剪贴板已有内容 (提升开箱体验)
        self._seed_initial_clipboard()

    def _seed_initial_clipboard(self) -> None:
        """冷启动时将当前剪贴板现有内容作为第 1 条历史自动抓取"""
        try:
            if is_text_available():
                txt = get_clipboard_text()
                if txt:
                    self.storage.add_text(txt)
            if is_image_available():
                img = get_clipboard_image()
                if img:
                    self.storage.add_image(img)
        except Exception as e:
            logger.warning(f"Failed to seed initial clipboard: {e}")

    def _on_ctrl_v_triggered(self, cursor_x: int, cursor_y: int, target_hwnd: int) -> None:
        """
        低级键盘钩子捕获到用户 Ctrl+V 时触发的回调
        (在钩子后台线程调用，通过 after 跨线程安全投递至 Tkinter 主 UI 线程)
        """
        logger.info(f"Hotkey triggered Ctrl+V, posting to UI thread at ({cursor_x}, {cursor_y})")
        self.root.after(0, lambda: self.ui.show_at(cursor_x, cursor_y, target_hwnd))

    def _show_ui_from_tray(self) -> None:
        """从托盘菜单点击唤起浮窗 (居中弹出)"""
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        self.root.after(0, lambda: self.ui.show_at(pt.x, pt.y, fg_hwnd))

    def _toggle_hook(self, enabled: bool) -> None:
        """切换全局按键拦截状态"""
        self.hook.set_enabled(enabled)

    def _handle_paste_item(self, item: ClipboardItem, target_hwnd: int) -> None:
        """执行条目粘贴并临时阻断监听器防重入"""
        def on_before_write():
            self.listener.set_ignore_internal_event(True)

        def on_after_paste():
            # 延时 150ms 重新允许剪贴板监听
            self.root.after(150, lambda: self.listener.set_ignore_internal_event(False))

        execute_paste(
            item=item,
            target_hwnd=target_hwnd,
            on_before_write=on_before_write,
            on_after_paste=on_after_paste
        )

    def run(self) -> None:
        """启动所有服务并运行主 UI 消息泵"""
        logger.info("Starting background services...")
        self.listener.start()
        self.hook.start()
        self.tray.start()

        logger.info("Smart Clipboard Manager running. Listening for Ctrl+V...")
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt, shutting down...")
        finally:
            self.exit_app()

    def exit_app(self) -> None:
        """安全释放 Win32 钩子与线程资源退出进程"""
        logger.info("Terminating Smart Clipboard Application...")
        try:
            self.hook.stop()
        except Exception:
            pass
        try:
            self.listener.stop()
        except Exception:
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)


def main():
    setup_logging()
    app = SmartClipboardApp()
    app.run()


if __name__ == "__main__":
    main()
