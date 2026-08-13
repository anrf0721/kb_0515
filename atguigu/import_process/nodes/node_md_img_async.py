"""
author: anrf
date:7/31/2026
desc:
改动记录 (2026-08-03)：
  ① 加 import asyncio
  ② process 拆为同步入口 + 异步核心 _process_async
  ③ 外层串行 for → asyncio.gather 并发
  ④ 加 asyncio.Semaphore(5) 控制并发数
  ⑤ llm.invoke() 包 asyncio.to_thread
  ⑥ time.sleep → await asyncio.sleep，滑动窗口 deque 逻辑保留
  ⑦ logger 移到 gather 之后汇总
  ⑧ 加 TPM 限速：token_dq 滑动窗口 + asyncio.Lock
改动记录 (2026-08-11)：
  ⑨ 补全 get_minio_url：MinIO 上传 + 预签名 URL + 替换 md 图片引用
  ⑩ 补全 read_image_obj 类方法，与同步版对齐
  ⑪ _process_async 三步走：read → summarize(异步) → minio → 返回 {md_path, md_content}
  ⑫ 移除指数退避重试：其他节点均无重试，且 return_exceptions=True 已兜底
改动记录 (2026-08-13)：
  ⑬ MinIO 图片按文件 stem 隔离子目录，仅清理本文件前缀（防多用户并发互删互盖）
  ⑭ RPM/TPM 限速窗口升级为进程级类属性 + threading.Lock（跨请求共享配额，锁外 sleep 防死锁）
"""
import asyncio
import base64
import os
import re
import threading
import time
from collections import deque
from datetime import timedelta
from pathlib import Path

from langchain.chat_models import init_chat_model
from minio.deleteobjects import DeleteObject

