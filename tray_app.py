"""
系统托盘管理层 (System Tray Manager)

基于 pystray 在 Windows 任务栏通知区域提供后台常驻管理。
包含：
1. 动态自绘高清托盘图标 (无须外挂 .ico 资源，自包含单文件友好)；
2. 一键暂停 / 恢复全局 Ctrl+V 拦截开关；
3. 开机自启动开关；
4. 管理员模式检测与一键提权重启（确保完全控制管理员权限终端）；
5. 清空历史记录；
6. 退出程序。
"""

import ctypes
import logging
import os
import sys
import threading
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item, Menu

from autostart import is_autostart_enabled, set_autostart
from paste_synthesizer import is_current_process_admin

logger = logging.getLogger("SmartClipboard.Tray")


def create_default_tray_image(size: int = 64) -> Image.Image:
    """
    程序自绘现代剪贴板矢量风格托盘图标 (64x64 RGBA)
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 绘制深蓝底板卡片
    margin = 8
    draw.rounded_rectangle(
        [margin, margin + 4, size - margin, size - margin],
        radius=8,
        fill="#0078D4",
        outline="#005A9E",
        width=2
    )

    # 绘制剪贴板金属顶夹
    clip_w = 24
    clip_h = 10
    cx = size // 2
    draw.rounded_rectangle(
        [cx - clip_w // 2, margin - 2, cx + clip_w // 2, margin + clip_h],
        radius=3,
        fill="#E5E7EB",
        outline="#9CA3AF",
        width=2
    )

    # 绘制板上的三道文本线
    line_x1 = margin + 12
    line_x2 = size - margin - 12
    y_starts = [margin + 18, margin + 27, margin + 36]
    for y in y_starts:
        draw.rounded_rectangle([line_x1, y, line_x2, y + 3], radius=1, fill="#FFFFFF")

    return image


def restart_as_admin() -> bool:
    """
    通过 ShellExecuteW 以管理员权限请求 UAC 提权重新启动当前程序
    
    返回是否成功向系统发起提权启动请求。
    """
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            args = ""
        else:
            exe = sys.executable
            args = f'"{os.path.abspath(sys.argv[0])}"'
            if len(sys.argv) > 1:
                args += " " + " ".join(f'"{a}"' for a in sys.argv[1:])

        SW_NORMAL = 1
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, SW_NORMAL)
        return ret > 32
    except Exception as e:
        logger.error(f"Failed to elevate process: {e}")
        return False


class TrayApp:
    """系统托盘应用管理器"""

    def __init__(
        self,
        on_show_popup: Callable[[], None],
        on_toggle_hook: Callable[[bool], None],
        is_hook_enabled_getter: Callable[[], bool],
        on_clear_history: Callable[[], None],
        on_exit_app: Callable[[], None],
    ):
        self.on_show_popup = on_show_popup
        self.on_toggle_hook = on_toggle_hook
        self.is_hook_enabled_getter = is_hook_enabled_getter
        self.on_clear_history = on_clear_history
        self.on_exit_app = on_exit_app

        self._icon: Optional[pystray.Icon] = None
        self._tray_thread: Optional[threading.Thread] = None

    def _get_toggle_text(self, item) -> str:
        enabled = self.is_hook_enabled_getter()
        return "✓ 拦截 Ctrl+V (已开启)" if enabled else "  拦截 Ctrl+V (已暂停)"

    def _on_toggle_clicked(self, icon, item) -> None:
        new_state = not self.is_hook_enabled_getter()
        self.on_toggle_hook(new_state)
        icon.update_menu()

    def _get_autostart_text(self, item) -> str:
        enabled = is_autostart_enabled()
        return "✓ 开机自启动 (已开启)" if enabled else "  开机自启动 (未开启)"

    def _on_autostart_clicked(self, icon, item) -> None:
        new_state = not is_autostart_enabled()
        set_autostart(new_state)
        icon.update_menu()

    def _on_restart_admin_clicked(self, icon, item) -> None:
        """用户点击以管理员身份重启"""
        logger.info("User requested elevation to Administrator...")
        if restart_as_admin():
            self.stop()

    def start(self) -> None:
        """在后台线程中启动系统托盘图标"""
        tray_image = create_default_tray_image()
        is_admin = is_current_process_admin()

        menu_items = [
            item("📋 显示剪贴板", lambda icon, item: self.on_show_popup(), default=True),
            item(self._get_toggle_text, self._on_toggle_clicked),
            item(self._get_autostart_text, self._on_autostart_clicked),
        ]

        if is_admin:
            menu_items.append(item("🛡️ 管理员模式 (已就绪)", lambda icon, item: None, enabled=False))
        else:
            menu_items.append(item("🛡️ 以管理员身份重启", self._on_restart_admin_clicked))

        menu_items.extend([
            item("🗑️ 清空所有记录", lambda icon, item: self.on_clear_history()),
            Menu.SEPARATOR,
            item("❌ 退出软件", lambda icon, item: self.stop()),
        ])

        menu = Menu(*menu_items)

        tooltip = "智能剪贴板 (管理员模式 · 按 Ctrl+V 唤起)" if is_admin else "智能剪贴板 (按 Ctrl+V 唤起)"

        self._icon = pystray.Icon(
            name="SmartClipboard",
            icon=tray_image,
            title=tooltip,
            menu=menu
        )

        self._tray_thread = threading.Thread(target=self._icon.run, daemon=True, name="TrayThread")
        self._tray_thread.start()
        logger.info(f"System tray initialized and running (is_admin={is_admin})")

    def stop(self) -> None:
        """停止托盘并通知主程序退出"""
        if self._icon:
            try:
                self._icon.stop()
            except Exception as e:
                logger.error(f"Error stopping tray icon: {e}")
        self.on_exit_app()
