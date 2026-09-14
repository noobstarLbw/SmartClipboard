"""
Windows 原生剪贴板驱动层 (Win32 Clipboard Driver)

本模块直接封装 Win32 原生剪贴板 API，提供严格的 64 位类型安全与资源管理。
遵循 Defensive Programming：
1. 包含针对剪贴板锁争用的重试退避机制；
2. 使用 RAII / 上下文管理器确保 OpenClipboard 必有 CloseClipboard；
3. 显式配置 argtypes 与 restype，彻底杜绝 64 位指针截断 (Access Violation)。
"""

import ctypes
from ctypes import wintypes
import io
import logging
import time
from typing import Optional
from PIL import Image, ImageGrab

from config import CLIPBOARD_RETRY_COUNT, CLIPBOARD_RETRY_DELAY_MS

logger = logging.getLogger("SmartClipboard.Win32")

# Windows API 句柄与常量
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_BITMAP = 2
CF_DIB = 8
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# 显式配置 Win32 API 参数类型与返回值类型（防止 64 位环境下指针被当做 32 位 int 截断）
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL

kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p

kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL

user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL

user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL

user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE

user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL


class ClipboardContext:
    """
    剪贴板上下文管理器 (RAII 模式)
    
    自动重试打开剪贴板，退出时无条件调用 CloseClipboard。
    """
    def __init__(self, hwnd: int = 0, retries: int = CLIPBOARD_RETRY_COUNT, delay_ms: int = CLIPBOARD_RETRY_DELAY_MS):
        self.hwnd = hwnd
        self.retries = retries
        self.delay_sec = delay_ms / 1000.0
        self.is_open = False

    def __enter__(self) -> bool:
        for attempt in range(self.retries):
            if user32.OpenClipboard(self.hwnd):
                self.is_open = True
                return True
            time.sleep(self.delay_sec)
        logger.warning(f"Failed to open clipboard after {self.retries} attempts")
        return False

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_open:
            user32.CloseClipboard()
            self.is_open = False


def is_text_available() -> bool:
    """查询当前系统剪贴板是否存在 Unicode 文本"""
    return bool(user32.IsClipboardFormatAvailable(CF_UNICODETEXT))


def is_image_available() -> bool:
    """查询当前系统剪贴板是否存在位图/DIB"""
    return bool(user32.IsClipboardFormatAvailable(CF_DIB) or user32.IsClipboardFormatAvailable(CF_BITMAP))


def get_clipboard_text() -> Optional[str]:
    """
    读取系统剪贴板中的 Unicode 文本
    
    Returns:
        文本内容，若无或读取失败则返回 None
    """
    if not is_text_available():
        return None

    with ClipboardContext() as opened:
        if not opened:
            return None

        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return None

        p_data = kernel32.GlobalLock(h_data)
        if not p_data:
            return None

        try:
            text = ctypes.wstring_at(p_data)
            return text
        except Exception as e:
            logger.error(f"Failed to decode unicode clipboard string: {e}", exc_info=True)
            return None
        finally:
            kernel32.GlobalUnlock(h_data)


def set_clipboard_text(text: str) -> bool:
    """
    将文本写入系统剪贴板 (CF_UNICODETEXT 格式)
    
    Args:
        text: 待写入文本
        
    Returns:
        是否成功
    """
    if not isinstance(text, str):
        return False

    # 以 UTF-16LE 编码并追加双字节空终止符
    encoded = (text + "\0").encode("utf-16le")
    byte_len = len(encoded)

    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, byte_len)
    if not h_mem:
        logger.error("Failed to allocate global memory for text")
        return False

    p_mem = kernel32.GlobalLock(h_mem)
    if not p_mem:
        logger.error("Failed to lock global memory for text")
        return False

    ctypes.memmove(p_mem, encoded, byte_len)
    kernel32.GlobalUnlock(h_mem)

    with ClipboardContext() as opened:
        if not opened:
            return False

        user32.EmptyClipboard()
        # SetClipboardData 成功后，操作系统接管 h_mem 所有权，无需手动释放
        result = user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        if not result:
            logger.error("SetClipboardData CF_UNICODETEXT failed")
            return False
        return True


def get_clipboard_image() -> Optional[Image.Image]:
    """
    从系统剪贴板读取图像
    
    利用成熟的 Pillow.ImageGrab.grabclipboard 进行格式解析，
    具备极佳的兼容性。
    """
    if not is_image_available():
        return None

    try:
        data = ImageGrab.grabclipboard()
        if isinstance(data, Image.Image):
            return data
        return None
    except Exception as e:
        logger.error(f"Failed to grab image from clipboard: {e}", exc_info=True)
        return None


def set_clipboard_image(img: Image.Image) -> bool:
    """
    将 PIL.Image 图像写入系统剪贴板 (CF_DIB 格式)
    
    Windows 规范：DIB 数据即 BMP 文件去掉前 14 字节的 BITMAPFILEHEADER。
    
    Args:
        img: 待写入图像
        
    Returns:
        是否成功
    """
    if not isinstance(img, Image.Image):
        return False

    try:
        output = io.BytesIO()
        # 强制转换为 RGB 并以 BMP 格式编码
        img.convert("RGB").save(output, format="BMP")
        raw_bytes = output.getvalue()
        output.close()

        # 截取 BITMAPINFOHEADER 及像素阵列 (跳过 14 字节文件头)
        dib_data = raw_bytes[14:]
        byte_len = len(dib_data)

        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, byte_len)
        if not h_mem:
            logger.error("GlobalAlloc failed for DIB image")
            return False

        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            logger.error("GlobalLock failed for DIB image")
            return False

        ctypes.memmove(p_mem, dib_data, byte_len)
        kernel32.GlobalUnlock(h_mem)

        with ClipboardContext() as opened:
            if not opened:
                return False

            user32.EmptyClipboard()
            res = user32.SetClipboardData(CF_DIB, h_mem)
            if not res:
                logger.error("SetClipboardData CF_DIB failed")
                return False
            return True

    except Exception as e:
        logger.error(f"Exception during set_clipboard_image: {e}", exc_info=True)
        return False
