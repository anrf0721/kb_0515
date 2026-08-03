"""
author: anrf
date:7/31/2026
desc:
改动记录 (2026-08-03)：
  ① 加 import asyncio, random
  ② process 拆为同步入口 + 异步核心 _process_async
  ③ 外层串行 for → asyncio.gather 并发
  ④ 加 asyncio.Semaphore(5) 控制并发数
  ⑤ llm.invoke() 包 asyncio.to_thread + 指数退避重试(最多5次)
  ⑥ time.sleep → await asyncio.sleep，滑动窗口 deque 逻辑保留
  ⑦ logger 移到 gather 之后汇总
  ⑧ 加 TPM 限速：token_dq 滑动窗口 + asyncio.Lock
"""
import asyncio
import base64
import os
import random
import re
import time
from collections import deque
from pathlib import Path

from langchain.chat_models import init_chat_model

from atguigu.config.config import *
from atguigu.import_process.base import *
from atguigu.import_process.state import *
from atguigu.tool.logger import *
from atguigu.tool.json_dumps_tool import *


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    MAX_RETRIES = 5          # LLM 调用最多重试次数
    MAX_CONCURRENT = 5       # 并发上限
    MAX_RPM = 30             # RPM 上限（Requests Per Minute，每分钟请求数）
    MAX_TPM = 200_000        # TPM 上限（Tokens Per Minute，每分钟 Token 数）
    TPM_WINDOW = 60          # TPM 滑动窗口（秒）
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    MAX_CONTEXT_LENGTH = 250

    # ── 异步核心 ──────────────────────────────────────────
    async def _process_async(self, state: ImportGraphState):
        md_path = state.get('md_path', '')
        if not md_path:
            logger.error('路径没有提供')
            raise Exception('路径没有提供')
        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error('文件不存在')
            raise Exception('文件不存在')

        with open(md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()
            if not md_content:
                logger.error('文件内容为空')
                raise Exception('文件内容为空')
            image_path_obj = md_path_obj.parent / 'images'
            if not image_path_obj.exists():
                logger.info('图片不存在')
                return {'md_content': md_content}

            image_name_list = os.listdir(image_path_obj)
            if not image_name_list:
                logger.info('图片目录不存在')
                return {'md_content': md_content}
        logger.info(f'图片目录下文件数量:{len(image_name_list)}')

        llm = init_chat_model(
            model=LLMConfig.llm_default_model,
            model_provider='openai',
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_base_url,
            temperature=LLMConfig.llm_default_temperature
        )

        # Semaphore 控制并发
        sem = asyncio.Semaphore(self.MAX_CONCURRENT)
        # RPM 滑动窗口：存请求时间戳，maxlen = MAX_RPM
        dq = deque(maxlen=self.MAX_RPM)
        # TPM 滑动窗口：存 (timestamp, token_count)，用 Lock 保护并发读写
        token_dq = deque()
        token_lock = asyncio.Lock()

        async def process_one(image_name: str):
            """处理单张图片：限速 + 重试 + LLM 调用"""
            async with sem:
                # ── 校验图片 ──
                if Path(image_name).suffix.lower() not in self.IMAGE_EXTENSIONS:
                    logger.warning(f'图片格式错误:{image_name}')
                    return None

                # ── 提取上下文 ──
                pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")
                match = pattern.search(md_content)
                if not match:
                    logger.warning(f'图片未引用:{image_name}')
                    return None
                start, end = match.span()
                pre_text = md_content[max(0, start - self.MAX_CONTEXT_LENGTH):start]
                post_text = md_content[end:min(len(md_content), end + self.MAX_CONTEXT_LENGTH)]

                # ── RPM 限速 ──
                current_time = time.time()
                while dq and current_time - dq[0] > 60:
                    dq.popleft()
                if dq and len(dq) == dq.maxlen:
                    need_wait = 60 - (current_time - dq[0])
                    if need_wait > 0:
                        logger.warning(f'RPM限速等待:{need_wait:.1f}s ({image_name})')
                        await asyncio.sleep(need_wait)
                        current_time = time.time()
                        while dq and current_time - dq[0] > 60:
                            dq.popleft()
                dq.append(current_time)

                # ── TPM 限速 ──
                # TPM 没有 maxlen，且需要遍历整个 deque 做 sum,必须加锁,否则计数会出错
                async with token_lock:
                    now = time.time()
                    while token_dq and now - token_dq[0][0] > self.TPM_WINDOW:
                        token_dq.popleft()
                    tpm_used = sum(t[1] for t in token_dq)
                    if tpm_used >= self.MAX_TPM and token_dq:
                        wait_time = self.TPM_WINDOW - (now - token_dq[0][0]) + 0.1
                        logger.warning(f'TPM超限(已用{tpm_used}/{self.MAX_TPM}),等待{wait_time:.1f}s')
                        await asyncio.sleep(wait_time)
                        now = time.time()
                        while token_dq and now - token_dq[0][0] > self.TPM_WINDOW:
                            token_dq.popleft()

                # ── 读图片 + base64 ──
                image_path = str(image_path_obj / image_name)
                with open(image_path, 'rb') as f_img:
                    image_data = f_img.read()
                    base64_image_data = base64.b64encode(image_data).decode('utf-8')

                # ── 拼 messages ──
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/png;base64,{base64_image_data}"}},
                            {"type": "text",
                             "text": f"请根据图片的上文{pre_text},图片的后文{post_text}，给出图片的摘要，请使用中文,30字以内。"},
                        ],
                    },
                ]

                # ── 调 LLM（asyncio.to_thread + 指数退避重试） ──
                for attempt in range(self.MAX_RETRIES):
                    try:
                        res = await asyncio.to_thread(llm.invoke, messages)
                        break
                    except Exception as e:
                        if attempt == self.MAX_RETRIES - 1:
                            logger.error(f'LLM调用失败({image_name}),已重试{self.MAX_RETRIES}次:{e}')
                            raise
                        # 保护性机制,防止被抓包
                        backoff = 2 ** attempt + random.uniform(0, 1)
                        logger.warning(f'LLM调用失败({image_name}),第{attempt+1}次重试,等待{backoff:.1f}s:{e}')
                        await asyncio.sleep(backoff)

                # ── 记录 TPM 消耗 ──
                usage = getattr(res, 'usage_metadata', {})
                total_tokens = usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
                if not total_tokens:
                    resp_usage = getattr(res, 'response_metadata', {}).get('token_usage', {})
                    total_tokens = resp_usage.get('total_tokens', 0)
                async with token_lock:
                    token_dq.append((time.time(), total_tokens))

                return {
                    'image_name': image_name,
                    'image_path': image_path,
                    'summary': res.content
                }

        # 并发执行所有图片
        tasks = [process_one(name) for name in image_name_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        image_context_summary_list = []
        for i, r in enumerate(results):
            if isinstance(r, dict):
                image_context_summary_list.append(r)
            elif r is not None:
                logger.error(f'图片处理异常:{image_name_list[i]}:{r}')

        logger.info(f'图片处理结果:{json_format(image_context_summary_list)}')
        return state

    # ── 同步入口（保持接口兼容）──────────────────────────
    def process(self, state: ImportGraphState):
        return asyncio.run(self._process_async(state))


if __name__ == '__main__':
    node = NodeMDImg()
    init_state = {
        'md_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册.md'
    }
    res = node(init_state)
    logger.info(json_format(res))
