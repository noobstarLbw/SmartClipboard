"""
配置模块 (Application Configuration)

本模块集中定义整个智能剪贴板应用的所有运行参数、常量和样式设定。
遵循 Explicit over Implicit 原则，严禁散落魔法常数。
"""

from dataclasses import dataclass
from typing import Final


# 粘贴合成魔数 (用于低级键盘钩子识别自身合成的 Ctrl+V，防止死循环递归拦截)
# 选用 64位无符号安全魔数 0xCAFEBABE
SYNTHETIC_PASTE_MAGIC: Final[int] = 0xCAFEBABE

# 历史记录最大保留上限 (用户需求：只保存最近十条)
MAX_HISTORY_ITEMS: Final[int] = 10

# 缩略图生成规格 (像素)
THUMBNAIL_MAX_WIDTH: Final[int] = 72
THUMBNAIL_MAX_HEIGHT: Final[int] = 54

# 剪贴板访问防冲突重试参数 (毫秒)
CLIPBOARD_RETRY_COUNT: Final[int] = 5
CLIPBOARD_RETRY_DELAY_MS: Final[int] = 25

# 快捷键与按键虚拟键码 (Virtual Key Codes)
VK_CONTROL: Final[int] = 0x11
VK_LCONTROL: Final[int] = 0xA2
VK_RCONTROL: Final[int] = 0xA3
VK_V: Final[int] = 0x56
VK_ESCAPE: Final[int] = 0x1B
VK_SHIFT: Final[int] = 0x10
VK_MENU: Final[int] = 0x12  # Alt key
VK_LWIN: Final[int] = 0x5B
VK_RWIN: Final[int] = 0x5C
VK_INSERT: Final[int] = 0x2D

# 键盘事件标志 (Keyboard Event Flags)
KEYEVENTF_EXTENDEDKEY: Final[int] = 0x0001
KEYEVENTF_KEYUP: Final[int] = 0x0002

# 终端环境专属增强配置
INTERCEPT_TERMINAL_CTRL_SHIFT_V: Final[bool] = True  # 在终端环境下同时拦截 Ctrl+Shift+V 快捷键
TERMINAL_PASTE_WITH_SHIFT_INSERT: Final[bool] = True  # 针对终端环境合成 Shift+Insert 进行免乱码可靠粘贴


# 弹窗 UI 样式配置 (Windows Fluent Context Menu 视觉规范)
@dataclass(frozen=True)
class UITheme:
    """UI 视觉主题色彩与尺寸常量"""
    # 窗口尺寸
    WINDOW_WIDTH: int = 360
    WINDOW_HEIGHT: int = 440
    
    # 调色板 (现代桌面质感)
    BG_WINDOW: str = "#F9F9FB"
    BG_CARD: str = "#FFFFFF"
    BG_CARD_HOVER: str = "#EDF2F7"
    BG_CARD_ACTIVE: str = "#E2E8F0"
    
    BORDER_COLOR: str = "#D0D7DE"
    SHADOW_COLOR: str = "#000000"
    
    # 选项卡颜色
    TAB_ACTIVE_BG: str = "#0067C0"      # Windows 经典 Fluent 蓝
    TAB_ACTIVE_FG: str = "#FFFFFF"
    TAB_INACTIVE_BG: str = "#E5E7EB"
    TAB_INACTIVE_FG: str = "#374151"
    
    # 文字颜色
    TEXT_PRIMARY: str = "#1F2937"
    TEXT_SECONDARY: str = "#6B7280"
    TEXT_BADGE: str = "#4B5563"
    TEXT_HINT: str = "#9CA3AF"
    
    # 快捷键角标
    BADGE_BG: str = "#E2E8F0"
    BADGE_FG: str = "#4A5568"
    
    # 字体设定 (优先使用 Windows 11/10 现代字体 Segoe UI / 微软雅黑)
    FONT_FAMILY: str = "Microsoft YaHei UI"
    FONT_SIZE_MAIN: int = 9
    FONT_SIZE_PREVIEW: int = 9
    FONT_SIZE_META: int = 8
    FONT_SIZE_TAB: int = 9


THEME: Final[UITheme] = UITheme()
