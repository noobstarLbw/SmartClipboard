"""
存储与缓存单元测试 (Unit Tests for Clipboard Storage & History)
"""

import threading
import time
import unittest
from PIL import Image

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MAX_HISTORY_ITEMS
from models import ClipboardItem, ClipboardItemType
from storage import ClipboardHistoryManager


class TestClipboardStorage(unittest.TestCase):
    """验证历史记录存储器的核心逻辑、容量与并发安全性"""

    def setUp(self):
        self.mgr = ClipboardHistoryManager(max_items=10)

    def test_text_capacity_limit_ten(self):
        """验证文本队列严格受限于 10 条，超出自动淘汰最旧的一条"""
        for i in range(15):
            self.mgr.add_text(f"Text entry {i}")

        texts = self.mgr.get_texts()
        self.assertEqual(len(texts), 10, "Text list must not exceed 10 items")
        # 最新的应该在最前面
        self.assertEqual(texts[0].content_text, "Text entry 14")
        self.assertEqual(texts[-1].content_text, "Text entry 5")

    def test_text_deduplication_and_mru_promotion(self):
        """验证重复文本不增加总数，而是刷新时间戳并提升至队首"""
        self.mgr.add_text("First message")
        self.mgr.add_text("Second message")
        self.mgr.add_text("Third message")

        # 此时队首为 Third, 第二为 Second, 第三为 First
        texts = self.mgr.get_texts()
        self.assertEqual(len(texts), 3)
        self.assertEqual(texts[0].content_text, "Third message")

        # 重新添加 First message
        time.sleep(0.01)
        refreshed = self.mgr.add_text("First message")
        self.assertIsNotNone(refreshed)

        texts_after = self.mgr.get_texts()
        self.assertEqual(len(texts_after), 3, "Duplicate item should not increase count")
        self.assertEqual(texts_after[0].content_text, "First message", "Duplicate item should be promoted to top")
        self.assertEqual(texts_after[1].content_text, "Third message")
        self.assertEqual(texts_after[2].content_text, "Second message")

    def test_image_capacity_and_thumbnail(self):
        """验证图像队列受限 10 条，且缩略图正确预计算"""
        for i in range(12):
            # 创建不同颜色的测试图片
            img = Image.new("RGB", (200 + i * 10, 150 + i * 10), color=(i * 10, 50, 100))
            self.mgr.add_image(img)

        images = self.mgr.get_images()
        self.assertEqual(len(images), 10, "Image list must not exceed 10 items")
        latest = images[0]
        self.assertIsNotNone(latest.thumbnail)
        self.assertLessEqual(latest.thumbnail.width, 80)
        self.assertLessEqual(latest.thumbnail.height, 60)

    def test_clear_operations(self):
        """验证清空操作"""
        self.mgr.add_text("Sample text")
        img = Image.new("RGB", (50, 50), color="red")
        self.mgr.add_image(img)

        self.assertEqual(len(self.mgr.get_texts()), 1)
        self.assertEqual(len(self.mgr.get_images()), 1)

        self.mgr.clear_texts()
        self.assertEqual(len(self.mgr.get_texts()), 0)
        self.assertEqual(len(self.mgr.get_images()), 1)

        self.mgr.clear_all()
        self.assertEqual(len(self.mgr.get_texts()), 0)
        self.assertEqual(len(self.mgr.get_images()), 0)

    def test_concurrent_multithread_safety(self):
        """验证多线程并发写入不发生死锁或状态损坏"""
        threads = []

        def worker(thread_idx: int):
            for j in range(20):
                self.mgr.add_text(f"Thread {thread_idx} - Text {j}")
                if j % 5 == 0:
                    test_img = Image.new("RGB", (30, 30), color=(thread_idx * 20, j * 10, 50))
                    self.mgr.add_image(test_img)

        for t_id in range(5):
            t = threading.Thread(target=worker, args=(t_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        texts = self.mgr.get_texts()
        images = self.mgr.get_images()
        self.assertEqual(len(texts), 10)
        self.assertEqual(len(images), 10)


if __name__ == "__main__":
    unittest.main()
