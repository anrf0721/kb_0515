"""
清理 Milvus 脏数据 —— 删除旧的 chunks 和 item_name collection
运行后重新执行导入流程即可
"""
from atguigu.config.config import MilvusConfig
from atguigu.tool.milvus_client_tool import get_milvus_client
from atguigu.tool.logger import logger

if __name__ == '__main__':
    client = get_milvus_client()

    for name, collection in [
        ("CHUNKS_COLLECTION", MilvusConfig.chunks_collection),
        ("ITEM_NAME_COLLECTION", MilvusConfig.item_name_collection),
    ]:
        if client.has_collection(collection):
            client.drop_collection(collection)
            logger.info(f"✅ 已删除 collection: {collection}")
        else:
            logger.info(f"⏭️ collection 不存在，跳过: {collection}")

    logger.info("清理完成！请重新运行导入流程。")
