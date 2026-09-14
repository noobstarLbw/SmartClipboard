"""
系统托盘管理层 (System Tray Manager)

基于 pystray 在 Windows 任务栏通知区域提供后台常驻管理。
包含：
1. 动态自绘高清托盘图标 (无须外挂 .ico 资源，自包含单文件友好)；
2. 一键暂停 / 恢复全局 Ctrl+V 拦截开关；
3. 清空历史记录；
4. 退出程序。
"""

import logging
import threading
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item, Menu

from autostart import is_autostart_enabled, set_autostart

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

    def start(self) -> None:
        """在后台线程中启动系统托盘图标"""
        tray_image = create_default_tray_image()

        menu = Menu(
            item("📋 显示剪贴板", lambda icon, item: self.on_show_popup(), default=True),
            item(self._get_toggle_text, self._on_toggle_clicked),
            item(self._get_autostart_text, self._on_autostart_clicked),
            item("🗑️ 清空所有记录", lambda icon, item: self.on_clear_history()),
            Menu.SEPARATOR,
            item("❌ 退出软件", lambda icon, item: self.stop()),
        )

        self._icon = pystray.Icon(
            name="SmartClipboard",
            icon=tray_image,
            title="智能剪贴板 (按 Ctrl+V 唤起)",
            menu=menu
        )

        self._tray_thread = threading.Thread(target=self._icon.run, daemon=True, name="TrayThread")
        self._tray_thread.start()
        logger.info("System tray initialized and running")

    def stop(self) -> None:
        """停止托盘并通知主程序退出"""
        if self._icon:
            try:
                self._icon.stop()
            except Exception as e:
                logger.error(f"Error stopping tray icon: {e}")
        self.on_exit_app()
