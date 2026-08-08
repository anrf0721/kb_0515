"""
author: anrf
date:8/8/2026
desc: 批量版本 — 节点内批量 embedding，不走单条
       改动点见 [CHANGED] 标记
"""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain.chat_models import init_chat_model
from pymilvus import DataType
from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.propmt import *
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.bgem3_client_tool import get_bge_embedding
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import *
from atguigu.tool.milvus_client_tool import get_milvus_client


# ======================== [CHANGED] 新增辅助函数 ========================
def _build_context(chunks, file_title, max_len=10000):
    """从切片构建 LLM 输入上下文（原 process 中内联的逻辑，抽成函数）"""
    chunk_top_list = chunks[:5]
    content_str = '\n'
    for idx, chunk in enumerate(chunk_top_list, start=1):
        content = chunk.get("content", "")
        chunk_str = f'[切片{idx}]\n{file_title}\n{content}\n'
        if len(content_str) + len(chunk_str) > max_len:
            logger.warning(f'内容长度超过{max_len}，已截断')
            break
        content_str += chunk_str
    return content_str[:max_len]


def _extract_entity_name(llm, file_title, chunks):
    """调 LLM 识别实体名（与原逻辑一致，抽成函数便于并发）"""
    content_str = _build_context(chunks, file_title)
    messages = [
        {"role": "system", "content": ITEM_NAME_SYSTEM_PROMPT},
        {"role": "user", "content": ITEM_NAME_USER_PROMPT_TEMPLATE.format(
            file_title=file_title, context=content_str
        )}
    ]
    res = llm.invoke(messages)
    entity_name = res.content.strip()
    if not entity_name:
        entity_name = file_title
        logger.warning(f'识别失败，使用文件名:{file_title}')
    logger.info(f'实体名:{file_title} → {entity_name}')
    return entity_name


def _escape_filter(value):
    """Milvus filter 表达式注入防护"""
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


class NodeItemNameRecognitionSend(NodeBase):
    """
    [CHANGED] 批量版主体识别节点
    区别：state 中提供 batch_items（列表），不走单条 chunks/file_title
    """

    name = "node_item_name_recognition_send"

    def process(self, state: ImportGraphState):
        # ======================== [CHANGED] 从 batch_items 读取批量数据 ========================
        batch_items = state.get("batch_items")
        if not batch_items:
            logger.error("batch_items is empty")
            raise Exception("batch_items is empty")

        # ======================== [CHANGED] LLM 并发识别（IO 密集型，线程池加速） ========================
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider='openai',
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_base_url,
            temperature=LLMConfig.llm_default_temperature
        )

        results = []  # [{entity_name, file_title, chunks}, ...]
        with ThreadPoolExecutor(max_workers=5) as pool:
            future_map = {
                pool.submit(_extract_entity_name, llm, item["file_title"], item["chunks"]): item
                for item in batch_items
            }
            for future in as_completed(future_map):
                item = future_map[future]
                entity_name = future.result()
                results.append({
                    "entity_name": entity_name,
                    "file_title": item["file_title"],
                    "chunks": item["chunks"],
                })

        # ======================== Milvus 建表（与原逻辑一致，无改动） ========================
        milvus_client = get_milvus_client()
        if not milvus_client:
            logger.error('初始化MilvusClient失败')
            raise Exception('初始化MilvusClient失败')
        collection_name = MilvusConfig.item_name_collection

        if not milvus_client.has_collection(collection_name):
            schema = milvus_client.create_schema(auto_id=True)
            schema.add_field(field_name='id', datatype=DataType.INT64, is_primary=True)
            schema.add_field(field_name='entity_name', datatype=DataType.VARCHAR, max_length=500)
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

        milvus_client.load_collection(collection_name=collection_name)

        # ======================== [CHANGED] 批量删除旧记录（参数化防注入） ========================
        entity_names = [r["entity_name"] for r in results]
        for name in entity_names:
            milvus_client.delete(
                collection_name=collection_name,
                filter='entity_name=="$target_name"',
                filter_params={"$target_name": name}
            )

        # ======================== [CHANGED] 核心改动：批量 embedding，一次 GPU 调用 ========================
        embedding = get_bge_embedding(entity_names)
        # embedding['dense']  → [[1024], [1024], ...]   一一对应 entity_names
        # embedding['sparse'] → [{...}, {...}, ...]

        # ======================== [CHANGED] 批量插入 ========================
        insert_data = []
        for i, r in enumerate(results):
            insert_data.append({
                'entity_name': r["entity_name"],
                'file_title': r["file_title"],
                'dense_vector': embedding['dense'][i],
                'sparse_vector': embedding['sparse'][i],
            })

        insert_result = milvus_client.insert(
            collection_name=collection_name,
            data=insert_data
        )
        logger.info(f'批量插入结果:{insert_result}')

        # ======================== [CHANGED] 批量更新 chunks 中的 entity_name ========================
        for r in results:
            for chunk in r["chunks"]:
                chunk['entity_name'] = r["entity_name"]

        return {
            "batch_results": results,   # [CHANGED] 原版返回单条，批量版返回列表
        }


if __name__ == '__main__':
    # ======================== [CHANGED] 测试用例：模拟多文件批量输入 ========================
    node = NodeItemNameRecognitionSend()
    input_path = Path(__file__).parent.parent.parent / 'data' / 'chunks.json'
    with open(input_path,
              'r', encoding='utf-8') as f:
        chunks = json.load(f)

    init_state = {
        'batch_items': [
            {'chunks': chunks, 'file_title': 'hak180产品安全手册'},
            # 可以追加更多文件：
            # {'chunks': other_chunks, 'file_title': '另一个产品手册'},
        ]
    }
    res = node(init_state)
    logger.info(json_format(res))
