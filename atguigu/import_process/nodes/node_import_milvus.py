"""
author: anrf
date:7/31/2026
desc:
"""
import json
import re
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

# 集合加载轮询配置（load_collection 是异步操作）
LOAD_MAX_RETRIES = 30
LOAD_POLL_INTERVAL = 2  # 秒

# 批量写入配置：分批 insert，避免单次 gRPC 请求体过大
INSERT_BATCH_SIZE = 100

# 写入失败现场保留目录（data 目录已被 .gitignore 忽略）
PENDING_DIR = Path(__file__).parent.parent.parent / 'data'


def _sanitize_filename(name: str) -> str:
    """清理 file_title 中的非法文件名字符，用于失败现场落盘"""
    return re.sub(r'[\\/:*?"<>|]', '_', name)


def _wait_collection_loaded(milvus_client, collection_name: str):
    """load_collection 是异步操作：有限轮询等待加载完成，超时抛异常防死循环。
    不等待就立即写入会因数据节点时间戳未同步报 Timestamp lag too large。"""
    for i in range(LOAD_MAX_RETRIES):
        try:
            load_state = milvus_client.get_load_state(collection_name=collection_name)
            state = str(load_state.get("state", ""))
            # 兼容不同 pymilvus 版本的返回值：Loaded / LoadState.Loaded
            if "Loaded" in state:
                logger.info("collection 加载完成")
                return
            logger.info(f"collection 加载中，当前状态: {state}，等待{LOAD_POLL_INTERVAL}秒... ({i + 1}/{LOAD_MAX_RETRIES})")
        except Exception as e:
            logger.warning(f"get_load_state 异常: {e}，等待{LOAD_POLL_INTERVAL}秒重试... ({i + 1}/{LOAD_MAX_RETRIES})")
        time.sleep(LOAD_POLL_INTERVAL)
    raise Exception(f"collection 加载超时（>{LOAD_MAX_RETRIES * LOAD_POLL_INTERVAL}s），请检查 Milvus 服务状态")


class NodeImportMilvus(NodeBase):
    """
    导入向量库节点：数据持久化
    """

    name = "node_import_milvus"

    def process(self, state: ImportGraphState):
        chunks = state.get('chunks', [])
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
            schema.add_field(field_name='title', datatype=DataType.VARCHAR, max_length=500)
            schema.add_field(field_name='item_name', datatype=DataType.VARCHAR, max_length=500)

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
            try:
                milvus_client.create_collection(
                    collection_name=collection_name, schema=schema, index_params=index_params
                )
            except Exception as e:
                # 并发首建竞争：其他任务可能已创建成功，确认存在则忽略
                if not milvus_client.has_collection(collection_name):
                    raise
                logger.warning(f'collection 已由其他任务创建，跳过建表: {e}')

        # 加载集合：create_collection 的索引构建是异步的，并发首建场景下
        # 其他任务可能在索引就绪前 load 而报 no vector index，失败时有限重试
        for i in range(LOAD_MAX_RETRIES):
            try:
                milvus_client.load_collection(collection_name=collection_name)
                break
            except Exception as e:
                if i == LOAD_MAX_RETRIES - 1:
                    raise
                logger.warning(f'load_collection 失败（第 {i+1} 次）: {e}，{LOAD_POLL_INTERVAL}s 后重试（索引可能正在异步构建）')
                time.sleep(LOAD_POLL_INTERVAL)
        _wait_collection_loaded(milvus_client, collection_name)

        # 按文件标题删除旧记录，避免重复（参数化防注入：查询逻辑与数据分离）
        milvus_client.delete(
            collection_name=collection_name,
            filter='file_title=="$target_title"',
            filter_params={"$target_title": file_title}
        )

        # 组装插入数据：
        # chunk['content'] 已在 node_bge_embedding 写回为 entity_name-content 拼接文本
        # （单一事实来源，此处只读不拼，避免两处拼接逻辑漂移）
        insert_data = []
        seen_contents = set()
        for chunk in chunks:
            entity_content = chunk.get('content', '')
            # 批次内按内容去重：切片/上游环节产生相同内容时，只保留第一条，
            # 防止重复 chunk 写入向量库污染召回结果
            if entity_content in seen_contents:
                logger.warning(f'检测到重复内容，跳过写入: {entity_content[:50]}...')
                continue
            seen_contents.add(entity_content)
            insert_data.append({
                "entity_content": entity_content,
                "file_title": file_title,
                "title": chunk.get("title", ""),
                "item_name": chunk.get("entity_name", ""),
                "dense_vector": chunk['dense_vector'],
                "sparse_vector": chunk['sparse_vector']
            })

        # 分批写入：单批失败只损失单批，失败时落盘剩余数据供补偿重放
        total_inserted = 0
        try:
            for start in range(0, len(insert_data), INSERT_BATCH_SIZE):
                batch = insert_data[start:start + INSERT_BATCH_SIZE]
                result = milvus_client.insert(collection_name=collection_name, data=batch)
                count = result.get('insert_count', 0)
                total_inserted += count
                if count != len(batch):
                    logger.warning(f'本批 insert_count({count}) 与批大小({len(batch)}) 不一致，可能存在部分写入失败')
        except Exception as e:
            # 现场保留：落盘未写入的数据（含已组装向量，JSON 可序列化），供补偿重放
            self._save_failed_insert(file_title, collection_name, insert_data, total_inserted)
            logger.error(f'Milvus 写入失败: {e}，已写入 {total_inserted}/{len(insert_data)} 条，剩余数据已落盘可重放')
            raise

        logger.info(f'插入成功, 条数: {total_inserted}')
        return {'chunks': chunks}

    @staticmethod
    def _save_failed_insert(file_title: str, collection_name: str, insert_data: list, total_inserted: int):
        """insert 失败时将未写入的数据落盘（尽力而为，不影响原始异常抛出），供补偿重放"""
        try:
            PENDING_DIR.mkdir(parents=True, exist_ok=True)
            safe_title = _sanitize_filename(file_title) or 'unknown'
            failed_path = PENDING_DIR / f'milvus_failed_insert_{safe_title}.json'
            payload = {
                'collection_name': collection_name,
                'file_title': file_title,
                'total_inserted': total_inserted,
                'remaining_data': insert_data[total_inserted:],
            }
            with open(failed_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f'写入失败现场已保留: {failed_path}')
        except Exception as save_err:
            logger.error(f'失败现场落盘异常（不影响原始异常抛出）: {save_err}')


if __name__ == '__main__':
    node = NodeImportMilvus()
    input_path = Path(__file__).parent.parent.parent / 'data' / 'chunks_bge.json'
    with open(input_path, 'r', encoding='utf-8') as f:
        chunks_load = json.load(f)
    md_path = r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册_new.md'
    init_state = {
        'chunks': chunks_load,
        'md_path': md_path,
        'file_title': 'hak180产品安全手册'
    }
    res = node(init_state)
    logger.info(f"chunks 数量: {len(res.get('chunks', []))}")
