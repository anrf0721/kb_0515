"""
author: anrf
date:7/31/2026
desc:
"""
# atguigu/import_process/nodes/node_bge_embedding.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState


class NodeBGEEmbedding(NodeBase):
    """
    混合向量化节点：使用 BGE-M3 模型将文本转换为向量
    """

    name = "node_bge_embedding"

    def process(self, state: ImportGraphState):


        return state