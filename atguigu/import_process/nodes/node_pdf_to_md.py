"""
author: anrf
date:7/31/2026
desc:
优化记录 (2026-08-03)：
  ① upload_pdf: PUT 上传失败加 raise，不再静默跳过
  ② pdf_2_md:    超时改用墙钟判断，修复 sum_time 只在 except 累加的 bug
  ③ upload_pdf:   data_id 从死值 "abcd" 改为 uuid，避免状态污染
  ④ download_zip: 加重试 机制 + timeout=60 指数退避重试策略
  ⑤ upload_pdf:   去掉无意义的 requests 返回值
  ⑥ 全局:         print 统一改为 logger
  ⑦ 全局:         import shutil 从标准库导入
"""
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import requests

from atguigu.config.config import MineruConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_dumps_tool import *
from atguigu.tool.logger import *


class NodePDFToMD(NodeBase):
    """
    PDF 转 Markdown 节点：PDF结构化解析
    """

    name = "node_pdf_to_md"

    def extract_zip(self, local_dir_obj: Path, mp_zip_file_obj: Path, pdf_path_obj: Path) -> tuple[Path, str]:
        unzip_file_path = local_dir_obj / f'{pdf_path_obj.stem}'
        shutil.rmtree(unzip_file_path, ignore_errors=True)
        if not unzip_file_path.exists():
            unzip_file_path.mkdir(parents=True, exist_ok=True)
        unzip_file = zipfile.ZipFile(mp_zip_file_obj)
        unzip_file.extractall(unzip_file_path)
        # 改名,文件叫full.md
        origin_md_path = unzip_file_path / 'full.md'
        new_md_path = origin_md_path.with_name(f'{pdf_path_obj.stem}.md')
        origin_md_path.rename(new_md_path)
        # 存储到state
        with open(new_md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        logger.info(f'保存md文件成功,保存路径:{new_md_path}')
        return md_content, new_md_path

    def download_zip(self, local_dir_obj: Path, pdf_path_obj: Path, zip_url) -> Path:
        # 【改动4】加重试 10 次 + timeout=60，防止 SSL EOF / 网络抖动
        max_retries = 10
        for attempt in range(max_retries):
            try:
                md_zip = requests.get(zip_url, timeout=60)
                if md_zip.status_code == 200:
                    break
            except requests.exceptions.RequestException as e:
                logger.warning(f'下载zip失败,第{attempt+1}次重试,错误:{e}')
                if attempt == max_retries-1 :
                    raise Exception(f"请求失败,状态码:{md_zip.status_code},错误信息:{md_zip.text}")
                time.sleep(2 ** attempt)

        if md_zip.status_code != 200:
            logger.error(f"请求失败,状态码:{md_zip.status_code},错误信息:{md_zip.text}")
            raise Exception(f"请求失败,状态码:{md_zip.status_code},错误信息:{md_zip.text}")
        mp_zip_file = md_zip.content
        logger.info(f'下载zip文件成功,结果:{zip_url}')

        # 构造磁盘路径
        mp_zip_file_obj = local_dir_obj / f'{pdf_path_obj.stem}.zip'
        # 读写wb二进制文件不能加encoding参数
        with open(mp_zip_file_obj, 'wb') as f:
            f.write(mp_zip_file)
        logger.info(f'保存zip文件成功,保存路径:{mp_zip_file_obj}')
        return mp_zip_file_obj

    def pdf_2_md(self, batch_id: str | None, token) -> Any:
        # 【改动2】超时改用墙钟判断，不用 sum_time 只在 except 累加的写法
        total_time = 300
        t0 = time.time()

        url = f"{MineruConfig.mineru_base_url}/extract-results/batch/{batch_id}"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        while True:
            if time.time() - t0 > total_time:
                logger.error('PDF文件处理超时')
                raise Exception('PDF文件处理超时')

            try:
                res = requests.get(url, headers=header)
                if res.status_code != 200:
                    logger.error(f"请求失败,状态码:{res.status_code},错误信息:{res.text}")
                    raise Exception(f"请求失败,状态码:{res.status_code},错误信息:{res.text}")
                result = res.json()
                logger.info(f"请求数据返回成功,结果:{result}")
                if result.get("code", 1) != 0:
                    logger.error(f"请求数据返回失败,错误信息:{result['msg']}")
                    raise Exception(f"请求数据返回失败,错误信息:{result['msg']}")
                data = result.get("data", {}).get('extract_result', [])[0]
                logger.info(f'获取文件处理结果:{data}')
                if data.get('state') != 'done':
                    logger.info('PDF文件处理中')
                    time.sleep(5)
                    continue
                zip_url = data.get('full_zip_url', '')
                logger.info(f'获取zip文件地址:{zip_url}')
                break

            except Exception as e:
                logger.error(f'文件处理失败:{e}')
                time.sleep(5)
                continue
        return zip_url

    def upload_pdf(self, pdf_path: str, pdf_path_obj: Path) -> tuple[str | None, str]:
        token = MineruConfig.mineru_token
        url = f'{MineruConfig.mineru_base_url}/file-urls/batch'
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        # 【改动3】data_id 从死值 "abcd" 改为 uuid，避免状态污染
        data = {
            "files": [
                {"name": f"{pdf_path_obj.name}", "data_id": str(uuid.uuid4())}
            ],
            "model_version": "vlm"
        }
        file_path = [f'{pdf_path}']

        """
        但凡发请求,三次考虑
        1.请求是否成功
        2.数据是否成功
        3.数据是否是需要的
        """
        response = requests.post(url, headers=header, json=data)
        if response.status_code != 200:
            logger.error(f"上传文件请求失败,状态码:{response.status_code},错误信息:{response.text}")
            raise Exception(f"上传文件请求失败,状态码:{response.status_code},错误信息:{response.text}")
        result = response.json()
        if result.get("code", 1) != 0:
            logger.error(f"上传文件数据返回失败,错误信息:{result['msg']}")
            raise Exception(f"上传文件数据返回失败,错误信息:{result['msg']}")
        logger.info(f"上传文件请求成功,结果:{result}")

        batch_id = result["data"]["batch_id"]
        urls = result["data"]["file_urls"]
        logger.info(f'batch_id: {batch_id}, urls: {urls}')

        for i in range(0, len(urls)):
            with open(file_path[i], 'rb') as f:
                res_upload = requests.put(urls[i], data=f)
                if res_upload.status_code == 200:
                    logger.info(f"{urls[i]} 上传成功")
                else:
                    # 【改动1】PUT 上传失败必须 raise，否则 batch_id 永远没文件 → state 卡 waiting-file
                    logger.error(f"{urls[i]} 上传失败,错误信息:{res_upload.text}")
                    raise Exception(f"PUT 上传失败: {urls[i]}, 错误: {res_upload.text}")

        # 【改动5】不返回 requests 模块，只返回 batch_id 和 token
        return batch_id, token

    def check_pdf(self, state: ImportGraphState) -> tuple[Path, str, Path]:
        pdf_path = state.get('pdf_path')
        if not pdf_path:
            logger.error('路径没有提供')
            raise Exception('路径没有提供')

        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            logger.error('文件不存在')
            raise Exception('文件不存在')

        # 校验输出目录是否存在
        local_dir = state.get('local_dir', '')
        if not local_dir:
            logger.error('输出目录没有提供')
            raise Exception('输出目录没有提供')

        local_dir_obj = Path(local_dir)
        if not local_dir_obj.exists():
            local_dir_obj.mkdir(parents=True, exist_ok=True)
        return local_dir_obj, pdf_path, pdf_path_obj

    def process(self, state: ImportGraphState):
        local_dir_obj, pdf_path, pdf_path_obj = self.check_pdf(state)
        # 上传pdf到mineru
        batch_id, token = self.upload_pdf(pdf_path, pdf_path_obj)

        zip_url = self.pdf_2_md(batch_id, token)

        # 下载zip文件
        mp_zip_file_obj = self.download_zip(local_dir_obj, pdf_path_obj, zip_url)
        # 解压zip文件

        md_content, new_md_path = self.extract_zip(local_dir_obj, mp_zip_file_obj, pdf_path_obj)

        return {'md_path': str(new_md_path), 'md_content': md_content}


if __name__ == '__main__':
    node = NodePDFToMD()
    init_state = {
        'pdf_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册.pdf',
        'local_dir': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc'
    }
    res = node(init_state)
