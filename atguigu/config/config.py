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
    openai_base_url = os.getenv('OPENAI_API_BASE')
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

class EmbeddingConfig:
    bge_m3_path=os.getenv("BGE_M3_PATH")
    bge_m3=os.getenv("BGE_M3")
    bge_device=os.getenv("BGE_DEVICE")
    # 特殊处理：将.env中的1/0转为布尔值，兼容常见的数字/字符串格式
    bge_fp16=os.getenv("BGE_FP16") in ("1", "True", "true", 1)
    bge_batch_size=int(os.getenv("BGE_BATCH_SIZE", "32"))

class MilvusConfig:
    milvus_url=os.getenv("MILVUS_URL")
    chunks_collection=os.getenv("CHUNKS_COLLECTION")
    item_name_collection=os.getenv("ITEM_NAME_COLLECTION")

class MongoConfig:
    mongo_url=os.getenv("MONGO_URL")
    mongo_db_name=os.getenv("MONGO_DB_NAME")

class McpConfig:
    mcp_base_url=os.getenv("MCP_DASHSCOPE_BASE_URL")
    api_key=os.getenv("OPENAI_API_KEY")