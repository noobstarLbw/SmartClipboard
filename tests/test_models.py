"""
数据模型单元测试 (Unit Tests for Models)
"""

import unittest
from PIL import Image

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import ClipboardItem, ClipboardItemType


class TestModels(unittest.TestCase):
    """验证条目模型与工厂方法"""

    def test_text_item_creation(self):
        text = "  Hello World\nLine 2\tTab  "
        item = ClipboardItem.from_text(text)

        self.assertEqual(item.item_type, ClipboardItemType.TEXT)
        self.assertEqual(item.content_text, text)
        self.assertEqual(item.char_count, len(text))
        self.assertTrue(len(item.content_hash) > 0)

        # 验证紧凑预览截断
        preview = item.get_preview_text(max_len=15)
        self.assertNotIn("\n", preview)
        self.assertTrue(preview.endswith("..."))

    def test_image_item_creation(self):
        img = Image.new("RGB", (400, 300), color="blue")
        item = ClipboardItem.from_image(img)

        self.assertEqual(item.item_type, ClipboardItemType.IMAGE)
        self.assertEqual(item.image_dimensions, (400, 300))
        self.assertIsNotNone(item.thumbnail)
        self.assertLessEqual(item.thumbnail.width, 72)
        self.assertLessEqual(item.thumbnail.height, 54)


if __name__ == "__main__":
    unittest.main()
