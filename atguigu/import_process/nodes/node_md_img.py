"""
author: anrf
date:7/31/2026
desc:
"""
import os
import re
from pathlib import Path

from atguigu.import_process.base import *
from atguigu.import_process.state import *
from atguigu.tool.logger import *
from atguigu.tool.json_dumps_tool import *


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    def process(self, state: ImportGraphState):
        md_path = state.get('md_path','')
        if not md_path:
            logger.error('路径没有提供')
            raise Exception('路径没有提供')
        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error('文件不存在')
            raise Exception('文件不存在')

        with open (md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()
            if not md_content:
                logger.error('文件内容为空')
                raise Exception('文件内容为空')
            image_path_obj = md_path_obj.parent / 'images'
            if not image_path_obj.exists():
                logger.info('图片不存在')
                return md_content

            image_name_list = os.listdir(image_path_obj)
            if not image_name_list:
                logger.info('图片目录不存在')
                return md_content

            logger.info(f'图片目录下图片数量:{len(image_name_list)}')
            IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
            MAX_CONTEXT_LENGTH = 250
            image_context_list = []
            for image_name in image_name_list:
                if  Path(image_name).suffix.lower() not in IMAGE_EXTENSIONS:
                    logger.warning(f'图片格式错误:{image_name}')
                    continue

                pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")
                match = pattern.search(md_content)
                logger.info(f'图片匹配结果:{match}')
                if not match:
                    logger.warning(f'图片未引用:{image_name}')
                    continue
                start,end = match.span()
                pre_text = md_content[max(0,start-MAX_CONTEXT_LENGTH):start]
                post_text = md_content[end:min(len(md_content),end+MAX_CONTEXT_LENGTH)]

                image_context_list.append({'image_name':image_name,
                                           'image_pre_context':pre_text,
                                           'image_post_context':post_text,
                                           'image_path':str(image_path_obj / image_name)

                                           })
                # logger.info(f'图片上下文:{image_context_list}')

        return state

if __name__ == '__main__':
    node = NodeMDImg()
    init_state = {
        'md_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册.md'
    }
    res = node(init_state)
    logger.info(json_format(res))