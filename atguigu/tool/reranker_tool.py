"""
author: anrf
date:8/14/2026
desc:
"""
from http import HTTPStatus
from atguigu.tool.logger import logger

import dashscope

from atguigu.config.config import RerankConfig

dashscope.base_http_api_url = RerankConfig.rerank_base_url
dashscope.api_key = RerankConfig.rerank_api_key


def text_rerank(query, documents, limit):
    try:
        resp = dashscope.TextReRank.call(
            model="qwen3-rerank",
            query=query,
            documents=documents,
            top_n=limit,
            return_documents=True,
            instruct="Given a web search query, retrieve relevant passages that answer the query."
        )
        if resp.status_code == HTTPStatus.OK:
            # print(resp)
            return [
                {
                    "score": item['relevance_score'],
                    "index": item['index']
                }
                for item in resp['output']['results']
            ]
        else:
            logger.error(f'重排序失败: {resp.status_code} - {resp.message}')
            raise Exception(f'重排序失败: {resp.status_code} - {resp.message}')
    except Exception as e:
        logger.error(f'重排序失败: {e}')
        raise Exception(f'重排序失败: {e}')

if __name__ == '__main__':
    logger.info(text_rerank('你是谁', ['我是人', '我是千问', '我是豆包'], 10))