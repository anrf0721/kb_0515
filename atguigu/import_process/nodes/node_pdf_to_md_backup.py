"""
author: anrf
date:7/31/2026
desc:
"""
import time
import zipfile
from pathlib import Path

from envs.condaproject.Lib import shutil

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

    def process(self, state: ImportGraphState):
        pdf_path = state.get('pdf_path')
        if not pdf_path:
            logger.error('路径没有提供')
            raise Exception('路径没有提供')

        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            logger.error('文件不存在')
            raise Exception('文件不存在')

        # 校验输出目录是否存在
        local_dir = state.get('local_dir','')
        if not local_dir:
            logger.error('输出目录没有提供')
            raise Exception('输出目录没有提供')

        local_dir_obj = Path(local_dir)
        if not local_dir_obj.exists() :
            local_dir_obj.mkdir(parents=True,exist_ok=True)


        # 上传pdf到mineru
        import requests

        token = MineruConfig.mineru_token
        url = f'{MineruConfig.mineru_base_url}/file-urls/batch'
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        data = {
            "files": [
                {"name": f"{pdf_path_obj.name}", "data_id": "abcd"}
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
        logger.info(f"上传文件请求成功,结果:{response}")
        result = response.json()
        if result["code"] != 0:
            logger.error(f"上传文件数据返回失败,错误信息:{result['msg']}")
            raise Exception(f"上传文件数据返回失败,错误信息:{result['msg']}")
        logger.info(f"上传文件数据返回成功,结果:{result}")


        batch_id = result["data"]["batch_id"]
        urls = result["data"]["file_urls"]
        print(batch_id,urls)

        for i in range(0, len(urls)):
            with open(file_path[i], 'rb') as f:
                res_upload = requests.put(urls[i], data=f)
                if res_upload.status_code == 200:
                    logger.info(f"{urls[i]} 上传成功")
                else:
                    logger.error(f"{urls[i]} 上传失败,错误信息:{res_upload.text}")
        total_time = 300
        sum_time = 0

        token = token
        batch_id = batch_id
        url = f"{MineruConfig.mineru_base_url}/extract-results/batch/{batch_id}"
        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # 读取zip文件
        while True:

            start_time = time.time()
            try:
                res = requests.get(url, headers=header)
                if res.status_code != 200:
                    logger.error(f"请求失败,状态码:{res.status_code},错误信息:{res.text}")
                    raise Exception(f"请求失败,状态码:{res.status_code},错误信息:{res.text}")
                result = res.json()
                logger.info(f"请求数据返回成功,结果:{result}")
                if result.get("code",1):
                    logger.error(f"请求数据返回失败,错误信息:{result['msg']}")
                    raise Exception(f"请求数据返回失败,错误信息:{result['msg']}")
                data = result.get("data",{}).get('extract_result',[])[0]
                logger.info(f'获取文件处理结果:{data}')
                if data.get('state') != 'done':
                    logger.info('PDF文件处理中')
                    time.sleep(5)
                    continue
                zip_url = data.get('full_zip_url','')
                print(f'获取zip文件地址:',zip_url)
                break


            except Exception as e:
                logger.error(f'文件处理失败:{e}')
                end_time = time.time()
                sum_time += end_time - start_time
                if sum_time > total_time:
                    logger.error('PDF文件处理超时')
                    raise Exception('PDF文件处理超时')
                continue


        # 下载zip文件
        import requests
        md_zip = requests.get(zip_url)
        if md_zip.status_code != 200:
            logger.error(f"请求失败,状态码:{md_zip.status_code},错误信息:{md_zip.text}")
            raise Exception(f"请求失败,状态码:{md_zip.status_code},错误信息:{md_zip.text}")
        mp_zip_file = md_zip.content

        # 构造磁盘路径
        mp_zip_file_obj = local_dir_obj/f'{pdf_path_obj.stem}.zip'
        # 读写wb二进制文件不能加encoding参数
        with open(mp_zip_file_obj,'wb') as f:
            f.write(mp_zip_file)

        # 解压zip文件

        unzip_file_path = local_dir_obj / f'{pdf_path_obj.stem}'
        shutil.rmtree(unzip_file_path, ignore_errors=True)
        if not unzip_file_path.exists():
            unzip_file_path.mkdir(parents=True,exist_ok=True)
        unzip_file = zipfile.ZipFile(mp_zip_file_obj)
        unzip_file.extractall(unzip_file_path)
        # 改名,文件叫full.md
        origin_md_path = unzip_file_path / 'full.md'
        new_md_path = origin_md_path.with_name(f'{pdf_path_obj.stem}.md')
        origin_md_path.rename(new_md_path)
        # 存储到state
        with open(new_md_path,'r',encoding='utf-8') as f:
            md_content = f.read()


        return {'md_path':str(new_md_path),'md_content' : md_content}

if __name__ == '__main__':
    node = NodePDFToMD()
    init_state = {
        'pdf_path': r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册.pdf',
        'local_dir' : r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc'

                  }
    res = node(init_state)
    # print(res)
    logger.info(json_format(res))
