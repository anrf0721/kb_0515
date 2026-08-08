"""
author: anrf
date:7/31/2026
desc:
"""
import json
from pathlib import Path
# atguigu/import_process/nodes/node_bge_embedding.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.bgem3_client_tool import get_bge_embedding
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger


class NodeBGEEmbedding(NodeBase):
    """
    混合向量化节点：使用 BGE-M3 模型将文本转换为向量
    """

    name = "node_bge_embedding"

    def process(self, state: ImportGraphState):
        chunks = state.get("chunks")
        if not chunks:
            logger.error("chunks is empty")
            raise Exception("chunks is empty")

        chunk_content_list = [f'{chunk.get("entity_name", "")}-{chunk.get("content", "")}' for chunk in chunks]
        emb_list = get_bge_embedding(chunk_content_list)
        for idx, chunk in enumerate(chunks):
            chunk['dense_vector'] = emb_list.get('dense')[idx]
            chunk['sparse_vector'] = emb_list.get('sparse')[idx]

        logger.info(f'向量化完成，共处理 {len(chunks)} 条')
        return state

if __name__ == '__main__':
    node = NodeBGEEmbedding()
    input_path = Path(__file__).parent.parent.parent / 'data' / 'chunks_recognition.json'
    with open(input_path, 'r', encoding='utf-8') as f:
        # chunks = json.loads(f.read())
    # 非流式写入, 会占用大量内存
        chunks = json.load(f)

    init_state = {
        'chunks': chunks
    }
    res = node(init_state)

    output_path = Path(__file__).parent.parent.parent / 'data' / 'chunks_bge.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        # f.write(json.dumps(res, ensure_ascii=False, indent=4))
        json.dump(res,f,ensure_ascii=False,indent=4)
    # logger.info(json_format(res))