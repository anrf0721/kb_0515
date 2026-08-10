"""
author: anrf
date:7/31/2026
desc:
"""
import json
import time
from pathlib import Path

from pymilvus import DataType

from atguigu.config.config import MilvusConfig
# atguigu/import_process/nodes/node_import_milvus.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client


class NodeImportMilvus(NodeBase):
    """
    导入向量库节点：数据持久化
    """

    name = "node_import_milvus"

    def process(self, state: ImportGraphState):
        chunks = state.get('chunks', [])
        logger.info(type(chunks))
        if not chunks:
            logger.error("导入失败，数据为空")
            raise Exception("导入失败，数据为空")

        file_title = state.get('file_title', '')

        milvus_client = get_milvus_client()
        collection_name = MilvusConfig.chunks_collection

        # 建表（不存在时）
        if not milvus_client.has_collection(collection_name):
            schema = milvus_client.create_schema(auto_id=True)
            schema.add_field(field_name='id', datatype=DataType.INT64, is_primary=True)
            schema.add_field(field_name='entity_content', datatype=DataType.VARCHAR, max_length=5000)
            schema.add_field(field_name='file_title', datatype=DataType.VARCHAR, max_length=500)
            schema.add_field(field_name='dense_vector', datatype=DataType.FLOAT_VECTOR, dim=1024)
            schema.add_field(field_name='sparse_vector', datatype=DataType.SPARSE_FLOAT_VECTOR)

            index_params = milvus_client.prepare_index_params()
            index_params.add_index(
                field_name='dense_vector', index_type='IVF_FLAT',
                metric_type='COSINE', params={'nlist': 128}
            )
            index_params.add_index(
                field_name='sparse_vector', index_type='SPARSE_INVERTED_INDEX',
                metric_type='IP'
            )
            milvus_client.create_collection(
                collection_name=collection_name, schema=schema, index_params=index_params
            )

        # 加载 collection 并等待就绪
        milvus_client.load_collection(collection_name=collection_name)
        # max_retries = 30
        # for i in range(max_retries):
        #     try:
        #         load_state = milvus_client.get_load_state(collection_name=collection_name)
        #         state = str(load_state.get("state", ""))
        #         if state == "Loaded":
        #             logger.info("collection 加载完成")
        #             break
        #         logger.info(f"collection 加载中，当前状态: {state}，等待2秒... ({i+1}/{max_retries})")
        #     except Exception as e:
        #         logger.warning(f"get_load_state 异常: {e}，等待2秒重试... ({i+1}/{max_retries})")
        #     time.sleep(2)
        # else:
        #     logger.error("collection 加载超时，请检查 Milvus 服务状态")
        #     raise Exception("collection 加载超时")

        # 按文件标题删除旧记录，避免重复
        milvus_client.delete(
            collection_name=collection_name,
            filter='file_title=="$target_title"',
            filter_params={"$target_title": file_title}
        )

        # 构建批量插入数据
        insert_data = []
        for chunk in chunks:
            entity_content = f'{chunk.get("entity_name", "")}-{chunk.get("content", "")}'
            chunk['content'] = entity_content


            insert_data.append({
                "entity_content": entity_content,
                "file_title": file_title,
                "dense_vector": chunk['dense_vector'],
                "sparse_vector": chunk['sparse_vector']
            })

        result = milvus_client.insert(collection_name=collection_name, data=insert_data)
        # logger.info(f"插入结果: {result}")



        return {'chunks': chunks}


if __name__ == '__main__':
    node = NodeImportMilvus()
    input_path = Path(__file__).parent.parent.parent / 'data' / 'chunks_bge.json'
    with open(input_path,'r',encoding='utf-8') as f:
        chunks_load = json.load(f)
    md_path = r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册_new.md'
    init_state = {
        'chunks': chunks_load,
        'md_path' : md_path,
        'file_title' : 'hak180产品安全手册'
    }
    res = node(init_state)
    logger.info(json_format(res))