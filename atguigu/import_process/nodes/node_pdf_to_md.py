"""
author: anrf
date:7/31/2026
desc:
"""
# atguigu/import_process/nodes/node_pdf_to_md.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState


class NodePDFToMD(NodeBase):
    """
    PDF 转 Markdown 节点：PDF结构化解析
    """

    name = "node_pdf_to_md"

    def process(self, state: ImportGraphState):

        return state