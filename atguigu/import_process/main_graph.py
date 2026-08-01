"""
author: anrf
date:8/1/2026
desc:
"""
from langgraph import graph
from langgraph.constants import START,END
from langgraph.graph import StateGraph

from atguigu.import_process.nodes.node_bge_embedding import NodeBGEEmbedding
from atguigu.import_process.nodes.node_document_split import NodeDocumentSplit
from atguigu.import_process.nodes.node_entry import *
from atguigu.import_process.nodes.node_import_milvus import NodeImportMilvus
from atguigu.import_process.nodes.node_item_name_recognition import NodeItemNameRecognition
from atguigu.import_process.nodes.node_md_img import NodeMDImg
from atguigu.import_process.nodes.node_pdf_to_md import NodePDFToMD
from atguigu.import_process.state import *


# 函数版本
# builder = StateGraph(state_schema=ImportGraphState)
#
# def after_entry_router(state:ImportGraphState):
#     if state.get('is_md_read_enabled'):
#         return NodeMDImg.name
#     elif state.get('is_pdf_read_enabled'):
#         return NodePDFToMD.name
#     else:
#         return END
#
#
# builder.add_node(NodeEntry.name,NodeEntry())
# builder.add_node(NodePDFToMD.name,NodePDFToMD())
# builder.add_node(NodeMDImg.name,NodeMDImg())
# builder.add_node(NodeDocumentSplit.name,NodeDocumentSplit())
# builder.add_node(NodeItemNameRecognition.name,NodeItemNameRecognition())
# builder.add_node(NodeBGEEmbedding.name,NodeBGEEmbedding())
# builder.add_node(NodeImportMilvus.name,NodeImportMilvus())
#
# builder.set_entry_point(NodeEntry.name)
# builder.add_conditional_edges(NodeEntry.name,after_entry_router,{NodePDFToMD.name:NodePDFToMD.name,
#                                                                  NodeMDImg.name:NodeMDImg.name})
# builder.add_edge(NodePDFToMD.name,NodeMDImg.name)
# builder.add_edge(NodeMDImg.name,NodeDocumentSplit.name)
# builder.add_edge(NodeDocumentSplit.name,NodeItemNameRecognition.name)
# builder.add_edge(NodeItemNameRecognition.name,NodeBGEEmbedding.name)
# builder.add_edge(NodeBGEEmbedding.name,NodeImportMilvus.name)
# builder.add_edge(NodeBGEEmbedding.name,END)
#
# graph = builder.compile()
# init_state = {'local_file_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\xx2.md'}
#
# graph.invoke(init_state)

# 封装为类,添加实例方法
class MainGraphRunner:
    def __init__(self):
        self.builder = StateGraph(state_schema=ImportGraphState)
        self.add_nodes()
        self.add_edges()
        # 单例,避免重复创建;第二个目的:可以懒加载,延迟加载,节省开销
        self.graph = None

    def add_nodes(self):
        self.builder.add_node(NodeEntry.name,NodeEntry())
        self.builder.add_node(NodePDFToMD.name,NodePDFToMD())
        self.builder.add_node(NodeMDImg.name,NodeMDImg())
        self.builder.add_node(NodeDocumentSplit.name,NodeDocumentSplit())
        self.builder.add_node(NodeItemNameRecognition.name,NodeItemNameRecognition())
        self.builder.add_node(NodeBGEEmbedding.name,NodeBGEEmbedding())
        self.builder.add_node(NodeImportMilvus.name,NodeImportMilvus())

    def add_edges(self):
        self.builder.set_entry_point(NodeEntry.name)
        self.builder.add_conditional_edges(NodeEntry.name,self.after_entry_router)
        self.builder.add_edge(NodePDFToMD.name,NodeMDImg.name)
        self.builder.add_edge(NodeMDImg.name,NodeDocumentSplit.name)
        self.builder.add_edge(NodeDocumentSplit.name,NodeItemNameRecognition.name)
        self.builder.add_edge(NodeItemNameRecognition.name,NodeBGEEmbedding.name)
        self.builder.add_edge(NodeBGEEmbedding.name,NodeImportMilvus.name)
        self.builder.add_edge(NodeBGEEmbedding.name,END)

    def after_entry_router(self,state:ImportGraphState):
        if state.get('is_md_read_enabled'):
            return NodeMDImg.name
        elif state.get('is_pdf_read_enabled'):
            return NodePDFToMD.name
        else:
            return END

    def run_graph(self,init_state):
        if not self.graph:
            self.graph = self.builder.compile()
        return self.graph.invoke(init_state)

    @classmethod
    def create_and_run(cls,state):
        runner = cls().run_graph(state)

if __name__ == '__main__':
    # runner = MainGraphRunner()
    init_state = {'local_file_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\xx2.md'}
    # result = runner.run_graph(init_state)
    # print(result)
    MainGraphRunner.create_and_run(init_state)