"""
开机自启动模块单元测试 (Unit Tests for Autostart)
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autostart import is_autostart_enabled, set_autostart, get_current_executable_path


class TestAutostart(unittest.TestCase):
    """验证开机自启动注册表操作的幂等性与安全性"""

    def test_get_current_executable_path(self):
        path = get_current_executable_path()
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(os.path.exists(path) or getattr(sys, "frozen", False))

    def test_autostart_toggle_roundtrip(self):
        # 记录初始状态
        initial_state = is_autostart_enabled()
        try:
            # 开启
            success = set_autostart(True)
            self.assertTrue(success)
            self.assertTrue(is_autostart_enabled())

            # 关闭
            success = set_autostart(False)
            self.assertTrue(success)
            self.assertFalse(is_autostart_enabled())
        finally:
            # 还原初始状态
            set_autostart(initial_state)


if __name__ == "__main__":
    unittest.main()
