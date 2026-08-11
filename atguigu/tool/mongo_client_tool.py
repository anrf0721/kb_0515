"""
author: anrf
date:8/10/2026
desc:
"""
import time

from pymongo import MongoClient

from atguigu.config.config import MongoConfig
from atguigu.tool.logger import logger

mongo_client = None
def get_mongo_client():
    global mongo_client
    if not mongo_client:
        mongo_client = MongoClient(MongoConfig.mongo_url)
        logger.info('MongoDB 连接已建立')
    return mongo_client

mongo_collection = None
def get_mongo_collection():
    global mongo_collection
    mongo_client = get_mongo_client()
    mongo_db = mongo_client[MongoConfig.mongo_db_name]
    if mongo_collection is None:
        mongo_collection = mongo_db['chat_history']
        mongo_collection.create_index([('session_id', 1), ('ts', -1)])  # 核心：会话查消息
        mongo_collection.create_index([('ts', -1)])  # 辅助：时间范围浏览
    # logger.info(f"集合打印结果: {collection} ")
    return mongo_collection

def get_chat_history_list(session_id,limit=10):
    collection = get_mongo_collection()
    res = collection.find({'session_id': session_id}).sort([('ts', 1)]).limit(limit)
    return list(res)

def add_or_update_history(session_id,role,text,rewritten_query=None,item_names=None,ts=None,message_id=None):
    collection = get_mongo_collection()
    if message_id:
        # 修改操作
        data = {
            'session_id': session_id,
            'role': role,
            'text': text,
            'rewritten_query': rewritten_query,
            'item_names': item_names,
            'ts': ts or time.time()
        }
        collection.update_one({'_id': message_id}, {'$set': data})
    else:
        # 新增操作
        data = {
            'session_id': session_id,
            'role': role,
            'text': text,
            'rewritten_query': rewritten_query,
            'item_names': item_names,
            'ts': ts or time.time()
        }
        result = collection.insert_one(data)
        return str(result.inserted_id)
# # _id 和 message_id 解耦,实际没必要
# def add_or_update_history(message_id=None, session_id, role, text, rewritten_query=None, item_names=None, ts=None):
#     collection = get_mongo_collection()
#     data = {
#         'session_id': session_id,
#         'role': role,
#         'text': text,
#         'ts': ts or time.time()
#     }
#     if rewritten_query:
#         data['rewritten_query'] = rewritten_query
#     if item_names:
#         data['item_names'] = item_names
#     # message_id 一定存在 → upsert 一把梭
#     res = collection.update_one({'message_id': _id}, {'$set': data}, upsert=True)
#     return res

def clear_history(session_id):
    collection = get_mongo_collection()
    res = collection.delete_many({'session_id': session_id})
    logger.info(f"清空会话 {session_id} 的历史记录")
    return res

def update_history_item_names(message_id_list:list, rewritten_query, item_names, ts=None):
    collection = get_mongo_collection()
    data = {
        'item_names': item_names,
        'rewritten_query': rewritten_query,
        'ts': ts or time.time()
    }
    res = collection.update_many({'_id': {'$in': message_id_list}}, {'$set': data})
    logger.info(f'更新消息 {message_id_list} 的 item_names / rewritten_query')
    return res


if __name__ == '__main__':
    test_add_history1 = add_or_update_history('test_001','test_session_001','user','哈哈1')
    test_add_history2 = add_or_update_history('test_002','test_session_001','user','哈哈2')
    print(test_add_history1)
    test_get_history_text = get_chat_history_list('test_session_001',5)
    test_update_history_name = update_history_item_names('test_001','哈哈3','哈哈主题')
    print(test_get_history_text)
    # drop_test_list = clear_history(session_id='test_session_001')
    # print(drop_test_list)