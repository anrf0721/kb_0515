"""
author: anrf
date:8/10/2026
desc:
"""
import json

from atguigu.config.config import MilvusConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.bgem3_client_tool import get_bge_embedding
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import create_reqs, search_hybrid


class NodeSearchEmbedding(NodeBase):
    """
    节点功能：基于已确认主体名+改写后的用户问题，执行Milvus向量数据库混合检索
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_search_embedding"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        logger.info(f"【{self.name}】节点逻辑")
        rewritten_query = state.get("rewritten_query", '')
        item_names = state.get("item_names", [])
        if not rewritten_query:
            logger.error("用户问题改写为空")
            raise ValueError("用户问题改写为空")
        if not item_names:
            logger.warning("已确认的主体名为空，将不加商品名过滤，全库检索")

        embeddings = get_bge_embedding([rewritten_query])
        collection_chunks = MilvusConfig.chunks_collection
        dense_data = embeddings.get('dense')[0]
        sparse_data = embeddings.get('sparse')[0]

        kwargs = {}
        if item_names:
            item_names = [
                item.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
                for item in item_names
            ]
            kwargs['expr'] = f'item_name in {json.dumps(item_names)}'
        reqs = create_reqs(
            dense_data=[dense_data],
            sparse_data=[sparse_data],
            dense_anns_field='dense_vector',
            sparse_anns_field='sparse_vector',
            **kwargs,
        )
        res = search_hybrid(
            collection_name=collection_chunks,
            reqs=reqs,
            ranker=(0.8, 0.2),
            limit=10,
            output_fields=['id', 'entity_content', 'title','item_name']
        )
        # logger.info(res[0])
        embeddings_chunks = [
            {
                **item.get('entity',''),
                'score': item.get('distance', 0.0),
                'source' : 'local'
            }
            for item in res[0]
        ]

        return {"embedding_chunks": embeddings_chunks}


if __name__ == '__main__':
    init_state = {
        "rewritten_query": "关于hak180烫金机如何使用",
        "item_names": ["brotherhak180烫金机"]
    }
    node_search_embedding = NodeSearchEmbedding()
    result = node_search_embedding(init_state)
    logger.info(json_format(result))
