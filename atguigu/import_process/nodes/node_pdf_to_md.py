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
from pypdf import PdfReader, PdfWriter

from atguigu.config.config import MineruConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_dumps_tool import *
from atguigu.tool.logger import *


class MineruFailedError(Exception):
    """MinerU 服务端明确返回 failed（如 retry limit reached）：重试无意义，直接失败穿透轮询"""
    pass


# 大 PDF 拆分页数阈值：整本书级 PDF（数百页）一次性提交 MinerU 云服务会解析失败
# （服务端重试 5 次后返回 retry limit reached），按此阈值拆分后逐份解析
SPLIT_PAGE_SIZE = 50


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
                extract_results = result.get("data", {}).get('extract_result', [])
                if not extract_results:
                    raise MineruFailedError('extract_result 为空，服务端未返回文件处理记录')
                data = extract_results[0]
                logger.info(f'获取文件处理结果:{data}')
                if data.get('state') == 'failed':
                    # 服务端已明确失败（如 retry limit reached），轮询永远等不到 done，直接失败
                    raise MineruFailedError(f"MinerU解析失败: {data.get('err_msg', '')}")
                if data.get('state') != 'done':
                    logger.info('PDF文件处理中')
                    time.sleep(5)
                    continue
                zip_url = data.get('full_zip_url', '')
                logger.info(f'获取zip文件地址:{zip_url}')
                break

            except MineruFailedError:
                # 致命失败直接向上抛，让任务状态变为失败，而不是无限轮询
                raise
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

    def _split_pdf(self, pdf_path_obj: Path, local_dir_obj: Path) -> list[Path]:
        """页数超过阈值时拆分为多份临时 PDF。返回待解析文件路径列表（未超阈值时只有原文件）。"""
        reader = PdfReader(str(pdf_path_obj))
        total_pages = len(reader.pages)
        if total_pages <= SPLIT_PAGE_SIZE:
            return [pdf_path_obj]
        split_paths = []
        for start in range(0, total_pages, SPLIT_PAGE_SIZE):
            writer = PdfWriter()
            for i in range(start, min(start + SPLIT_PAGE_SIZE, total_pages)):
                writer.add_page(reader.pages[i])
            part_path = local_dir_obj / f'{pdf_path_obj.stem}_part{len(split_paths) + 1}.pdf'
            with open(part_path, 'wb') as f:
                writer.write(f)
            split_paths.append(part_path)
        logger.info(f'PDF 共 {total_pages} 页，超过 {SPLIT_PAGE_SIZE} 页阈值，拆分为 {len(split_paths)} 份逐份解析')
        return split_paths

    def process(self, state: ImportGraphState):
        local_dir_obj, pdf_path, pdf_path_obj = self.check_pdf(state)

        # 大 PDF 拆分：整本数百页一次性提交 MinerU 会解析失败，拆成小份逐份解析后合并
        parse_paths = self._split_pdf(pdf_path_obj, local_dir_obj)

        if len(parse_paths) == 1:
            # 未超阈值：走原单文件流程
            batch_id, token = self.upload_pdf(pdf_path, pdf_path_obj)
            zip_url = self.pdf_2_md(batch_id, token)
            mp_zip_file_obj = self.download_zip(local_dir_obj, pdf_path_obj, zip_url)
            md_content, new_md_path = self.extract_zip(local_dir_obj, mp_zip_file_obj, pdf_path_obj)
            return {'md_path': str(new_md_path), 'md_content': md_content}

        # 拆分多份：逐份走 上传→解析→下载→解压，最后合并为一个 md
        md_contents = []
        for part_path_obj in parse_paths:
            batch_id, token = self.upload_pdf(str(part_path_obj), part_path_obj)
            zip_url = self.pdf_2_md(batch_id, token)
            part_zip_obj = self.download_zip(local_dir_obj, part_path_obj, zip_url)
            part_content, _ = self.extract_zip(local_dir_obj, part_zip_obj, part_path_obj)
            md_contents.append(part_content)
            logger.info(f'第 {len(md_contents)}/{len(parse_paths)} 份解析完成: {part_path_obj.name}')

        md_content = '\n\n'.join(md_contents)
        new_md_path = local_dir_obj / f'{pdf_path_obj.stem}.md'
        with open(new_md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        logger.info(f'拆分解析完成，合并 md 保存路径: {new_md_path}')
        # 清理拆分产生的临时 part PDF，保留合并后的 md
        for part_path_obj in parse_paths:
            part_path_obj.unlink(missing_ok=True)
        return {'md_path': str(new_md_path), 'md_content': md_content}


if __name__ == '__main__':
    node = NodePDFToMD()
    init_state = {
        'pdf_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册.pdf',
        'local_dir': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc'
    }
    res = node(init_state)
