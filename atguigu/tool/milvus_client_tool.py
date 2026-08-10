"""
author: anrf
date:8/8/2026
desc:
"""
from pymilvus import MilvusClient

from atguigu.config.config import MilvusConfig
from atguigu.tool.logger import logger

milvus_client = None
def get_milvus_client():
    global milvus_client
    if not milvus_client:
        milvus_client = MilvusClient(
            uri=MilvusConfig.milvus_url,
            timeout=30  # 连接超时30秒
        )
    return milvus_client

