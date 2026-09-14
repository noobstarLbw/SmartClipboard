"""
数据模型层 (Data Models)

定义剪贴板历史条目的实体结构与值对象。
遵守 Defensive Programming 原则，确保所有外部输入和转换均具备类型安全与边界保护。
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import time
from typing import Optional, Tuple
from PIL import Image

from config import THUMBNAIL_MAX_WIDTH, THUMBNAIL_MAX_HEIGHT


class ClipboardItemType(str, Enum):
    """剪贴板数据类型枚举"""
    TEXT = "text"
    IMAGE = "image"


@dataclass
class ClipboardItem:
    """
    剪贴板历史记录条目实体
    
    Attributes:
        id: 条目全局唯一标识
        item_type: 数据类型 (TEXT / IMAGE)
        content_text: 文本内容 (若为文本类型)
        content_image: PIL 图像对象 (若为图像类型)
        thumbnail: 用于 UI 渲染的高性能微缩图 (若为图像类型)
        created_at: 捕获时间戳
        content_hash: 内容哈希指纹，用于高效 O(1) 去重
        char_count: 文本字符数 (仅文本)
        image_dimensions: 原始图像分辨率 (仅图像)
    """
    id: str
    item_type: ClipboardItemType
    content_text: Optional[str] = None
    content_image: Optional[Image.Image] = None
    thumbnail: Optional[Image.Image] = None
    created_at: float = 0.0
    content_hash: str = ""
    char_count: int = 0
    image_dimensions: Optional[Tuple[int, int]] = None

    @classmethod
    def from_text(cls, text: str) -> "ClipboardItem":
        """
        工厂方法：从原生字符串构造文本记录条目
        
        Args:
            text: 捕获的文本内容
            
        Returns:
            经过校验和指纹计算的 ClipboardItem 实例
        """
        if not isinstance(text, str):
            raise TypeError(f"Expected str for text item, got {type(text)}")
        
        now = time.time()
        # 计算 SHA-256 指纹前 16 位作为内容去重判据
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
        item_id = f"txt_{int(now * 1000)}_{digest[:6]}"
        
        return cls(
            id=item_id,
            item_type=ClipboardItemType.TEXT,
            content_text=text,
            created_at=now,
            content_hash=digest,
            char_count=len(text)
        )

    @classmethod
    def from_image(cls, img: Image.Image) -> "ClipboardItem":
        """
        工厂方法：从 PIL.Image 构造图像记录条目并预计算高质量微缩图
        
        Args:
            img: 捕获的 PIL 图像对象
            
        Returns:
            包含微缩图和分辨率特征的 ClipboardItem 实例
        """
        if not isinstance(img, Image.Image):
            raise TypeError(f"Expected PIL.Image for image item, got {type(img)}")
        
        now = time.time()
        # 针对图片，采用像素特征采样与尺寸哈希进行去重
        img_rgb = img.convert("RGB")
        orig_size = img_rgb.size
        
        # 缩放至 16x16 计算感知结构哈希，避免因整图全量哈希带来卡顿
        small_sample = img_rgb.resize((16, 16), Image.Resampling.BOX)
        digest = hashlib.sha256(small_sample.tobytes() + str(orig_size).encode()).hexdigest()[:16]
        item_id = f"img_{int(now * 1000)}_{digest[:6]}"
        
        # 预计算 UI 缩略图，并限制在预设宽高内等比例缩放
        thumb = img_rgb.copy()
        thumb.thumbnail((THUMBNAIL_MAX_WIDTH, THUMBNAIL_MAX_HEIGHT), Image.Resampling.LANCZOS)
        
        return cls(
            id=item_id,
            item_type=ClipboardItemType.IMAGE,
            content_image=img_rgb,
            thumbnail=thumb,
            created_at=now,
            content_hash=digest,
            image_dimensions=orig_size
        )

    def get_preview_text(self, max_len: int = 50) -> str:
        """获取压缩为单行预览的展示文本"""
        if not self.content_text:
            return ""
        # 替换多行换行符为紧凑展示
        cleaned = " ".join(self.content_text.split())
        if len(cleaned) > max_len:
            return cleaned[:max_len] + "..."
        return cleaned

    def get_time_str(self) -> str:
        """获取易读的捕获时间字符串 (HH:MM:SS)"""
        return time.strftime("%H:%M:%S", time.localtime(self.created_at))
