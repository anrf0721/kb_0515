"""
author: anrf
date:8/10/2026
desc: 联网搜索节点 — 通过 MCP 协议调用外部搜索引擎，补充本地知识库之外的信息
"""
import asyncio
import json

from agents.mcp import MCPServerStreamableHttp

from atguigu.config.config import McpConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger


class NodeWebSearchMcp(NodeBase):
    """
    节点功能：调用外部搜索引擎补充信息
    """

    name: str = "node_web_search_mcp"

    def process(self, state: QueryGraphState):
        """
        节点逻辑
        :param state: 工作流状态对象
        :return: 更新后的状态对象
        """

        logger.info(f"【{self.name}】节点逻辑")
        rewritten_query = state.get("rewritten_query", '')
        if not rewritten_query:
            logger.error("用户问题改写为空")
            raise ValueError("用户问题改写为空")

        search_result = asyncio.run(self._search(rewritten_query))
        # logger.info(f"联网搜索结果: {search_result[:300]}...")

        return {
            "web_search_docs": [
                {
                    "content": item.get("snippet", ""),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "source": "web"
                }
            for item in search_result
            ]
        }

    async def _search(self, query: str) -> list:
        """
        直接通过 MCP 协议调用搜索引擎，无需 LLM 中转
        :param query: 改写后的用户查询
        :return: 搜索结果文本
        """
        async with MCPServerStreamableHttp(
            name="WebSearch MCP",
            params={
                "url": McpConfig.mcp_base_url,
                "headers": {"Authorization": f"Bearer {McpConfig.api_key}"},
                "timeout": 10,
            },
            cache_tools_list=True,
            max_retry_attempts=3,
            client_session_timeout_seconds=30,
        ) as server:
            result = await server.call_tool(
                "bailian_web_search",
                arguments={"query": query, "count": 10},
            )
            # result 是 CallToolResult，提取文本内容
            data = json.loads(result.content[0].text).get('pages')
            # logger.info(f"搜索结果: {data[:300]}...")
            return data


if __name__ == '__main__':
    init_state = {
        "rewritten_query": "关于hak180烫金机如何使用",
        "item_names": ["brotherhak180烫金机"]
    }
    node = NodeWebSearchMcp()
    result = node(init_state)
    logger.info(json_format(result))
