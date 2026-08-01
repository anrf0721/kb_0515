"""
author: anrf
date:7/31/2026
desc:
"""
# atguigu/import_process/nodes/node_document_split.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：智能文档切片
    """

    name = "node_document_split"

    def process(self, state: ImportGraphState):


        return state