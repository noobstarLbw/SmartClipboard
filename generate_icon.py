"""
生成应用程序高清 .ico 图标
"""

import os
from PIL import Image, ImageDraw

def generate_ico(output_path: str = "app_icon.ico"):
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 绘制深蓝底板卡片
    margin = 28
    draw.rounded_rectangle(
        [margin, margin + 16, size - margin, size - margin],
        radius=36,
        fill="#0078D4",
        outline="#005A9E",
        width=8
    )

    # 绘制剪贴板金属顶夹
    clip_w = 96
    clip_h = 42
    cx = size // 2
    draw.rounded_rectangle(
        [cx - clip_w // 2, margin - 8, cx + clip_w // 2, margin + clip_h],
        radius=14,
        fill="#E5E7EB",
        outline="#9CA3AF",
        width=8
    )

    # 绘制夹子中间把手
    draw.rounded_rectangle(
        [cx - 24, margin + 6, cx + 24, margin + 24],
        radius=6,
        fill="#FFFFFF"
    )

    # 绘制板上的三道白色文本线
    line_x1 = margin + 40
    line_x2 = size - margin - 40
    y_starts = [margin + 75, margin + 115, margin + 155]
    for y in y_starts:
        draw.rounded_rectangle([line_x1, y, line_x2, y + 14], radius=7, fill="#FFFFFF")

    # 保存多分辨率高清 ico 文件
    image.save(
        output_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    print(f"Generated icon: {output_path}")

if __name__ == "__main__":
    generate_ico()
