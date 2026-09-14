"""
桌面右键级浮动窗界面 (Context-Menu Style UI Popup)

基于 Tkinter 构建具有 Windows Fluent Context Menu 质感的轻量级无边框浮窗。
具备以下特性：
1. 顶部 Tab 切换（📝 文字 / 🖼️ 图片），各展示最多 10 条历史；
2. 智能屏幕边界检测，防止在任务栏或多屏边缘出界；
3. 支持鼠标悬浮卡片高亮与点击即贴；
4. 支持全键盘操作：Tab 切页、1~9 快速粘贴对应项、ESC 快速关闭；
5. 原生失焦 (<FocusOut>) 自动消失，行为与桌面右键菜单一致。
"""

import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional
from PIL import Image, ImageTk

from config import THEME, UITheme
from models import ClipboardItem, ClipboardItemType
from storage import ClipboardHistoryManager

logger = logging.getLogger("SmartClipboard.UI")


class ContextMenuPopup:
    """
    仿 Windows 桌面右键菜单风格的智能剪贴板浮窗
    """

    def __init__(
        self,
        root: tk.Tk,
        storage: ClipboardHistoryManager,
        on_select_item: Callable[[ClipboardItem, int], None],
    ):
        """
        Args:
            root: Tkinter 主根窗口
            storage: 历史数据管理器
            on_select_item: 用户选中某条目进行粘贴的回调 (item, target_hwnd)
        """
        self.root = root
        self.storage = storage
        self.on_select_item = on_select_item

        # 记录触发该次弹窗的目标窗口句柄与当前激活的 Tab
        self.target_hwnd: int = 0
        self.current_tab: str = "text"  # "text" 或 "image"

        # 保持对 PhotoImage 的持久引用，防止 Tkinter 图像被 GC 导致白块
        self._photo_images: List[ImageTk.PhotoImage] = []

        # 创建顶层无边框悬浮窗口
        self.window = tk.Toplevel(root)
        self.window.withdraw()  # 初始隐藏
        self.window.overrideredirect(True)  # 无系统边框
        self.window.attributes("-topmost", True)  # 保持最顶层

        # 构建主视觉框架
        self._build_ui()
        self._bind_events()

        # 监听存储数据变更
        self.storage.add_change_listener(self._on_storage_changed)

    def _build_ui(self) -> None:
        """搭建 UI 层次结构"""
        # 外层 1px 细边框背景容器
        self.outer_border = tk.Frame(
            self.window,
            bg=THEME.BORDER_COLOR,
            bd=1,
            relief=tk.FLAT
        )
        self.outer_border.pack(fill=tk.BOTH, expand=True)

        # 内部主容器
        self.main_container = tk.Frame(
            self.outer_border,
            bg=THEME.BG_WINDOW,
            padx=0,
            pady=0
        )
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 1. 顶部 Header (分类选项卡 + 关闭按钮)
        self.header_frame = tk.Frame(self.main_container, bg=THEME.BG_WINDOW, pady=6, padx=8)
        self.header_frame.pack(fill=tk.X)

        self.tab_text_btn = tk.Label(
            self.header_frame,
            text="📝 文字 (0/10)",
            font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_TAB, "bold"),
            bg=THEME.TAB_ACTIVE_BG,
            fg=THEME.TAB_ACTIVE_FG,
            padx=12,
            pady=4,
            cursor="hand2",
            relief=tk.FLAT
        )
        self.tab_text_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.tab_text_btn.bind("<Button-1>", lambda e: self.switch_tab("text"))

        self.tab_img_btn = tk.Label(
            self.header_frame,
            text="🖼️ 图片 (0/10)",
            font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_TAB, "normal"),
            bg=THEME.TAB_INACTIVE_BG,
            fg=THEME.TAB_INACTIVE_FG,
            padx=12,
            pady=4,
            cursor="hand2",
            relief=tk.FLAT
        )
        self.tab_img_btn.pack(side=tk.LEFT)
        self.tab_img_btn.bind("<Button-1>", lambda e: self.switch_tab("image"))

        # 右侧关闭小叉
        self.close_btn = tk.Label(
            self.header_frame,
            text="✕",
            font=(THEME.FONT_FAMILY, 9),
            bg=THEME.BG_WINDOW,
            fg=THEME.TEXT_SECONDARY,
            padx=8,
            pady=2,
            cursor="hand2"
        )
        self.close_btn.pack(side=tk.RIGHT)
        self.close_btn.bind("<Button-1>", lambda e: self.hide())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.config(fg="#DC2626"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.config(fg=THEME.TEXT_SECONDARY))

        # 分割线
        sep = tk.Frame(self.main_container, height=1, bg=THEME.BORDER_COLOR)
        sep.pack(fill=tk.X)

        # 2. 中间可滚动列表容器
        self.list_canvas = tk.Canvas(
            self.main_container,
            bg=THEME.BG_WINDOW,
            highlightthickness=0,
            bd=0
        )
        self.scrollbar = tk.Scrollbar(
            self.main_container,
            orient=tk.VERTICAL,
            command=self.list_canvas.yview
        )
        self.scrollable_frame = tk.Frame(self.list_canvas, bg=THEME.BG_WINDOW)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))
        )
        self.canvas_window = self.list_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        
        # 窗口大小改变时同步内部容器宽度
        self.list_canvas.bind(
            "<Configure>",
            lambda e: self.list_canvas.itemconfig(self.canvas_window, width=e.width)
        )
        self.list_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.list_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=4)

        # 3. 底部操作说明与快捷操作栏
        sep_bot = tk.Frame(self.main_container, height=1, bg=THEME.BORDER_COLOR)
        sep_bot.pack(fill=tk.X)

        self.footer_frame = tk.Frame(self.main_container, bg=THEME.BG_WINDOW, pady=4, padx=8)
        self.footer_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.hint_label = tk.Label(
            self.footer_frame,
            text="[Tab] 切换 | [1-9] 极速粘贴 | [ESC] 关闭",
            font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_META),
            bg=THEME.BG_WINDOW,
            fg=THEME.TEXT_HINT
        )
        self.hint_label.pack(side=tk.LEFT)

        self.clear_btn = tk.Label(
            self.footer_frame,
            text="清空历史",
            font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_META),
            bg=THEME.BG_WINDOW,
            fg=THEME.TEXT_SECONDARY,
            cursor="hand2"
        )
        self.clear_btn.pack(side=tk.RIGHT)
        self.clear_btn.bind("<Button-1>", lambda e: self._on_clear_clicked())
        self.clear_btn.bind("<Enter>", lambda e: self.clear_btn.config(fg="#DC2626"))
        self.clear_btn.bind("<Leave>", lambda e: self.clear_btn.config(fg=THEME.TEXT_SECONDARY))

    def _bind_events(self) -> None:
        """绑定全局窗口交互事件"""
        # ESC 键立即退出
        self.window.bind("<Escape>", lambda e: self.hide())
        # Tab 键切换分类
        self.window.bind("<Tab>", lambda e: self._toggle_tab())
        # 数字键 1-9 快捷键粘贴
        for num in range(1, 10):
            self.window.bind(str(num), lambda e, n=num: self._paste_by_index(n - 1))
        self.window.bind("0", lambda e: self._paste_by_index(9))

        # 滚轮事件
        self.window.bind_all("<MouseWheel>", self._on_mousewheel)

        # 桌面右键菜单最关键特征：失去焦点时无条件关闭
        self.window.bind("<FocusOut>", self._on_focus_out)

    def _on_focus_out(self, event) -> None:
        """当用户点击了弹窗外部的任何区域，立即销毁隐藏"""
        # 排除子控件内部聚焦转移产生的虚假 FocusOut
        if self.window.focus_get() is None:
            self.hide()

    def _on_mousewheel(self, event) -> None:
        """鼠标滚轮平滑滚动"""
        if self.window.winfo_ismapped():
            self.list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _toggle_tab(self) -> None:
        """Tab 键快速切换分类"""
        new_tab = "image" if self.current_tab == "text" else "text"
        self.switch_tab(new_tab)

    def switch_tab(self, tab: str) -> None:
        """切换当前选项卡并重新渲染列表"""
        self.current_tab = tab
        if tab == "text":
            self.tab_text_btn.config(
                bg=THEME.TAB_ACTIVE_BG, fg=THEME.TAB_ACTIVE_FG, font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_TAB, "bold")
            )
            self.tab_img_btn.config(
                bg=THEME.TAB_INACTIVE_BG, fg=THEME.TAB_INACTIVE_FG, font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_TAB, "normal")
            )
        else:
            self.tab_text_btn.config(
                bg=THEME.TAB_INACTIVE_BG, fg=THEME.TAB_INACTIVE_FG, font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_TAB, "normal")
            )
            self.tab_img_btn.config(
                bg=THEME.TAB_ACTIVE_BG, fg=THEME.TAB_ACTIVE_FG, font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_TAB, "bold")
            )
        self.render_items()

    def _on_clear_clicked(self) -> None:
        """清空当前分类历史"""
        if self.current_tab == "text":
            self.storage.clear_texts()
        else:
            self.storage.clear_images()
        self.render_items()

    def _on_storage_changed(self) -> None:
        """后台存储更新后，若窗口处于显示状态则在主线程调度更新"""
        if self.window.winfo_ismapped():
            self.root.after(0, self._update_tab_counts_and_render)

    def _update_tab_counts_and_render(self) -> None:
        texts = self.storage.get_texts()
        images = self.storage.get_images()
        self.tab_text_btn.config(text=f"📝 文字 ({len(texts)}/10)")
        self.tab_img_btn.config(text=f"🖼️ 图片 ({len(images)}/10)")
        self.render_items()

    def render_items(self) -> None:
        """清空并重构中间卡片列表"""
        # 清空内部控件
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self._photo_images.clear()

        texts = self.storage.get_texts()
        images = self.storage.get_images()

        self.tab_text_btn.config(text=f"📝 文字 ({len(texts)}/10)")
        self.tab_img_btn.config(text=f"🖼️ 图片 ({len(images)}/10)")

        items = texts if self.current_tab == "text" else images

        if not items:
            # 空白占位状态
            empty_frame = tk.Frame(self.scrollable_frame, bg=THEME.BG_WINDOW, pady=60)
            empty_frame.pack(fill=tk.BOTH, expand=True)

            icon_str = "📄" if self.current_tab == "text" else "🖼️"
            lbl_icon = tk.Label(
                empty_frame,
                text=icon_str,
                font=(THEME.FONT_FAMILY, 32),
                bg=THEME.BG_WINDOW,
                fg=THEME.TEXT_HINT
            )
            lbl_icon.pack()

            lbl_txt = tk.Label(
                empty_frame,
                text=f"暂无已复制的{ '文字' if self.current_tab == 'text' else '图片' }",
                font=(THEME.FONT_FAMILY, 10),
                bg=THEME.BG_WINDOW,
                fg=THEME.TEXT_SECONDARY
            )
            lbl_txt.pack(pady=(6, 2))

            lbl_sub = tk.Label(
                empty_frame,
                text="在任何地方复制后将自动保存最近 10 条",
                font=(THEME.FONT_FAMILY, 8),
                bg=THEME.BG_WINDOW,
                fg=THEME.TEXT_HINT
            )
            lbl_sub.pack()
            return

        # 依次渲染条目卡片 (最多 10 条)
        for idx, item in enumerate(items[:10]):
            self._render_card(idx, item)

        # 重置滚动条至最上方
        self.list_canvas.yview_moveto(0.0)

    def _render_card(self, index: int, item: ClipboardItem) -> None:
        """渲染单条卡片"""
        card = tk.Frame(
            self.scrollable_frame,
            bg=THEME.BG_CARD,
            bd=1,
            relief=tk.SOLID,
            padx=8,
            pady=6,
            cursor="hand2"
        )
        card.pack(fill=tk.X, expand=True, padx=4, pady=3)

        # 左侧序号角标
        num_badge = tk.Label(
            card,
            text=f"{index + 1 if index < 9 else (0 if index == 9 else '')}",
            font=(THEME.FONT_FAMILY, 8, "bold"),
            bg=THEME.BADGE_BG,
            fg=THEME.BADGE_FG,
            width=2,
            padx=2,
            pady=1
        )
        num_badge.pack(side=tk.LEFT, padx=(0, 8), anchor="center")

        content_box = tk.Frame(card, bg=THEME.BG_CARD)
        content_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        if item.item_type == ClipboardItemType.TEXT:
            # 文本卡片
            preview = item.get_preview_text(max_len=60)
            lbl_preview = tk.Label(
                content_box,
                text=preview,
                font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_PREVIEW),
                bg=THEME.BG_CARD,
                fg=THEME.TEXT_PRIMARY,
                anchor="w",
                justify=tk.LEFT,
                wraplength=230
            )
            lbl_preview.pack(fill=tk.X, anchor="w")

            meta_text = f"{item.get_time_str()}  ·  {item.char_count} 字符"
            lbl_meta = tk.Label(
                content_box,
                text=meta_text,
                font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_META),
                bg=THEME.BG_CARD,
                fg=THEME.TEXT_SECONDARY,
                anchor="w"
            )
            lbl_meta.pack(fill=tk.X, anchor="w", pady=(2, 0))

        else:
            # 图像卡片
            img_row = tk.Frame(content_box, bg=THEME.BG_CARD)
            img_row.pack(fill=tk.X, anchor="w")

            if item.thumbnail:
                try:
                    photo = ImageTk.PhotoImage(item.thumbnail)
                    self._photo_images.append(photo)
                    lbl_thumb = tk.Label(img_row, image=photo, bg=THEME.BG_CARD)
                    lbl_thumb.pack(side=tk.LEFT, padx=(0, 8))
                except Exception as e:
                    logger.error(f"Failed to render thumbnail: {e}")

            info_col = tk.Frame(img_row, bg=THEME.BG_CARD)
            info_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            dims_str = f"{item.image_dimensions[0]} × {item.image_dimensions[1]}" if item.image_dimensions else "图像"
            lbl_dims = tk.Label(
                info_col,
                text=dims_str,
                font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_PREVIEW, "bold"),
                bg=THEME.BG_CARD,
                fg=THEME.TEXT_PRIMARY,
                anchor="w"
            )
            lbl_dims.pack(fill=tk.X, anchor="w")

            lbl_time = tk.Label(
                info_col,
                text=item.get_time_str(),
                font=(THEME.FONT_FAMILY, THEME.FONT_SIZE_META),
                bg=THEME.BG_CARD,
                fg=THEME.TEXT_SECONDARY,
                anchor="w"
            )
            lbl_time.pack(fill=tk.X, anchor="w", pady=(2, 0))

        # 右侧操作提示
        action_lbl = tk.Label(
            card,
            text="粘贴",
            font=(THEME.FONT_FAMILY, 8),
            bg=THEME.BG_CARD,
            fg="#2563EB",
            cursor="hand2"
        )
        action_lbl.pack(side=tk.RIGHT, padx=4)

        # 绑定整卡点击事件与鼠标悬停高亮
        all_widgets = [card, num_badge, content_box, action_lbl]
        for child in content_box.winfo_children():
            all_widgets.append(child)
            if isinstance(child, tk.Frame):
                all_widgets.extend(child.winfo_children())

        def _on_enter(e):
            for w in all_widgets:
                if w != num_badge:
                    w.config(bg=THEME.BG_CARD_HOVER)

        def _on_leave(e):
            for w in all_widgets:
                if w != num_badge:
                    w.config(bg=THEME.BG_CARD)

        def _on_click(e):
            self._do_select(item)

        for w in all_widgets:
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)
            w.bind("<Button-1>", _on_click)

    def _paste_by_index(self, index: int) -> None:
        """通过数字键 1~9 直接粘贴对应下标的条目"""
        items = self.storage.get_texts() if self.current_tab == "text" else self.storage.get_images()
        if 0 <= index < len(items):
            self._do_select(items[index])

    def _do_select(self, item: ClipboardItem) -> None:
        """用户选中某条记录执行粘贴"""
        logger.info(f"User selected item to paste: {item.id}")
        # 1. 立即隐藏浮动窗口
        self.hide()
        # 2. 调度执行粘贴合成
        self.on_select_item(item, self.target_hwnd)

    def show_at(self, cursor_x: int, cursor_y: int, target_hwnd: int) -> None:
        """在指定屏幕光标坐标旁弹出浮窗（具备边界自适应防出界算法）"""
        # 若窗口尚未显示，记录目标窗口句柄；若已显示，保留原有效目标句柄防止覆盖
        if not self.window.winfo_ismapped() or not self.target_hwnd:
            self.target_hwnd = target_hwnd

        # 刷新视图列表
        self.render_items()

        # 计算并矫正屏幕坐标
        win_w = THEME.WINDOW_WIDTH
        win_h = THEME.WINDOW_HEIGHT

        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()

        # 默认显示在光标右下方偏移 5 像素处
        pos_x = cursor_x + 5
        pos_y = cursor_y + 5

        # 右边缘防出界：若超出屏幕右侧，则显示在光标左侧
        if pos_x + win_w > screen_w:
            pos_x = max(10, cursor_x - win_w - 5)

        # 下边缘防出界：若超出屏幕下方（例如靠近任务栏），则向上弹出
        if pos_y + win_h > screen_h - 40:  # 预留任务栏高度
            pos_y = max(10, cursor_y - win_h - 5)

        self.window.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.window.deiconify()
        self.window.attributes("-topmost", True)
        self.window.lift()
        self.window.focus_force()
        logger.debug(f"Popup shown at ({pos_x}, {pos_y}) for target hwnd: {target_hwnd}")

    def hide(self) -> None:
        """隐藏并重置浮窗"""
        if self.window.winfo_ismapped():
            self.window.withdraw()
            logger.debug("Popup hidden")
