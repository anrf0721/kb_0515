"""
author: anrf
date:8/18/2026
desc:
"""
import asyncio
import json
import queue
import time
import uuid
from typing import Annotated
from fastapi.responses import StreamingResponse

import uvicorn
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Path, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from atguigu.config.config import MinIoConfig
from atguigu.import_process.main_graph import MainGraphRunner
from atguigu.query_process.main_graph import QueryMainGraphRunner
from atguigu.tool.logger import logger
from atguigu.tool.minio_client_tool import get_client
from atguigu.tool.task_utils import add_running_task, add_done_task, get_task_info, update_task_status, \
    TASK_STATUS_PROCESSING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED, cleanup_expired_tasks, \
    register_emit, unregister_emit
from atguigu.tool.mongo_client_tool import get_chat_history_list, clear_history

app = FastAPI(
    title='掌柜智库查询接口服务',
    description='查询各个接口 api 服务',
    version='0.0.1'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get('/health')
async def health():
    return {'status': 'ok'}

@app.get('/history/{session_id}')
async def get_history_list(session_id: Annotated[str, Path(..., description='会话ID')]):
    # ObjectId 无法被 JSON 序列化，转成 str 后返回
    items = []
    for doc in get_chat_history_list(session_id):
        doc['_id'] = str(doc['_id'])
        items.append(doc)
    return {'items': items}


@app.delete('/history/{session_id}')
async def delete_history_list(session_id: Annotated[str, Path(..., description='会话ID')]):
    clear_history(session_id)
    return {'message': '删除成功'}


queue_dict = {}
def exec_query_graph(task_id: str, session_id: str, original_query: str):
    q = queue_dict.get(task_id)  # queue.Queue 是线程安全的，直接取值

    def emit(event: str, data: dict):
        # queue.Queue.put() 是同步方法，线程安全，不需要 run_coroutine_threadsafe
        if q:
            q.put({'event': event, 'data': data})

    try:
        cleanup_expired_tasks()
        register_emit(task_id, emit)  # 注册到 task_utils（跨模块共享），供节点发送 progress/delta

        init_state = {
            'task_id': task_id,
            'session_id': session_id,
            'original_query': original_query,
        }

        update_task_status(task_id, TASK_STATUS_PROCESSING)
        emit('progress', get_task_info(task_id))
        result = QueryMainGraphRunner.create_and_run(init_state)   # 同步调用，不要 await
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        emit('final', {
            **get_task_info(task_id),
            'answer': result.get('answer', ''),
            'image_urls': result.get('image_urls', []),
        })
    except Exception as e:
        logger.error(f"任务执行出错: {e}")
        update_task_status(task_id, TASK_STATUS_FAILED)
        emit('error', {'error': str(e)})
    finally:
        unregister_emit(task_id)  # 清理回调，避免内存泄漏
        queue_dict.pop(task_id, None)

class QueryParams(BaseModel):
    query: str = Field(...,description='查询问题')
    session_id: str = Field(..., description='会话ID')


@app.post('/query')
async def query(background_task: BackgroundTasks, query_params: Annotated[QueryParams, Body(..., description='查询参数')]):
    # # 生成task_id
    task_id = str(uuid.uuid4())
    queue_dict[task_id] = queue.Queue()  # 预建队列（线程安全），无需 loop 引用
    # # 调用后台任务,执行查询graph
    background_task.add_task(exec_query_graph, task_id, query_params.session_id, query_params.query)
    # # 返回响应(task_id)
    return {
        'task_id': task_id,
            'session_id': query_params.session_id,
            'query': query_params.query,
            }

async def get_stream_info(task_id):
    while task_id not in queue_dict:
        await asyncio.sleep(0.1)
    q = queue_dict[task_id]
    loop = asyncio.get_running_loop()
    while True:
        # queue.Queue.get() 是阻塞方法，用 run_in_executor 在线程池执行，不阻塞事件循环
        item = await loop.run_in_executor(None, q.get)
        yield f'event: {item["event"]}\n'
        yield f'data: {json.dumps(item["data"], ensure_ascii=False)}\n\n'
        if item['event'] in ('final', 'error'):
            break

@app.get('/stream/{task_id}')
async def stream(task_id: Annotated[str, Path(..., description='任务ID')]):
    return StreamingResponse(
        get_stream_info(task_id),
        media_type = 'text/event-stream'
    )


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8001)