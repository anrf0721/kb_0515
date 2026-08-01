"""
author: anrf
date:7/31/2026
desc:
"""
# atguigu/import_process/nodes/node_import_milvus.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState


class NodeImportMilvus(NodeBase):
    """
    导入向量库节点：数据持久化
    """

    name = "node_import_milvus"

    def process(self, state: ImportGraphState):


        return state