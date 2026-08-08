"""
author: anrf
date:7/31/2026
desc:
"""
import json

# atguigu/import_process/nodes/node_item_name_recognition.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import *


class NodeItemNameRecognition(NodeBase):
    """
    主体识别节点：主体识别与标签提取
    """

    name = "node_item_name_recognition"

    def process(self, state: ImportGraphState):
        chunks = state.get("chunks")
        if not chunks:
            logger.error("chunks is empty")
            raise Exception("chunks is empty")
        file_title = state.get("file_title", "")
        if not file_title:
            logger.error("file_title is empty")
            raise Exception("file_title is empty")

        chunk_top_list = chunks[:5]
        max_len = 10000
        content_str = '\n'
        for idx,chunk in enumerate(chunk_top_list,start=1):
            title = chunk.get("title", "")
            content = chunk.get("content", "")
            chunk_str = f'[切片{idx}]\n{file_title}\n{content}\n'
            logger.info(f'内容:{chunk_str}')
            if len(content_str) > max_len:
                logger.warning(f'内容长度超过{max_len}，已截断')
                break
            content_str += chunk_str
        content_str = content_str[:max_len]

        logger.info(f'内容:{content_str}')

        # return state

if __name__ == '__main__':
    node = NodeItemNameRecognition()
    with open(r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\chunks.json','r',encoding='utf-8') as f:
        chunks = f.read()
        # print(type(chunks))
        chunks_load = json.loads(chunks)

    init_state = {
        'chunks': chunks_load,
        'file_title' : 'hak180产品安全手册'
    }
    res = node(init_state)
    logger.info(json_format(res))