"""
开机自启动管理模块 (Windows Autostart Manager)

通过管理 Windows 用户级注册表实现免管理员权限的开机自启动。
注册表路径: HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
"""

import logging
import os
import sys
import winreg
from typing import Optional

logger = logging.getLogger("SmartClipboard.Autostart")

APP_REG_NAME = "SmartClipboardManager"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_current_executable_path() -> str:
    """获取当前可执行文件或脚本的绝对路径"""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))


def is_autostart_enabled() -> bool:
    """
    检查是否已配置开机自启
    
    Returns:
        若注册表中存在对应项且路径匹配则返回 True
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_REG_NAME)
            current_path = f'"{get_current_executable_path()}"'
            return value.strip() == current_path.strip()
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"Failed to check autostart status: {e}")
        return False


def set_autostart(enabled: bool) -> bool:
    """
    启用或禁用开机自启
    
    Args:
        enabled: True 为开启，False 为关闭
        
    Returns:
        操作是否成功
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                exe_path = f'"{get_current_executable_path()}"'
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, exe_path)
                logger.info(f"Enabled autostart with command: {exe_path}")
                return True
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                    logger.info("Disabled autostart")
                except FileNotFoundError:
                    pass
                return True
    except Exception as e:
        logger.error(f"Failed to set autostart to {enabled}: {e}", exc_info=True)
        return False
