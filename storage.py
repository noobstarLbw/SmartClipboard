"""
存储与缓存管理层 (Storage & History Management)

实现线程安全、容量受限的双队列剪贴板历史记录管理器。
遵守 SOLID 原则中的单一职责原则 (SRP) 与开闭原则 (OCP)。
"""

from collections import deque
import logging
import threading
from typing import Callable, List, Optional
from PIL import Image

from config import MAX_HISTORY_ITEMS
from models import ClipboardItem, ClipboardItemType

logger = logging.getLogger("SmartClipboard.Storage")


class ClipboardHistoryManager:
    """
    剪贴板历史管理器
    
    维护双分类独立队列（文本/图片各受限 10 条）。
    具备去重提升机制（重复条目提升至队首，维持最近最常使用 MRU 语义）。
    """

    def __init__(self, max_items: int = MAX_HISTORY_ITEMS):
        self._max_items = max_items
        self._lock = threading.Lock()
        self._text_items: List[ClipboardItem] = []
        self._image_items: List[ClipboardItem] = []
        self._listeners: List[Callable[[], None]] = []

    def add_change_listener(self, listener: Callable[[], None]) -> None:
        """注册历史数据变更监听器"""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_change_listener(self, listener: Callable[[], None]) -> None:
        """注销历史数据变更监听器"""
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _notify_listeners(self) -> None:
        """触发通知变更事件（在外部安全调用，不持锁）"""
        for listener in list(self._listeners):
            try:
                listener()
            except Exception as e:
                logger.error(f"Error in change listener: {e}", exc_info=True)

    def add_text(self, text: str) -> Optional[ClipboardItem]:
        """
        向历史库中添加文本条目
        
        Args:
            text: 捕获的文本
            
        Returns:
            若成功添加或更新返回条目对象；若文本为空则返回 None
        """
        if not text or not text.strip():
            logger.debug("Ignored empty or whitespace-only text")
            return None

        new_item = ClipboardItem.from_text(text)
        should_notify = False

        with self._lock:
            # 检查是否已存在相同哈希的条目
            existing_idx = None
            for idx, item in enumerate(self._text_items):
                if item.content_hash == new_item.content_hash:
                    existing_idx = idx
                    break

            if existing_idx is not None:
                # 若已存在，移至队首并更新时间
                item = self._text_items.pop(existing_idx)
                item.created_at = new_item.created_at
                self._text_items.insert(0, item)
                logger.info(f"Refreshed existing text to top: {item.id}")
                should_notify = True
                ret_item = item
            else:
                # 新增至队首
                self._text_items.insert(0, new_item)
                # 限制队列容量为最近十条
                if len(self._text_items) > self._max_items:
                    discarded = self._text_items.pop()
                    logger.debug(f"Discarded oldest text item: {discarded.id}")
                logger.info(f"Added new text item: {new_item.id}, total texts: {len(self._text_items)}")
                should_notify = True
                ret_item = new_item

        if should_notify:
            self._notify_listeners()

        return ret_item

    def add_image(self, img: Image.Image) -> Optional[ClipboardItem]:
        """
        向历史库中添加图像条目
        
        Args:
            img: 捕获的 PIL Image
            
        Returns:
            若成功添加返回条目对象；若图像无效返回 None
        """
        if img is None:
            return None

        try:
            new_item = ClipboardItem.from_image(img)
        except Exception as e:
            logger.error(f"Failed to create image item: {e}", exc_info=True)
            return None

        should_notify = False
        with self._lock:
            # 检查重复
            existing_idx = None
            for idx, item in enumerate(self._image_items):
                if item.content_hash == new_item.content_hash:
                    existing_idx = idx
                    break

            if existing_idx is not None:
                item = self._image_items.pop(existing_idx)
                item.created_at = new_item.created_at
                self._image_items.insert(0, item)
                logger.info(f"Refreshed existing image to top: {item.id}")
                should_notify = True
                ret_item = item
            else:
                self._image_items.insert(0, new_item)
                if len(self._image_items) > self._max_items:
                    discarded = self._image_items.pop()
                    logger.debug(f"Discarded oldest image item: {discarded.id}")
                logger.info(f"Added new image item: {new_item.id}, total images: {len(self._image_items)}")
                should_notify = True
                ret_item = new_item

        if should_notify:
            self._notify_listeners()

        return ret_item

    def get_texts(self) -> List[ClipboardItem]:
        """获取当前文本历史快照（浅拷贝，防止遍历并发冲突）"""
        with self._lock:
            return list(self._text_items)

    def get_images(self) -> List[ClipboardItem]:
        """获取当前图像历史快照（浅拷贝）"""
        with self._lock:
            return list(self._image_items)

    def clear_texts(self) -> None:
        """清空所有文本历史"""
        with self._lock:
            self._text_items.clear()
        self._notify_listeners()
        logger.info("Cleared all text history")

    def clear_images(self) -> None:
        """清空所有图像历史"""
        with self._lock:
            self._image_items.clear()
        self._notify_listeners()
        logger.info("Cleared all image history")

    def clear_all(self) -> None:
        """清空所有历史"""
        with self._lock:
            self._text_items.clear()
            self._image_items.clear()
        self._notify_listeners()
        logger.info("Cleared all clipboard history")
