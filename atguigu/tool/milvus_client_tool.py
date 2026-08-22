"""
author: anrf
date:8/8/2026
desc:
"""
import threading

from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker
from atguigu.config.config import MilvusConfig
from atguigu.tool.logger import logger

milvus_client = None
# 连接创建锁：懒加载的检查-创建非原子，多线程并发首次调用会各自创建 gRPC 连接池，
# 浪费连接资源；MilvusClient 本身线程安全，多线程可共享同一实例
_milvus_client_lock = threading.Lock()

def get_milvus_client():
    global milvus_client
    if not milvus_client:
        with _milvus_client_lock:
            if not milvus_client:
                milvus_client = MilvusClient(
                    uri=MilvusConfig.milvus_url,
                    timeout=30  # 连接超时30秒
                )
    return milvus_client

def create_reqs(
        dense_data,
        sparse_data,
        dense_anns_field: str,
        sparse_anns_field: str,
        dense_param = None,
        sparse_param = None,
        dense_limit: int = None,
        sparse_limit: int = None,
        expr = None,

):
    if not dense_param:
        dense_param = {
            'metric_type': 'COSINE',
            'params': {
                'nprobe': 10
            }
        }
    if not sparse_param:
        sparse_param = {
            'metric_type': 'IP',
        }
    dense_reqs = AnnSearchRequest(
        data=dense_data,
        anns_field=dense_anns_field,
        param=dense_param,
        limit=dense_limit,
        expr=expr,
    )
    sparse_reqs = AnnSearchRequest(
        data=sparse_data,
        anns_field=sparse_anns_field,
        param=sparse_param,
        limit=sparse_limit,
        expr=expr,
    )
    return [dense_reqs,sparse_reqs]

def search_hybrid(
        collection_name: str,
        reqs,
        ranker=(0.8,0.2),
        limit=10,
        output_fields=None
):
    milvus_client = get_milvus_client()
    weight_ranker = WeightedRanker(*ranker, norm_score=True)
    result = milvus_client.hybrid_search(
        collection_name=collection_name,
        reqs=reqs,
        ranker=weight_ranker,
        limit=limit,
        output_fields=output_fields
    )
    return result