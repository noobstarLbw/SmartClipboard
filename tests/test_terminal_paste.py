"""
单元测试：终端环境窗口识别与智能按键合成验证 (Terminal Environment Paste Tests)
"""

import unittest
from unittest.mock import patch, MagicMock
import ctypes

from config import (
    VK_CONTROL,
    VK_V,
    VK_SHIFT,
    VK_INSERT,
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    SYNTHETIC_PASTE_MAGIC,
)
from models import ClipboardItem, ClipboardItemType
from paste_synthesizer import (
    is_terminal_window,
    is_current_process_admin,
    TERMINAL_WINDOW_CLASSES,
    TERMINAL_PROCESS_NAMES,
    execute_paste,
)


class TestTerminalPaste(unittest.TestCase):
    """验证终端检测逻辑与智能粘贴键分发"""

    def test_terminal_window_classes_set(self):
        """确保预定义的主要终端类名完整"""
        self.assertIn("ConsoleWindowClass", TERMINAL_WINDOW_CLASSES)
        self.assertIn("CASCADIA_HOSTING_WINDOW_CLASS", TERMINAL_WINDOW_CLASSES)
        self.assertIn("mintty", TERMINAL_WINDOW_CLASSES)
        self.assertIn("PuTTY", TERMINAL_WINDOW_CLASSES)

    def test_terminal_process_names_set(self):
        """确保预定义的主要终端进程名完整"""
        self.assertIn("cmd.exe", TERMINAL_PROCESS_NAMES)
        self.assertIn("powershell.exe", TERMINAL_PROCESS_NAMES)
        self.assertIn("windowsterminal.exe", TERMINAL_PROCESS_NAMES)
        self.assertIn("mintty.exe", TERMINAL_PROCESS_NAMES)
        self.assertIn("wsl.exe", TERMINAL_PROCESS_NAMES)

    @patch("paste_synthesizer.user32.IsWindow", return_value=True)
    @patch("paste_synthesizer.get_window_class_name")
    @patch("paste_synthesizer.get_process_name_by_hwnd")
    def test_is_terminal_by_class_name(self, mock_proc, mock_cls, mock_is_window):
        """验证通过窗口类名准确识别各种终端"""
        # 测试 conhost / CMD / PowerShell
        mock_cls.return_value = "ConsoleWindowClass"
        mock_proc.return_value = "unknown.exe"
        self.assertTrue(is_terminal_window(12345))

        # 测试 Windows Terminal
        mock_cls.return_value = "CASCADIA_HOSTING_WINDOW_CLASS"
        mock_proc.return_value = "unknown.exe"
        self.assertTrue(is_terminal_window(12345))

        # 测试 Git Bash (mintty)
        mock_cls.return_value = "mintty"
        mock_proc.return_value = "mintty.exe"
        self.assertTrue(is_terminal_window(12345))

        # 测试 PuTTY
        mock_cls.return_value = "PuTTY"
        self.assertTrue(is_terminal_window(12345))

    @patch("paste_synthesizer.user32.IsWindow", return_value=True)
    @patch("paste_synthesizer.get_window_class_name")
    @patch("paste_synthesizer.get_process_name_by_hwnd")
    def test_is_terminal_by_process_name(self, mock_proc, mock_cls, mock_is_window):
        """验证当窗口类名未知时，通过进程名识别终端"""
        mock_cls.return_value = "CustomWrapperClass"

        # 测试 cmd.exe
        mock_proc.return_value = "cmd.exe"
        self.assertTrue(is_terminal_window(12345))

        # 测试 powershell.exe
        mock_proc.return_value = "powershell.exe"
        self.assertTrue(is_terminal_window(12345))

        # 测试 wsl.exe
        mock_proc.return_value = "wsl.exe"
        self.assertTrue(is_terminal_window(12345))

        # 测试 git-bash mintty.exe
        mock_proc.return_value = "mintty.exe"
        self.assertTrue(is_terminal_window(12345))

    @patch("paste_synthesizer.user32.IsWindow", return_value=True)
    @patch("paste_synthesizer.get_window_class_name")
    @patch("paste_synthesizer.get_process_name_by_hwnd")
    def test_non_terminal_window(self, mock_proc, mock_cls, mock_is_window):
        """验证非终端应用（记事本、Chrome、Word等）正确判定为 False"""
        # 测试记事本
        mock_cls.return_value = "Notepad"
        mock_proc.return_value = "notepad.exe"
        self.assertFalse(is_terminal_window(12345))

        # 测试 Chrome
        mock_cls.return_value = "Chrome_WidgetWin_1"
        mock_proc.return_value = "chrome.exe"
        self.assertFalse(is_terminal_window(12345))

        # 测试 Word
        mock_cls.return_value = "OpusApp"
        mock_proc.return_value = "winword.exe"
        self.assertFalse(is_terminal_window(12345))

    def test_invalid_hwnd(self):
        """验证空句柄与无效句柄返回 False"""
        self.assertFalse(is_terminal_window(0))
        self.assertFalse(is_terminal_window(None))

    def test_is_current_process_admin_boolean(self):
        """验证管理员权限状态查询返回布尔值"""
        result = is_current_process_admin()
        self.assertIsInstance(result, bool)

    @patch("paste_synthesizer.set_clipboard_text", return_value=True)
    @patch("paste_synthesizer.activate_target_window", return_value=True)
    @patch("paste_synthesizer.is_terminal_window", return_value=True)
    @patch("paste_synthesizer.user32.keybd_event")
    @patch("paste_synthesizer.time.sleep")
    def test_terminal_paste_synthesizes_shift_insert(
        self, mock_sleep, mock_keybd, mock_is_term, mock_activate, mock_set_clip
    ):
        """验证针对终端目标窗口时，合成 Shift + Insert 组合键"""
        import threading
        done_event = threading.Event()

        item = ClipboardItem(
            id="item_term_1",
            item_type=ClipboardItemType.TEXT,
            content_text="echo 'hello terminal'"
        )

        execute_paste(item, target_hwnd=99999, on_after_paste=lambda: done_event.set())

        self.assertTrue(done_event.wait(timeout=2.0))

        # 检查 keybd_event 的调用序列包含 VK_SHIFT 和 VK_INSERT
        called_vks = [call.args[0] for call in mock_keybd.call_args_list]
        self.assertIn(VK_SHIFT, called_vks)
        self.assertIn(VK_INSERT, called_vks)
        self.assertNotIn(VK_CONTROL, called_vks)
        self.assertNotIn(VK_V, called_vks)

    @patch("paste_synthesizer.set_clipboard_text", return_value=True)
    @patch("paste_synthesizer.activate_target_window", return_value=True)
    @patch("paste_synthesizer.is_terminal_window", return_value=False)
    @patch("paste_synthesizer.user32.keybd_event")
    @patch("paste_synthesizer.time.sleep")
    def test_gui_paste_synthesizes_ctrl_v(
        self, mock_sleep, mock_keybd, mock_is_term, mock_activate, mock_set_clip
    ):
        """验证针对常规 GUI 目标窗口时，合成 Ctrl + V 组合键"""
        import threading
        done_event = threading.Event()

        item = ClipboardItem(
            id="item_gui_1",
            item_type=ClipboardItemType.TEXT,
            content_text="hello GUI"
        )

        execute_paste(item, target_hwnd=88888, on_after_paste=lambda: done_event.set())

        self.assertTrue(done_event.wait(timeout=2.0))

        called_vks = [call.args[0] for call in mock_keybd.call_args_list]
        self.assertIn(VK_CONTROL, called_vks)
        self.assertIn(VK_V, called_vks)
        self.assertNotIn(VK_INSERT, called_vks)




if __name__ == "__main__":
    unittest.main()
