"""
author: anrf
date:8/10/2026
desc:
"""

from typing import List

from langchain.chat_models import init_chat_model
from pydantic import BaseModel

from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.propmt import *
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.bgem3_client_tool import get_bge_embedding
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client, create_reqs, search_hybrid
from atguigu.tool.mongo_client_tool import add_or_update_history, get_chat_history_list, clear_history, \
    update_history_item_names

# 格式化输出
class ItemExtractResult(BaseModel):
    """LLM 结构化输出的 schema"""
    item_names: List[str]
    rewritten_query: str


class NodeItemNameConfirm(NodeBase):
    """
    节点功能：确认用户问题中的核心商品名称。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_item_name_confirm"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        logger.info(f"【{self.name}】节点逻辑")
        session_id = state.get('session_id','')
        if not session_id:
            logger.error("会话ID为空")
            raise Exception("会话ID为空")

        original_query = state.get('original_query','')
        if not original_query:
            logger.error("原始查询为空")
            raise Exception("原始查询为空")

        message_id = add_or_update_history(session_id,'user',original_query)
        user_message_id = message_id  # 保存用户消息ID，后续 update_history_item_names 只更新当前用户消息
        logger.info(f"会话ID:{session_id},消息ID:{message_id},原始查询:{original_query}")
        # 汇总历史会话消息给到大模型
        history_list = get_chat_history_list(session_id)
        content_parts = []
        for history in history_list:
            role = history.get('role','')
            text = history.get('text','')
            rewritten = history.get('rewritten_query','')
            # 将上一轮的查询改写也传给 LLM，确保用户确认主题时能带上原始问题上下文
            # 只展示历史消息的 rewritten_query，跳过当前用户消息自身（text == original_query）
            if rewritten and text != original_query:
                history_content = f"{role}:{text}\n[上轮查询改写：{rewritten}]\n"
            else:
                history_content = f"{role}:{text}\n"
            content_parts.append(history_content)
        content = ''.join(content_parts)
        logger.info(f"历史会话汇总:{content}")

        llm = init_chat_model(
            model_provider='openai',
            model=LLMConfig.llm_default_model,
            temperature=LLMConfig.llm_default_temperature,
            api_key = LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_base_url,

        )
        message = [
            {"role": "system", "content": ITEM_NAME_EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": ITEM_NAME_EXTRACT_TEMPLATE.format(history_text=content, original_query=original_query)}
        ]
        # 格式化输出
        structured_llm = llm.with_structured_output(ItemExtractResult)
        result = structured_llm.invoke(message)
        # 获取查询改写和转移后的商品名称.查询改写字段可以直接存储
        logger.info(f"LLM Response: item_names={result.item_names}, rewritten_query={result.rewritten_query}")
        # 去除空格 + 统一小写：与导入端一致，消除 LLM 大小写不稳定的影响
        item_names_list = [
            ''.join(item_name.split()).lower() for item_name in result.item_names
        ]
        logger.info(f"商品名称列表: {item_names_list}")
        if not result.rewritten_query:
            result.rewritten_query = original_query


        # 向量数据库匹配真实的商品名称
        if item_names_list:
            embeddings = get_bge_embedding(item_names_list)
            collection_name = MilvusConfig.item_name_collection
            final_search_item_names_list = []
            for idx, item_name in enumerate(item_names_list):

                dense_data = embeddings.get('dense')[idx]
                sparse_data = embeddings.get('sparse')[idx]
                # logger.info(f"dense_data_type: {type(dense_data)}, sparse_data_type:{type(sparse_data)}")

                reqs = create_reqs(
                    # AnnSearchRequest 需要的data格式是list
                    dense_data=[dense_data],
                    sparse_data=[sparse_data],
                    dense_anns_field="dense_vector",
                    sparse_anns_field="sparse_vector",

                )
                hybrid_result = search_hybrid(
                    collection_name=collection_name,
                    reqs=reqs,
                    ranker=(0.8, 0.2),
                    limit=10,
                    output_fields=['entity_name']
                )
                # logger.info(f"混合搜索结果: {hybrid_result}")
                res = hybrid_result[0]
                # logger.info(json_format(res))
                search_item_names_list = [
                    {
                        'origin_item_name': item_name,
                        'search_item_name': item.get('entity', {}).get('entity_name',''),
                        'score': item.get('distance','')
                    }
                    for item in res
                ]
                final_search_item_names_list.extend(search_item_names_list)
                logger.info(f"搜索商品名称: {final_search_item_names_list}")
                # 根据置信度判断走哪条路线,补充商品名称和答案字段
                option_item_names = [item.get('search_item_name') for item in final_search_item_names_list
                                      if item.get('score') >= 0.6 and item.get('score') < 0.85 ]

                confirm_item_names = [item.get('search_item_name') for item in final_search_item_names_list
                                      if item.get('score') >= 0.85]
                # 四条路线分支
                if confirm_item_names:
                    final_item_names = confirm_item_names
                    answer = ''
                elif option_item_names:
                    final_item_names = []
                    answer = f'请确认你要咨询的商品是以下的哪个?\n{",".join(option_item_names)}'
                else:
                    final_item_names = []
                    answer = '无法确定商品名称，请重新描述。'
                # 回填历史记录列表字段,因为刚刚可能执行了插入数据操作,需要再拿一次历史会话消息
                if answer:
                    add_or_update_history(session_id, 'assistant', answer)

                # 只更新当前用户消息的 rewritten_query/item_names，不污染历史消息
                update_history_item_names([user_message_id], rewritten_query=result.rewritten_query, item_names=final_item_names)
                # 将 _id 转为字符串，避免 JSON 序列化报错❌️
                history_list = get_chat_history_list(session_id, limit=10)
                for h in history_list:
                    h['_id'] = str(h['_id'])
        else:
            # LLM 未提取到任何商品名（非商品类问题），走通用问答路径
            final_item_names = []
            answer = ''
            history_list = get_chat_history_list(session_id, limit=10)
            for h in history_list:
                h['_id'] = str(h['_id'])
        return {
            'message_id' : message_id,
            "session_id": session_id,
            "original_query": original_query,
            "rewritten_query": result.rewritten_query,
            "item_names": final_item_names,
            'answer': answer,
            'history_list': history_list
        }

if __name__ == "__main__":

    # 模拟会话历史
    session_id = "test_001"
    delete_message = clear_history(session_id)
    add_or_update_history(session_id, "user", "咨询下烫金机。")
    add_or_update_history(session_id, "assistant", "您好。请问是哪个型号")
    add_or_update_history(session_id, "user", "hak180")
    add_or_update_history(session_id, "assistant", "具体有什么问题呢？")

    # 初始化图状态
    init_state = {
        "session_id": "test_001",
        "original_query": "咋用？"
    }

    # 创建节点对象
    node_item_name_confirm = NodeItemNameConfirm()
    # 执行节点的单元测试
    result = node_item_name_confirm(init_state)
    # 将返回的图状态进行json序列化
    logger.info(json_format(result))
