"""
author: anrf
date:8/1/2026
desc:
"""
import os

from dotenv import load_dotenv

load_dotenv(override=True)

class MineruConfig :
    """
    Mineru配置类
    """
    mineru_token = os.getenv('MINERU_TOKEN')
    mineru_base_url = os.getenv('MINERU_BASE_URL')

class LLMConfig:
    openai_api_key = os.getenv('OPENAI_API_KEY')
    openai_base_url = os.getenv('OPENAI_BASE_URL')
    # 默认 LLM 模型
    llm_default_model = os.getenv('LLM_DEFAULT_MODEL')
    # 默认温度参数（0-1，越低越稳定）
    llm_default_temperature = float(os.getenv('LLM_DEFAULT_TEMPERATURE'))
    # 视觉语言模型
    vl_model = os.getenv('VL_MODEL')
    # 商品名识别模型
    item_model = os.getenv('ITEM_MODEL')

class MinIoConfig:
    minio_endpoint = os.getenv("MINIO_ENDPOINT")
    minio_access_key = os.getenv("MINIO_ACCESS_KEY")
    minio_secret_key = os.getenv("MINIO_SECRET_KEY")
    minio_bucket_name = os.getenv("MINIO_BUCKET_NAME")
    minio_img_dir = os.getenv("MINIO_IMG_DIR")