from atguigu.config.config import *
from atguigu.import_process.base import *
from atguigu.import_process.state import *
from atguigu.tool.logger import *
from atguigu.tool.json_dumps_tool import *
from atguigu.tool.minio_client_tool import *


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    MAX_CONCURRENT = 5       # 并发上限
    MAX_RPM = 30             # RPM 上限（Requests Per Minute）
    MAX_TPM = 200_000        # TPM 上限（Tokens Per Minute）
    TPM_WINDOW = 60          # TPM 滑动窗口（秒）
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    MAX_CONTEXT_LENGTH = 250

    # 进程级限速窗口：跨请求共享，防多用户并发时各自独立窗口叠加冲击 API 配额；
    # 用 threading.Lock（非 asyncio.Lock）保证多线程各自 asyncio.run 时跨事件循环安全，
    # 临界区内无 await，等待（sleep）一律在锁外执行
    _rpm_dq = deque(maxlen=MAX_RPM)
    _tpm_dq = deque()
    _rpm_lock = threading.Lock()
    _tpm_lock = threading.Lock()

    # ── 同步入口（保持接口兼容）──────────────────────────
    def process(self, state: ImportGraphState):
        return asyncio.run(self._process_async(state))

    # ── 异步核心：三步走 ──────────────────────────────────
    async def _process_async(self, state: ImportGraphState):
        # Step 1: 读取图片对象
        image_name_list, image_path_obj, md_content, md_path = self.read_image_obj(state)

        # Step 2: 异步生成图片摘要（并发 + 限速）
        image_context_summary_list = await self._image_summary_async(
            image_name_list, image_path_obj, md_content
        )

        # Step 3: MinIO 上传 + 预签名 URL + 替换 md 图片引用
        md_content, new_md_path = self.get_minio_url(
            image_context_summary_list, md_content, md_path
        )

        return {'md_path': str(new_md_path), 'md_content': md_content}

    # ── Step 1: 读取图片对象 ──────────────────────────────
    @classmethod
    def read_image_obj(cls, state: ImportGraphState):
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

            image_path_obj = md_path_obj.parent / 'images'
            if not image_path_obj.exists():
                logger.error('图片目录不存在')

            image_name_list = os.listdir(image_path_obj)
            if not image_name_list:
                logger.error('图片目录下图片不存在')

        logger.info(f'图片目录下文件数量:{len(image_name_list)}')
        return image_name_list, image_path_obj, md_content, md_path

    # ── Step 2: 异步生成图片摘要 ──────────────────────────
    async def _image_summary_async(self, image_name_list, image_path_obj, md_content):
        llm = init_chat_model(
            model=LLMConfig.llm_default_model,
            model_provider='openai',
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_base_url,
            temperature=LLMConfig.llm_default_temperature
        )

        sem = asyncio.Semaphore(self.MAX_CONCURRENT)

        async def process_one(image_name: str):
            """处理单张图片：限速 + LLM 调用"""
            async with sem:
                # ── 校验图片格式 ──
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

                # ── RPM 限速（进程级窗口，锁外 sleep）──
                current_time = time.time()
                with self._rpm_lock:
                    while self._rpm_dq and current_time - self._rpm_dq[0] > 60:
                        self._rpm_dq.popleft()
                    if self._rpm_dq and len(self._rpm_dq) == self._rpm_dq.maxlen:
                        need_wait = 60 - (current_time - self._rpm_dq[0])
                    else:
                        need_wait = 0
                if need_wait > 0:
                    logger.warning(f'RPM限速等待:{need_wait:.1f}s ({image_name})')
                    await asyncio.sleep(need_wait)
                    current_time = time.time()
                    with self._rpm_lock:
                        while self._rpm_dq and current_time - self._rpm_dq[0] > 60:
                            self._rpm_dq.popleft()
                with self._rpm_lock:
                    self._rpm_dq.append(current_time)

                # ── TPM 限速（进程级窗口，锁外 sleep）──
                with self._tpm_lock:
                    now = time.time()
                    while self._tpm_dq and now - self._tpm_dq[0][0] > self.TPM_WINDOW:
                        self._tpm_dq.popleft()
                    tpm_used = sum(t[1] for t in self._tpm_dq)
                    if tpm_used >= self.MAX_TPM and self._tpm_dq:
                        wait_time = self.TPM_WINDOW - (now - self._tpm_dq[0][0]) + 0.1
                    else:
                        wait_time = 0
                if wait_time > 0:
                    logger.warning(f'TPM超限(已用{tpm_used}/{self.MAX_TPM}),等待{wait_time:.1f}s')
                    await asyncio.sleep(wait_time)
                    with self._tpm_lock:
                        now = time.time()
                        while self._tpm_dq and now - self._tpm_dq[0][0] > self.TPM_WINDOW:
                            self._tpm_dq.popleft()

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

                # ── 调 LLM ──
                res = await asyncio.to_thread(llm.invoke, messages)

                # ── 记录 TPM 消耗 ──
                usage = getattr(res, 'usage_metadata', {})
                total_tokens = usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
                if not total_tokens:
                    resp_usage = getattr(res, 'response_metadata', {}).get('token_usage', {})
                    total_tokens = resp_usage.get('total_tokens', 0)
                # ── 记录 TPM 消耗（进程级窗口）──
                with self._tpm_lock:
                    self._tpm_dq.append((time.time(), total_tokens))
                return {
                    'image_name': image_name,
                    'image_path': image_path,
                    'summary': res.content
                }

        tasks = [process_one(name) for name in image_name_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        image_context_summary_list = []
        for i, r in enumerate(results):
            if isinstance(r, dict):
                image_context_summary_list.append(r)
            elif r is not None:
                logger.error(f'图片处理异常:{image_name_list[i]}:{r}')

        logger.info(f'图片处理结果:{json_format(image_context_summary_list)}')
        return image_context_summary_list

    # ── Step 3: MinIO 上传 + URL 替换 ─────────────────────
    def get_minio_url(self, image_context_summary_list, md_content, md_path):
        minio_client = get_client()
        upload_dir = MinIoConfig.minio_img_dir
        # 按文件 stem 隔离子目录：多用户并发上传时互不干扰，只清理当前文件自己的旧图
        file_prefix = f"{upload_dir}/{Path(md_path).stem}"

        # 清空旧图片（仅当前文件前缀）
        delete_image_obj = minio_client.list_objects(
            bucket_name=MinIoConfig.minio_bucket_name,
            prefix=file_prefix,
            recursive=True
        )
        delete_image_obj_list = [DeleteObject(i.object_name) for i in delete_image_obj]
        if delete_image_obj_list:
            errors = minio_client.remove_objects(
                bucket_name=MinIoConfig.minio_bucket_name,
                delete_object_list=delete_image_obj_list
            )
            logger.info(f"删除文件数: {len(delete_image_obj_list)}")
            for error in errors:
                logger.error(error)

        # 上传图片 + 生成预签名 URL（7 天有效）
        image_summary_with_context_and_url_list = []
        for image_with_context in image_context_summary_list:
            object_name = f"{file_prefix}/{image_with_context['image_name']}"
            minio_client.fput_object(
                bucket_name=MinIoConfig.minio_bucket_name,
                object_name=object_name,
                file_path=image_with_context['image_path']
            )
            url = minio_client.presigned_get_object(
                bucket_name=MinIoConfig.minio_bucket_name,
                object_name=object_name,
                expires=timedelta(days=7)
            )
            image_summary_with_context_and_url_list.append({
                **image_with_context,
                'url': url
            })
            logger.info(f'图片上传成功:{url}')

        # 替换 markdown 中图片引用 + 写入 _new.md
        for image_url_context in image_summary_with_context_and_url_list:
            patten = re.compile(
                r"!\[.*?\]\(.*?" + re.escape(image_url_context['image_name']) + r"\)"
            )
            md_content = patten.sub(
                f"![{image_url_context['summary']}]({image_url_context['url']})",
                md_content
            )
            new_md_path = Path(md_path).parent / str(Path(md_path).stem + '_new.md')
            with open(new_md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

        return md_content, new_md_path


if __name__ == '__main__':
    node = NodeMDImg()
    init_state = {
        'md_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册.md'
    }
    res = node(init_state)
    logger.info(json_format(res))
