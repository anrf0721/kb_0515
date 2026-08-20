"""
author: anrf
date:8/10/2026
desc:
"""
import re
from langchain.chat_models import init_chat_model

from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.config.propmt import *
from atguigu.config.config import LLMConfig
from atguigu.tool.mongo_client_tool import add_or_update_history


class NodeAnswerOutput(NodeBase):
    """
    节点功能: 答案生成
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_answer_output"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        logger.info(f"【{self.name}】节点逻辑")
        task_id = state.get("task_id")
        session_id = state.get("session_id")
        original_query = state.get("original_query")
        answer = state.get("answer")
        if answer:
            # 商品名确认分支已直接生成答案，原样透传，不再重复生成
            return state
        else:
            chunks = state.get('reranked_docs') or []   # or [] 防护：上游未产出时为 None，直接遍历会报 'NoneType' object is not iterable
            chunk_content = ''
            for idx,chunk in enumerate(chunks,start=1):
                title = chunk['title']
                content = chunk['content']
                url = chunk['url']
                source = chunk['source']
                chunk_content += f"{idx}. {title}\n{content}\n{url}\n{source}\n"

            history = state.get("history") or []
            history_content = ''
            for h in history:
                h_content = f'{h["role"]} : {h["text"]}'
                history_content += h_content + '\n'

            item_names = state.get("item_names") or []
            item_names_str = ','.join(item_names)
            rewritten_query = state.get("rewritten_query")

            prompt = ANSWER_PROMPT.format(
                context = chunk_content,
                history = history_content,
                item_names = item_names_str,
                question = rewritten_query
            )[:10000]

            llm = init_chat_model(
                model_provider = 'openai',
                model = LLMConfig.llm_default_model,
                temperature = LLMConfig.llm_default_temperature,
                api_key = LLMConfig.openai_api_key,
                base_url = LLMConfig.openai_base_url
            )

            message = [
                {"role": "user", "content": prompt}
            ]
            res = llm.stream(input=message)
            answer = ''
            # 从 task_utils 取 emit 回调（跨模块共享注册表，不能从 query_service 导入，模块实例不同）
            from atguigu.tool.task_utils import get_emit
            emit = get_emit(task_id)
            for r in res:
                token = r.content
                answer += token
                if emit:
                    emit('delta', {'delta': token})  # 逐 token 推送到前端流式渲染

            seen = set()
            md_img_pattern = re.compile(r'!\[.*?\]\((.*?)\)')
            for i,doc in enumerate(chunks):
                text = doc['content']
                matches = md_img_pattern.findall(text)
                for match in matches:
                    if match not in seen:
                        seen.add(match.strip())
            images_list = list(seen)
            add_or_update_history(
                session_id,  # 必传参数，之前漏了
                "assistant",
                answer,
                rewritten_query=rewritten_query,
                item_names=item_names,
            )
        return {"answer": answer, "image_urls": images_list}
