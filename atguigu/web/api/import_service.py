"""
author: anrf
date:8/17/2026
desc:
"""
from datetime import datetime as dt, timedelta
import uuid
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from atguigu.config.config import MinIoConfig
from atguigu.import_process.main_graph import MainGraphRunner
from atguigu.tool.logger import logger
from atguigu.tool.minio_client_tool import get_client
from atguigu.tool.task_utils import add_running_task, add_done_task, get_task_info, update_task_status, \
    TASK_STATUS_PROCESSING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED, cleanup_expired_tasks

app = FastAPI(
    title='掌柜智库导入接口服务',
    description='导入各个接口api服务',
    version='0.0.1'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def exec_graph(task_id: str, local_dir: str,local_file_path:str):
    try:
        init_state = {
            'task_id': task_id,
            'local_dir': local_dir,
            'local_file_path': local_file_path
        }
        update_task_status(task_id,TASK_STATUS_PROCESSING)
        MainGraphRunner.create_and_run(init_state)   # 同步调用，不要 await：create_and_run 是 def 不是 async def
        update_task_status(task_id, TASK_STATUS_COMPLETED)
    except Exception as e:
        logger.error(f"任务执行出错: {e}")
        update_task_status(task_id, TASK_STATUS_FAILED)


@app.post('/upload')
async def upload_file(background_task : BackgroundTasks,file:Annotated[UploadFile,File(...,description='开始上传文件')]):
    # 顺手清理超过 TTL 的已终态任务，防止内存只增不减
    cleanup_expired_tasks()

    # 生成task_id
    task_id = str(uuid.uuid4())
    # 上传文件的状态追踪
    add_running_task(task_id,'upload_file')

    # 接受文件并保存
    time_prefix = dt.now().strftime("%Y%m%d%H%M%S")  # 只取一次时间戳，本地目录和 MinIO 路径共用，保证一致

    local_dir = Path(__file__).parent.parent/'data'/time_prefix
    local_dir_obj = Path(local_dir)
    if not local_dir_obj.exists():
        local_dir_obj.mkdir(parents=True, exist_ok=True)
        logger.info(f'创建目录成功: {local_dir}')
    local_file_path = str(local_dir_obj / file.filename)
    with open(local_file_path, 'wb') as f:
        while chunk:= await file.read(1024*1024):
            f.write(chunk)
    logger.info(f'保存文件成功: {local_file_path}')


    # 备份文件到minio
    minio_client = get_client()
    object_name = f'upload_file/{time_prefix}/{task_id}/{file.filename}'
    minio_client.fput_object(
        bucket_name=MinIoConfig.minio_bucket_name,
        object_name=object_name,
        file_path=local_file_path
    )
    file_url = minio_client.presigned_get_object(
        bucket_name=MinIoConfig.minio_bucket_name,
        object_name=object_name,
        expires=timedelta(days=7)  # 链接有效期
    )
    logger.info(f'文件上传路径: {file_url}')
    add_done_task(task_id, 'upload_file')


    # 调用后台任务,执行graph
    background_task.add_task(exec_graph, task_id, local_dir, local_file_path)

    # 返回响应(task_id)
    return {"task_id": task_id, 'file_size': file.size, 'file_name': file.filename, 'file_url': file_url}

@app.get('/status/{task_id}')
async def get_task_status(task_id: str):
    return get_task_info(task_id)

if __name__ == '__main__':
    uvicorn.run('import_service:app', host='0.0.0.0', port=8000)
