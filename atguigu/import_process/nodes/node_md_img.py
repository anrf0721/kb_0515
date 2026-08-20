"""
author: anrf
date:7/31/2026
desc:
"""
import base64
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import quote

from langchain.chat_models import init_chat_model
from minio.deleteobjects import DeleteObject

from atguigu.config.config import *
from atguigu.import_process.base import *
from atguigu.import_process.state import *
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.logger import *
from atguigu.tool.json_dumps_tool import *
from atguigu.tool.minio_client_tool import *


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    # 进程级 RPM 滑动窗口：跨请求共享，防止多用户并发时各自独立窗口叠加冲击 API 配额；
    # 复合操作（检查+修改）用锁保护，sleep 在锁外执行避免阻塞其他请求
    _rpm_dq = deque(maxlen=30)
    _rpm_lock = threading.Lock()

    # 进程级 TPM 滑动窗口：token 数不定无法用 maxlen 容量驱逐，deque 存 (时间戳, token数) 元组，
    # 每次遍历求和判断（复合操作必须加锁），等待在锁外 sleep 避免阻塞其他请求
    _tpm_dq = deque()
    _tpm_lock = threading.Lock()
    MAX_TPM = 200_000        # TPM 上限（Tokens Per Minute）
    TPM_WINDOW = 60          # TPM 滑动窗口（秒）

    def process(self, state: ImportGraphState):
        image_name_list, image_path_obj, md_content,md_path = NodeMDImg.read_image_obj(state)

        image_summary_with_context_list = self.image_summary_list(image_name_list, image_path_obj, md_content,md_path)

        md_content, new_md_path = self.get_minio_url(image_summary_with_context_list, md_content, md_path)

        return {'md_path': str(new_md_path), 'md_content': md_content}

    def get_minio_url(self, image_summary_with_context_list: list[Any], md_content: str | Any,
                      md_path) -> tuple[Path, str]:
        minio_client = get_client()
        upload_dir = MinIoConfig.minio_img_dir
        # 按文件 stem 隔离子目录：多用户并发上传时互不干扰，只清理当前文件自己的旧图
        file_prefix = f"{upload_dir}/{Path(md_path).stem}"

        delete_image_obj = minio_client.list_objects(bucket_name=MinIoConfig.minio_bucket_name, prefix=file_prefix,
                                                     recursive=True)
        delete_image_obj_list = [DeleteObject(i.object_name) for i in delete_image_obj]
        if delete_image_obj_list:
            errors = minio_client.remove_objects(bucket_name=MinIoConfig.minio_bucket_name,
                                                 delete_object_list=delete_image_obj_list)
            logger.info(f"删除文件数: {len(delete_image_obj_list)}")
            for error in errors:
                logger.error(error)

        image_summary_with_context_and_url_list = []
        for image_with_context in image_summary_with_context_list:
            object_name = f"{file_prefix}/{image_with_context['image_name']}"
            minio_client.fput_object(bucket_name=MinIoConfig.minio_bucket_name,
                                     object_name=object_name,
                                     file_path=image_with_context['image_path'])

            # 预签名 URL 最长只能 7 天（S3 协议上限，改 expires 也无法永久），
            # 过期后前端 img 加载 403 只剩链接文字；
            # bucket 已配置公共读（get_client 的 policy），改用直链永久有效
            url = f"http://{MinIoConfig.minio_endpoint}/{MinIoConfig.minio_bucket_name}/{quote(object_name)}"

            image_summary_with_context_and_url_list.append(
                {
                    **image_with_context,
                    'url': url
                }
            )

            logger.info(f'图片上传成功:{url}')

        for image_url_context in image_summary_with_context_and_url_list:
            patten = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_url_context['image_name']) + r"\)")
            md_content = patten.sub(f"![{image_url_context['summary']}]({image_url_context['url']})", md_content)
            new_md_path = Path(md_path).parent / str(Path(md_path).stem + '_new.md')
            with open(new_md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
        return md_content, new_md_path if image_summary_with_context_and_url_list else Path(md_path)

    @classmethod
    def image_summary_list(cls, image_name_list: list[str], image_path_obj: str, md_content,md_path):
        IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        MAX_CONTEXT_LENGTH = 250
        image_context_summary_list = []
        llm = init_chat_model(
            model=LLMConfig.vl_model,
            model_provider='openai',
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_base_url,
            temperature=LLMConfig.llm_default_temperature
        )
        # 【改动1】dq 提到外层 for 外部，避免每次重建导致滑动窗口失效（升级为类属性进程级共享）
        # 【改动1.1】多用户并发：窗口与锁为类属性，跨请求共享限速配额
        for image_name in image_name_list:
            # 【改动7】每轮循环更新 current_time，否则窗口判断永远用的是初始值
            current_time = time.time()
            if Path(image_name).suffix.lower() not in IMAGE_EXTENSIONS:
                logger.warning(f'图片格式错误:{image_name}')
                continue

            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")
            match = pattern.search(md_content)
            # logger.info(f'图片匹配结果:{match}')
            if not match:
                logger.warning(f'图片未引用:{image_name}')
                continue
            start, end = match.span()
            pre_text = md_content[max(0, start - MAX_CONTEXT_LENGTH):start]
            post_text = md_content[end:min(len(md_content), end + MAX_CONTEXT_LENGTH)]

            # 【改动2】去掉内层 for image_context in image_context_list，每张图只调一次 LLM
            # 【改动3】滑动窗口限速逻辑直接处理当前图片，不再遍历历史列表
            # 先清理过期请求
            with cls._rpm_lock:
                while cls._rpm_dq and current_time - cls._rpm_dq[0] > 60:
                    cls._rpm_dq.popleft()
                if cls._rpm_dq and len(cls._rpm_dq) == cls._rpm_dq.maxlen:
                    need_wait_time = 60 - (current_time - cls._rpm_dq[0])
                else:
                    need_wait_time = 0
            if need_wait_time > 0:
                logger.error(f'图片处理超时,等待时间:{need_wait_time}')
                time.sleep(need_wait_time)
                current_time = time.time()
                with cls._rpm_lock:
                    while cls._rpm_dq and current_time - cls._rpm_dq[0] > 60:
                        cls._rpm_dq.popleft()
            with cls._rpm_lock:
                cls._rpm_dq.append(current_time)

            # TPM 限速：锁内清理过期 + 遍历求和判断，超限则锁外 sleep 等待最早一条过期
            with cls._tpm_lock:
                now = time.time()
                while cls._tpm_dq and now - cls._tpm_dq[0][0] > cls.TPM_WINDOW:
                    cls._tpm_dq.popleft()
                tpm_used = sum(t[1] for t in cls._tpm_dq)
                if tpm_used >= cls.MAX_TPM and cls._tpm_dq:
                    wait_time = cls.TPM_WINDOW - (now - cls._tpm_dq[0][0]) + 0.1
                else:
                    wait_time = 0
            if wait_time > 0:
                logger.warning(f'TPM超限(已用{tpm_used}/{cls.MAX_TPM}),等待{wait_time:.1f}s')
                time.sleep(wait_time)
                with cls._tpm_lock:
                    now = time.time()
                    while cls._tpm_dq and now - cls._tpm_dq[0][0] > cls.TPM_WINDOW:
                        cls._tpm_dq.popleft()

            # 【改动5】直接处理当前图片，使用 pre_text/post_text 而非 image_context.get()
            image_path = str(image_path_obj / image_name)
            with open(image_path, 'rb') as f:
                image_data = f.read()
                base64_image_data = base64.b64encode(image_data).decode('utf-8')
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image_data}"
                            },
                        },
                        {"type": "text",
                         "text": f"请根据图片的上文{pre_text},图片的后文{post_text}，给出图片的摘要，请使用中文,30字以内。"},
                    ],
                },
            ]
            res = llm.invoke(messages)
            # TPM 消耗记录：从返回元数据取 token 数，回记进程级窗口（跨请求共享配额）
            usage = getattr(res, 'usage_metadata', {})
            total_tokens = usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
            if not total_tokens:
                resp_usage = getattr(res, 'response_metadata', {}).get('token_usage', {})
                total_tokens = resp_usage.get('total_tokens', 0)
            with cls._tpm_lock:
                cls._tpm_dq.append((time.time(), total_tokens))
            image_context_summary_list.append({'image_name': image_name,
                                               'image_path': image_path,
                                               'summary': res.content
                                               })
        # 【改动6】logger 移到外层 for 外部，只打一次
        logger.info(f'图片处理结果:{json_format(image_context_summary_list)}')
        return image_context_summary_list

    @classmethod
    def read_image_obj(cls, state: ImportGraphState) -> tuple[list[str], str, Path]:
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
                logger.warning('文件内容为空')

            # 优先：MinerU 产出的标准 images/ 目录
            image_path_obj = md_path_obj.parent / 'images'
            if image_path_obj.exists():
                image_name_list = os.listdir(image_path_obj)
                if image_name_list:
                    logger.info(f'图片目录下文件数量:{len(image_name_list)}')
                    return image_name_list, image_path_obj, md_content, md_path
                logger.warning('图片目录下图片不存在，按无图片文档继续处理')
                return [], image_path_obj, md_content, md_path

            # 备选：用户直接上传的 MD，从内容中扫描本地图片引用
            image_refs = re.findall(r'!\[.*?\]\(([^)]+)\)', md_content)
            local_images = []
            local_dir = md_path_obj.parent
            for ref in image_refs:
                # 跳过远程 URL
                if ref.startswith('http://') or ref.startswith('https://'):
                    continue
                candidate = local_dir / ref
                if candidate.exists() and candidate.is_file():
                    local_images.append(str(candidate.relative_to(local_dir)))
            if local_images:
                logger.info(f'从 MD 内容扫描到 {len(local_images)} 张本地图片')
                return local_images, local_dir, md_content, md_path

            logger.warning('未找到任何图片（images/ 目录不存在，MD 内容中也无本地图片引用），按无图片文档继续处理')
            return [], image_path_obj, md_content, md_path


if __name__ == '__main__':
    node = NodeMDImg()
    init_state = {
        'md_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册.md'
    }
    res = node(init_state)
    logger.info(json_format(res))