"""
author: anrf
date:8/10/2026
desc:
"""
import re
from typing import List

from langchain.chat_models import init_chat_model
from pydantic import BaseModel

from atguigu.config.config import ItemConfirmConfig, LLMConfig, MilvusConfig
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

    # 疑似型号 token 正则：G6 / P7i / hak180 / MONA M03（规则优先，命中则跳过 LLM）
    MODEL_TOKEN_PATTERN = re.compile(r'[A-Za-z]{1,8}[- ]?\d{1,5}[A-Za-z0-9]*')

    def _extract_model_tokens(self, query: str) -> list:
        """规则提取结构化型号 token：命中即跳过 LLM，零幻觉零成本"""
        tokens = self.MODEL_TOKEN_PATTERN.findall(query)
        # 归一化与导入端一致：去空格 + 小写
        return [''.join(token.split()).lower() for token in tokens]

    @staticmethod
    def _get_last_confirmed_item_names(history_list: list):
        """倒序找最近一条 item_names 非空的历史消息（快速通道复用）"""
        for history in reversed(history_list):
            item_names = history.get('item_names') or []
            if item_names:
                return item_names
        return None

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

        # 兜底初始化：LLM 提取不到商品名时也不会 NameError
        final_item_names = []
        answer = ''
        history_list = []

        # ① 写入用户消息（持久化优先，拿当前轮 message_id 用于精确回填）
        message_id = add_or_update_history(session_id,'user',original_query)
        logger.info(f"会话ID:{session_id},消息ID:{message_id},原始查询:{original_query}")

        # ② 汇总历史会话消息给到大模型
        history_list = get_chat_history_list(session_id)
        content = ''
        for history in history_list:
            role = history.get('role','')
            text = history.get('text','')
            content += f"{role}:{text}\n"
        logger.info(f"历史会话汇总:{content}")

        # ③ 规则前置：先匹配结构化型号（G6/P7i/hak180），命中则跳过 LLM
        rule_item_names = self._extract_model_tokens(original_query)
        if rule_item_names:
            item_names_list = rule_item_names
            rewritten_query = original_query
            logger.info(f'规则命中型号: {rule_item_names}, 跳过 LLM 提取')
        else:
            # ④ 快速通道：历史已有已确认 item_names 且当前无新主体 → 直接复用，跳过 LLM + Milvus
            reuse_item_names = self._get_last_confirmed_item_names(history_list)
            if reuse_item_names:
                final_item_names = reuse_item_names
                rewritten_query = original_query
                logger.info(f'复用历史已确认商品名: {reuse_item_names}, 跳过 LLM + Milvus')
                # 回填当前轮 user 消息，保持每轮历史自洽
                update_history_item_names([message_id], rewritten_query=rewritten_query, item_names=final_item_names)
                history_list = get_chat_history_list(session_id, limit=10)
                for h in history_list:
                    h['_id'] = str(h['_id'])
                return {
                    'message_id' : message_id,
                    "session_id": session_id,
                    "original_query": original_query,
                    "rewritten_query": rewritten_query,
                    "item_names": final_item_names,
                    'answer': answer,
                    'history_list': history_list
                }

            # ⑤ LLM 提取（try/except 兜底：失败降级为原始查询，不拖垮链路）
            try:
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
                rewritten_query = result.rewritten_query or original_query
            except Exception as e:
                logger.error(f'LLM 提取失败: {e}, 降级为原始查询')
                item_names_list = []
                rewritten_query = original_query

        # ⑥ 向量数据库匹配真实的商品名称（try/except 兜底：失败降级为按原始说法进下游检索）
        if item_names_list:
            try:
                embeddings = get_bge_embedding(item_names_list)
                collection_name = MilvusConfig.item_name_collection
                final_search_item_names_list = []
                for idx, item_name in enumerate(item_names_list):

                    dense_data = embeddings.get('dense')[idx]
                    sparse_data = embeddings.get('sparse')[idx]
                    logger.info(f"dense_data_type: {type(dense_data)}, sparse_data_type:{type(sparse_data)}")

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
                    logger.info(f"混合搜索结果: {hybrid_result}")
                    res = hybrid_result[0]
                    logger.info(json_format(hybrid_result[0]))
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

                # ⑦ 置信度分支路由：confirm 与 option 独立处理，多商品逐个路由不吞候选
                option_item_names = [item.get('search_item_name') for item in final_search_item_names_list
                                      if item.get('score') >= ItemConfirmConfig.option_threshold
                                      and item.get('score') < ItemConfirmConfig.confirm_threshold]

                confirm_item_names = [item.get('search_item_name') for item in final_search_item_names_list
                                      if item.get('score') >= ItemConfirmConfig.confirm_threshold]

                if confirm_item_names and option_item_names:
                    # 部分确定 + 部分候选：确定的进 final，候选单独反问，不静默丢弃
                    final_item_names = confirm_item_names
                    answer = (f'已确定 {",".join(confirm_item_names)}；'
                              f'{",".join(option_item_names)} 是否也是你要咨询的商品?')
                elif confirm_item_names:
                    final_item_names = confirm_item_names
                    answer = ''
                elif option_item_names:
                    final_item_names = []
                    answer = f'请确认你要咨询的商品是以下的哪个?\n{",".join(option_item_names)}'
                else:
                    final_item_names = []
                    answer = '无法确定商品名称，请重新描述。'
            except Exception as e:
                # Milvus 降级：按原始说法进下游检索，不拖垮链路
                logger.error(f'Milvus 对齐失败: {e}, 降级为按原始说法进下游检索')
                final_item_names = item_names_list
                answer = ''
        else:
            # 规则与 LLM 均未提取到商品名
            answer = '无法确定商品名称，请重新描述。'

        # ⑧ 反问/提示写入 assistant 消息（answer 非空时）
        if answer:
            add_or_update_history(session_id, 'assistant', answer)

        # ⑨ 精确定位回填当前轮 user 消息（只更新这一条，不批量覆盖历史窗口）
        update_history_item_names([message_id], rewritten_query=rewritten_query, item_names=final_item_names)

        # ⑩ 重查历史拿最新数据 + _id 转 str，防止 JSON 序列化报错
        history_list = get_chat_history_list(session_id, limit=10)
        for h in history_list:
            h['_id'] = str(h['_id'])

        return {
            'message_id' : message_id,
            "session_id": session_id,
            "original_query": original_query,
            "rewritten_query": rewritten_query,
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
