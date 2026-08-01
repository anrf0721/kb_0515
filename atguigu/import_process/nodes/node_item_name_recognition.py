"""
author: anrf
date:7/31/2026
desc:
"""
# atguigu/import_process/nodes/node_item_name_recognition.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState


class NodeItemNameRecognition(NodeBase):
    """
    主体识别节点：主体识别与标签提取
    """

    name = "node_item_name_recognition"

    def process(self, state: ImportGraphState):


        return state