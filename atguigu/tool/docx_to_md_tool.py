"""
author: anrf
date:8/21/2026
desc: Word(.docx) 转 Markdown 工具，供导入图入口节点调用。
     产物结构与 MinerU 解析结果对齐：{output_dir}/{stem}.md + {output_dir}/images/，
     下游 node_md_img 按 images/ 目录约定直接复用。
     说明：mammoth 自带的 convert_to_markdown 不支持表格，故走 HTML 中转保表格。
"""
from itertools import count
from pathlib import Path

import mammoth
from markdownify import markdownify as html_to_md

from atguigu.tool.logger import *

# docx 内嵌图片 content_type → 扩展名；
# emf/wmf 保留原名（下游 VL 模型不支持的格式会被 node_md_img 跳过，不影响流程）
_IMAGE_EXT_MAP = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/gif': '.gif',
    'image/bmp': '.bmp',
    'image/tiff': '.tiff',
    'image/webp': '.webp',
    'image/x-emf': '.emf',
    'image/x-wmf': '.wmf',
}


def docx_to_md(docx_path_obj: Path, output_dir_obj: Path) -> Path:
    """
    docx 转 Markdown，返回 md 文件路径。
    图片提取到 output_dir/images/ 并在 md 中引用相对路径 images/xxx
    """
    images_dir_obj = output_dir_obj / 'images'
    image_seq = count(1)

    def save_image(image):
        # mammoth 逐图回调：图片落盘到 images/，md 中引用相对路径
        with image.open() as image_file:
            image_data = image_file.read()
        ext = _IMAGE_EXT_MAP.get(image.content_type, '.png')
        image_name = f'img_{next(image_seq):03d}{ext}'
        images_dir_obj.mkdir(parents=True, exist_ok=True)
        (images_dir_obj / image_name).write_bytes(image_data)
        return {'src': f'images/{image_name}'}

    # img_element 装饰器补齐 alt 文本并包装为 <img> 元素（mammoth 1.12 参数名为 convert_image）
    convert_image = mammoth.images.img_element(save_image)

    with open(docx_path_obj, 'rb') as f:
        result = mammoth.convert_to_html(f, convert_image=convert_image)
    for msg in result.messages:
        logger.warning(f'docx转换警告: {msg}')

    md_content = html_to_md(result.value, heading_style='ATX')

    output_dir_obj.mkdir(parents=True, exist_ok=True)
    md_path_obj = output_dir_obj / f'{docx_path_obj.stem}.md'
    with open(md_path_obj, 'w', encoding='utf-8') as f:
        f.write(md_content)
    logger.info(f'docx转换完成, md保存路径: {md_path_obj}, 提取图片数: {next(image_seq) - 1}')
    return md_path_obj
