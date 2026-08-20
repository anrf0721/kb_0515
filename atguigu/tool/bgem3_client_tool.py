"""
author: anrf
date:8/7/2026
desc:
"""
import threading
import time

from pymilvus.model.hybrid import BGEM3EmbeddingFunction

from atguigu.config.config import EmbeddingConfig
from atguigu.tool.logger import *

bgem3_client_model = None
# 模型加载锁：懒加载的"检查-创建"非原子，多线程并发首次调用会各自创建实例，
# 导致多个模型同时加载到 GPU（显存叠加、CUDA 上下文竞争），编码结果可能异常
_bge_model_lock = threading.Lock()

def get_bge_model():
    global  bgem3_client_model
    if not bgem3_client_model:
        with _bge_model_lock:
            # 双重检查：拿到锁后再次确认，防止其他线程已创建
            if not bgem3_client_model:
                bgem3_client_model = BGEM3EmbeddingFunction(
                    model_name=EmbeddingConfig.bge_m3_path,
                    device = EmbeddingConfig.bge_device,
                    use_fp16=EmbeddingConfig.bge_fp16,
                    batch_size=EmbeddingConfig.bge_batch_size,
         )
    return bgem3_client_model

# 全局推理锁：模型是进程级单例，多用户并发时串行化前向传播，
# 防止 GPU 显存叠加 OOM / CPU 线程池竞争导致性能退化
_bge_infer_lock = threading.Lock()

# 空结果/瞬时异常重试上限：偶发竞态问题重试即可恢复；
# 连续失败属于系统性问题（显存不足/模型损坏），fail-fast 向上抛
_BGE_ENCODE_MAX_RETRIES = 3


def _encode_once(model, text: list) -> tuple[list, list]:
    """单次编码 + dense/sparse 结构转换，供重试循环复用"""
    embedding = model.encode_documents(text)
    dense = [item.tolist() for item in embedding.get('dense')]
    sparse = [dict(zip(
        item.indices.tolist(),
        item.data.tolist()
    )) for item in embedding.get('sparse')]
    return dense, sparse


def get_bge_embedding(text:list):
    if not text:
        # 空输入重试无意义，快速失败
        raise ValueError('BGE 编码输入为空列表')
    bgem3_client_model = get_bge_model()
    # 防御：模型加载竞态/显存竞争下偶发空结果或瞬时异常（如 CUDA OOM），
    # 轮询重试 + 指数退避；校验非空且条数与输入一致（防下游按下标错位取值），
    # 避免下游直接取 [0] 触发 list index out of range
    last_err = None
    for attempt in range(1, _BGE_ENCODE_MAX_RETRIES + 1):
        try:
            with _bge_infer_lock:
                dense, sparse = _encode_once(bgem3_client_model, text)
            if dense and sparse and len(dense) == len(text) and len(sparse) == len(text):
                return {'dense': dense, 'sparse': sparse}
            last_err = RuntimeError(
                f'BGE 编码结果为空或条数不齐: 输入条数={len(text)}, dense条数={len(dense)}, '
                f'sparse条数={len(sparse)}, 输入前100字符={text[0][:100]}'
            )
            logger.warning(f'BGE 编码结果异常, 第{attempt}/{_BGE_ENCODE_MAX_RETRIES}次')
        except Exception as e:
            last_err = e
            logger.warning(f'BGE 编码异常, 第{attempt}/{_BGE_ENCODE_MAX_RETRIES}次, 错误:{e}')
        if attempt < _BGE_ENCODE_MAX_RETRIES:
            time.sleep(2 ** attempt)  # 指数退避，给瞬时显存竞争留恢复时间
    raise RuntimeError(
        f'BGE 编码连续 {_BGE_ENCODE_MAX_RETRIES} 次失败: 输入条数={len(text)}, '
        f'输入前100字符={text[0][:100]}'
    ) from last_err

if __name__ == '__main__':
    print(get_bge_embedding(['hello world','haha']))
