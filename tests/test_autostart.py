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

    def test_autostart_toggle_roundtrip(self):
        initial_state = is_autostart_enabled()
        try:
            success = set_autostart(True)
            if not success and os.environ.get("CI"):
                self.skipTest("Registry write restricted in CI runner container")
            self.assertTrue(success)
            self.assertTrue(is_autostart_enabled())

            success_off = set_autostart(False)
            self.assertTrue(success_off)
            self.assertFalse(is_autostart_enabled())
        finally:
            set_autostart(initial_state)


if __name__ == "__main__":
    unittest.main()
