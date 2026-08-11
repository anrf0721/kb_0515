"""
author: anrf
date:7/31/2026
desc:
"""
import json
import time
from pathlib import Path

from langchain.chat_models import init_chat_model
from pymilvus import DataType
from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.propmt import *
# atguigu/import_process/nodes/node_item_name_recognition.py
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.bgem3_client_tool import get_bge_embedding
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import *
from atguigu.tool.milvus_client_tool import get_milvus_client


class NodeItemNameRecognition(NodeBase):
    """
    主体识别节点：主体识别与标签提取
    """

    name = "node_item_name_recognition"

    def process(self, state: ImportGraphState):
        chunks = state.get("chunks")
        if not chunks:
            logger.error("chunks is empty")
            raise Exception("chunks is empty")
        file_title = state.get("file_title", "")
        if not file_title:
            logger.error("file_title is empty")
            raise Exception("file_title is empty")

        # 取更多切片，提高品牌名被命中的概率（受 max_len 限制，不会无限膨胀）
        chunk_top_list = chunks[:20]
        max_len = 10000
        content_str = '\n'
        for idx,chunk in enumerate(chunk_top_list,start=1):
            title = chunk.get("title", "")
            content = chunk.get("content", "")
            chunk_str = f'[切片{idx}]\n{file_title}\n{content}\n'
            # logger.info(f'内容:{chunk_str}')
            if len(content_str) > max_len:
                logger.warning(f'内容长度超过{max_len}，已截断')
                break
            content_str += chunk_str
        content_str = content_str[:max_len]

        # logger.info(f'内容:{content_str}')

        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider='openai',
            api_key = LLMConfig.openai_api_key,
            base_url = LLMConfig.openai_base_url,
            temperature = LLMConfig.llm_default_temperature
        )


        messages = [
            {"role": "system", "content": ITEM_NAME_SYSTEM_PROMPT},
            {"role": "user", "content": ITEM_NAME_USER_PROMPT_TEMPLATE.format(file_title=file_title, context=content_str)}
        ]
        res = llm.invoke(messages)
        entity_name = "".join(res.content.split())
        # 统一小写：消除 LLM 大小写不稳定的影响，保证导入与查询向量一致
        entity_name = entity_name.lower()
        logger.info(f'实体名:{entity_name}')

        if not entity_name:
            entity_name = file_title
            logger.warning(f'识别失败，使用文件名:{file_title}')

        milvus_client = get_milvus_client()
        if not milvus_client:
            logger.error('初始化MilvusClient失败')
            raise Exception('初始化MilvusClient失败')
        collection_name = MilvusConfig.item_name_collection


        if not milvus_client.has_collection(collection_name):
            schema = milvus_client.create_schema(auto_id = True)
            schema.add_field(field_name='id', datatype=DataType.INT64,is_primary=True,is_unique =  True)
            schema.add_field(field_name='entity_name', datatype=DataType.VARCHAR,max_length=500)
            schema.add_field(field_name='file_title', datatype=DataType.VARCHAR,max_length=500)
            schema.add_field(field_name='dense_vector', datatype=DataType.FLOAT_VECTOR,dim =1024)
            schema.add_field(field_name='sparse_vector', datatype=DataType.SPARSE_FLOAT_VECTOR)

            index_params = milvus_client.prepare_index_params()
            index_params.add_index(field_name='dense_vector', index_type='IVF_FLAT', metric_type='COSINE', params={'nlist':128})
            # search_params = {
            #     "metric_type": "COSINE",
            #     "params": {"nprobe": 16}
            # }
            index_params.add_index(
                field_name='sparse_vector',
                index_type='SPARSE_INVERTED_INDEX',
                metric_type='IP'  # 稀疏向量固定用 IP
            )
            milvus_client.create_collection(collection_name = collection_name,schema= schema, index_params=index_params)

        milvus_client.load_collection(collection_name=collection_name)

        milvus_client.delete(collection_name=collection_name, filter='entity_name=="$target_name"', filter_params={"$target_name": entity_name})

        embedding = get_bge_embedding([entity_name])
        # logger.info(f'embedding:{embedding}')
        result = milvus_client.insert(
            collection_name=collection_name,
            data = [
                {
                    'entity_name': entity_name,
                    'file_title': file_title,
                    'dense_vector': embedding['dense'][0],
                    'sparse_vector': embedding['sparse'][0]
                }
            ]
        )
        logger.info(f'插入结果:{result}')
        for chunk in chunks:
            chunk['entity_name'] = entity_name
        return {
            "item_name": entity_name,
            "file_title": file_title,
            "chunks": chunks
        }
        # return state

if __name__ == '__main__':
    node = NodeItemNameRecognition()
    input_path = Path(__file__).parent.parent.parent / 'data' / 'chunks.json'
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
    output_path = Path(__file__).parent.parent.parent / 'data' / 'chunks_recognition.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        # json.dump(res['chunks'], f, ensure_ascii=False, indent=2)
        f.write(json_format(res['chunks']))