"""
author: anrf
date:7/31/2026
desc:
"""
import base64
import os
import time
from collections import deque
from pathlib import Path
import re

from anyio import current_time
from langchain.chat_models import init_chat_model

from atguigu.config.config import LLMConfig
from atguigu.import_process.base import *
from atguigu.import_process.state import *
from atguigu.tool.json_dumps_tool import *
from atguigu.tool.logger import *


class NodeMdImage(NodeBase):

    name = 'node_md_image'

    def process(self,state:ImportGraphState):
        pass
        return state

if __name__ == '__main__':
    node = NodeMdImage()
    init_state = {'md_path' : r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册.md'}
    res = node(init_state)
    logger.info(json_format(res))
