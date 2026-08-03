"""
author: anrf
date:7/31/2026
desc:
"""
import base64
import os
import re
import time
from collections import deque
from pathlib import Path

from langchain.chat_models import init_chat_model

from atguigu.config.config import *
from atguigu.import_process.base import *
from atguigu.import_process.state import *
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import *
from atguigu.tool.json_dumps_tool import *


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    def process(self, state: ImportGraphState):
        image_name_list, image_path_obj, md_content,md_path = NodeMDImg.read_image_obj(state)

        image_summary_list1 = self.image_summary_list(image_name_list, image_path_obj, md_content,md_path)

        return {'md_path': md_path, 'md_content': md_content}

    @classmethod
    def image_summary_list(cls, image_name_list: list[str], image_path_obj: str, md_content,md_path):
        IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        MAX_CONTEXT_LENGTH = 250
        image_context_summary_list = []
        llm = init_chat_model(
            model=LLMConfig.llm_default_model,
            model_provider='openai',
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_base_url,
            temperature=LLMConfig.llm_default_temperature
        )
        # 【改动1】dq 提到外层 for 外部，避免每次重建导致滑动窗口失效
        dq = deque(maxlen=30)
        for image_name in image_name_list:
            # 【改动7】每轮循环更新 current_time，否则窗口判断永远用的是初始值
            current_time = time.time()
            if Path(image_name).suffix.lower() not in IMAGE_EXTENSIONS:
                logger.warning(f'图片格式错误:{image_name}')
                continue

            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")
            match = pattern.search(md_content)
            # logger.info(f'图片匹配结果:{match}')
            if not match:
                logger.warning(f'图片未引用:{image_name}')
                continue
            start, end = match.span()
            pre_text = md_content[max(0, start - MAX_CONTEXT_LENGTH):start]
            post_text = md_content[end:min(len(md_content), end + MAX_CONTEXT_LENGTH)]

            # 【改动2】去掉内层 for image_context in image_context_list，每张图只调一次 LLM
            # 【改动3】滑动窗口限速逻辑直接处理当前图片，不再遍历历史列表
            # 先清理过期请求
            while dq and current_time - dq[0] > 60:
                dq.popleft()
            if dq and len(dq) == dq.maxlen:
                need_wait_time = 60 - (current_time - dq[0])
                if need_wait_time > 0:
                    logger.error(f'图片处理超时,等待时间:{need_wait_time}')
                    time.sleep(need_wait_time)
                    current_time = time.time()
                    while dq and current_time - dq[0] > 60:
                        dq.popleft()
            dq.append(current_time)

            # 【改动5】直接处理当前图片，使用 pre_text/post_text 而非 image_context.get()
            image_path = str(image_path_obj / image_name)
            with open(image_path, 'rb') as f:
                image_data = f.read()
                base64_image_data = base64.b64encode(image_data).decode('utf-8')
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image_data}"
                            },
                        },
                        {"type": "text",
                         "text": f"请根据图片的上文{pre_text},图片的后文{post_text}，给出图片的摘要，请使用中文,30字以内。"},
                    ],
                },
            ]
            res = llm.invoke(messages)
            image_context_summary_list.append({'image_name': image_name,
                                               'image_path': image_path,
                                               'summary': res.content
                                               })
        # 【改动6】logger 移到外层 for 外部，只打一次
        logger.info(f'图片处理结果:{json_format(image_context_summary_list)}')
        return image_context_summary_list

    @classmethod
    def read_image_obj(cls, state: ImportGraphState) -> tuple[list[str], str, Path]:
        md_path = state.get('md_path', '')
        if not md_path:
            logger.error('路径没有提供')
            raise Exception('路径没有提供')
        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error('文件不存在')
            raise Exception('文件不存在')

        with open(md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()
            if not md_content:
                logger.error('文件内容为空')

            image_path_obj = md_path_obj.parent / 'images'
            if not image_path_obj.exists():
                logger.error('图片目录不存在')

            image_name_list = os.listdir(image_path_obj)
            if not image_name_list:
                logger.error('图片目录下图片不存在')

        logger.info(f'图片目录下文件数量:{len(image_name_list)}')
        # logger.info((f'图片内容:{md_content}'))
        return image_name_list, image_path_obj, md_content,md_path


if __name__ == '__main__':
    node = NodeMDImg()
    init_state = {
        'md_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册.md'
    }
    res = node(init_state)
    logger.info(json_format(res))