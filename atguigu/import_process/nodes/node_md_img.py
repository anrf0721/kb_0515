"""
author: anrf
date:7/31/2026
desc:
"""
# atguigu/import_process/nodes/node_md_img.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    def process(self, state: ImportGraphState):


        return state