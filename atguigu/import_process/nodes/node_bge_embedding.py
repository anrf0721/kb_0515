"""
author: anrf
date:7/31/2026
desc:
"""
import json
import re
import time
from pathlib import Path

# atguigu/import_process/nodes/node_bge_embedding.py
from atguigu.config.config import EmbeddingConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.bgem3_client_tool import get_bge_embedding
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger

# 编码失败重试配置
EMBED_MAX_RETRIES = 3
EMBED_RETRY_BASE_INTERVAL = 2  # 秒，线性退避：间隔 = 基础间隔 * 尝试次数

# 失败现场保留目录：与 __main__ 测试产物同目录（data 目录已被 .gitignore 忽略）
PENDING_DIR = Path(__file__).parent.parent.parent / 'data'


def build_entity_content(entity_name: str, content: str) -> str:
    """拼接实体名与切片内容——导入链路中 entity_content 文本的唯一事实来源（Single Source of Truth）"""
    return f'{entity_name}-{content}'


def _sanitize_filename(name: str) -> str:
    """清理 file_title 中的非法文件名字符，用于失败现场落盘"""
    return re.sub(r'[\\/:*?"<>|]', '_', name)


def _encode_with_retry(text_batch: list):
    """单批编码 + 线性退避重试；重试耗尽后向上抛异常，由 process 统一做现场保留"""
    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            return get_bge_embedding(text_batch)
        except Exception as e:
            if attempt == EMBED_MAX_RETRIES:
                raise
            wait = EMBED_RETRY_BASE_INTERVAL * attempt
            logger.warning(f'批次编码失败（第 {attempt} 次）: {e}，{wait}s 后重试')
            time.sleep(wait)


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

        file_title = state.get("file_title", "")

        # ① 拼接编码文本（唯一事实来源）：entity_name-content
        #    下游 node_import_milvus 直接读 chunk['content'] 落库，不再重复拼接
        chunk_content_list = [
            build_entity_content(chunk.get("entity_name", ""), chunk.get("content", ""))
            for chunk in chunks
        ]

        try:
            # ② 分批编码：单批失败只重试单批，避免一条异常毁掉整批（批量耦合）
            batch_size = EmbeddingConfig.bge_batch_size
            dense_list, sparse_list = [], []
            for start in range(0, len(chunk_content_list), batch_size):
                text_batch = chunk_content_list[start:start + batch_size]
                emb = _encode_with_retry(text_batch)
                dense_batch = emb.get('dense')
                sparse_batch = emb.get('sparse')
                if not dense_batch or not sparse_batch or len(dense_batch) != len(text_batch):
                    raise Exception(f'编码返回条数({len(dense_batch) if dense_batch else 0})与批次大小({len(text_batch)})不一致')
                dense_list.extend(dense_batch)
                sparse_list.extend(sparse_batch)
        except Exception as e:
            # ③ 现场保留：落盘"已识别未向量化"的 chunks，重跑时可跳过前序节点
            #    （PDF 转换、图片摘要、LLM 识别全部无需重来）
            self._save_pending_chunks(file_title, chunks)
            logger.error(f'向量化失败: {e}，已识别的切片已落盘，重跑时可跳过前序节点直接以落盘文件为输入')
            raise

        # ④ 回填向量 + 写回拼接文本：content 从此携带 entity_name 前缀，下游只读不拼
        for idx, chunk in enumerate(chunks):
            chunk['dense_vector'] = dense_list[idx]
            chunk['sparse_vector'] = sparse_list[idx]
            chunk['content'] = chunk_content_list[idx]

        logger.info(f'向量化完成，共处理 {len(chunks)} 条')
        return {'chunks': chunks}

    @staticmethod
    def _save_pending_chunks(file_title: str, chunks: list):
        """向量化失败时将已识别切片落盘，供重跑跳过前序节点（尽力而为，不影响原始异常抛出）"""
        try:
            PENDING_DIR.mkdir(parents=True, exist_ok=True)
            safe_title = _sanitize_filename(file_title) or 'unknown'
            pending_path = PENDING_DIR / f'chunks_pending_bge_{safe_title}.json'
            # 剔除向量字段：既有向量可能是 numpy 对象，不可直接 json 序列化
            pending_chunks = [
                {k: v for k, v in chunk.items() if k not in ('dense_vector', 'sparse_vector')}
                for chunk in chunks
            ]
            with open(pending_path, 'w', encoding='utf-8') as f:
                json.dump(pending_chunks, f, ensure_ascii=False, indent=2)
            logger.info(f'失败现场已保留: {pending_path}')
        except Exception as save_err:
            logger.error(f'失败现场落盘异常（不影响原始异常抛出）: {save_err}')


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
    # logger.info(json_format(res))
    output_path = Path(__file__).parent.parent.parent / 'data' / 'chunks_bge.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        # f.write(json.dumps(res, ensure_ascii=False, indent=4))
        json.dump(res['chunks'], f, ensure_ascii=False, indent=4)
    # logger.info(json_format(res))
