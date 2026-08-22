"""
author: anrf
date:8/4/2026
desc:
"""
import json
import threading

from minio import Minio

from atguigu.tool.logger import *
from atguigu.config.config import *


minio_client = None
# MinIO 客户端创建锁：初始化包含 bucket 检查/创建/策略设置，多线程首次调用同时执行
# 会导致 bucket 重复创建竞态和策略覆盖冲突
_minio_client_lock = threading.Lock()

def get_client():
    global minio_client
    if not minio_client:
        with _minio_client_lock:
            if not minio_client:
                try:
                    minio_client = Minio(
                        endpoint=MinIoConfig.minio_endpoint,
                        access_key=MinIoConfig.minio_access_key,
                        secret_key=MinIoConfig.minio_secret_key,
                        secure=False,
                    )

                    bucket_name = MinIoConfig.minio_bucket_name
                    if not minio_client.bucket_exists(bucket_name):
                        minio_client.make_bucket(bucket_name)

                    # 读公开,写认证
                    policy = {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"AWS": "*"},
                                "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                                "Resource": f"arn:aws:s3:::{bucket_name}",
                            },
                            {
                                "Effect": "Allow",
                                "Principal": {"AWS": "*"},
                                "Action": ["s3:GetObject", "s3:DeleteObject"],
                                # "Action": ["s3:GetObject"],
                                "Resource": f"arn:aws:s3:::{bucket_name}/*",
                            },
                        ],
                    }
                    minio_client.set_bucket_policy(bucket_name=bucket_name, policy=json.dumps(policy))

                except Exception as e:
                    logger.error(f'minio客户端初始化失败:{e}')

    return minio_client

if __name__ == '__main__':
    get_client()