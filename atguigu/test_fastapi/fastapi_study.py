"""
author: anrf
date:8/15/2026
desc:
"""
import shutil
import time
import uuid
import pathlib
import asyncio
from asyncio import Queue
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from typing import Annotated, List
from fastapi import FastAPI, Path, Query, Depends, File, UploadFile, BackgroundTasks, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from atguigu.tool.logger import *

# 上传文件统一存放目录，每次启动前自动清空
UPLOAD_DIR = pathlib.Path(__file__).parent / 'uploads'

app = FastAPI(
    title="测试功能",
    description="0815",
    version="0.1.0",
)

@app.get('/')
def read_root():
    return {"Hello": "World"}

@app.get('/testpath/{id}/{name}/{age}')
def testpath(id: Annotated[int, Path()],
             name: Annotated[str, Path(description='名称')],
             age: Annotated[int, Path(description='年龄', ge=18, le=60)]):
    return {"id": id, "name": name, "age": age}

@app.get('/testpath')
def testquery(id: int,
              gender: Annotated[str, Query(description='性别')],
              height: Annotated[float, Query()] = 100.2):
    return {'id': id, 'height': height, 'gender': gender}

class User(BaseModel):
    id: int
    name: str
    age: int

class Student:
    def __init__(self,id:int,name:str,age:int):
        self.id = id
        self.name = name
        self.age = age
def get_student() -> Student:
    """依赖函数：FastAPI 调用它来创建 Student 实例"""
    return Student(id=1, name='张三', age=20)

@app.post('/testbody')
def testbody(user: User, student: Annotated[Student, Depends(get_student)]):
    print(user, type(user))
    print(student, type(student))
    return JSONResponse(
        content={
            "user": {"id": user.id, "name": user.name, "age": user.age},
            "student": {"id": student.id, "name": student.name, "age": student.age},
        },
        status_code=201,
        headers={"X-Custom": "custom-headerrrrr"},  # 响应头只能用 ASCII，不能写中文
    )

@app.post('/uploadfile')
async def upload(files: Annotated[List[UploadFile], File(description='上传文件')]):
    result = []
    for file in files:
        print(file.__dict__)
        file_name = str(uuid.uuid4())[:9] + file.filename
        UPLOAD_DIR.mkdir(exist_ok=True)  # 确保目录存在
        with open(UPLOAD_DIR / file_name, 'wb') as f:
            while chunk := await file.read():
                f.write(chunk)
        result.append({
            "filename": file_name,
            "content_type": file.content_type,
            "size": file.size,
        })
    return result

app.mount('/static', StaticFiles(directory=str(pathlib.Path(__file__).parent / 'static')), name='static')
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],      # 允许哪些源（'*' = 全部）
    allow_methods=['*'],      # 允许哪些 HTTP 方法
    allow_headers=['*'],      # 允许哪些请求头
    allow_credentials=True,
)
def test_task(n):
    print('开始累加')
    while n > 0:
        n -= 1
        time.sleep(1)
        print(n)
    print('执行结束')
@app.get('/test_back_ground')
def test_back_ground(task: BackgroundTasks):
    task.add_task(test_task, 10)
    return {"message": "你好!!"}

queue_dict = {}
async def make_email(session_id:str):
    global queue_dict
    if not queue_dict.get(session_id):
        queue_dict[session_id] = Queue()
    q = queue_dict[session_id]
    # asyncio.Queue 的 put 是协程方法，不 await 消息不会真正入队；用 put_nowait 同步入队
    await q.put('邮件1发送')
    await asyncio.sleep(1)     # 每封邮件间隔 1 秒发送，制造流式节奏
    await q.put('邮件2发送')
    await asyncio.sleep(1)
    await q.put('邮件3发送')

@app.get('/sse01')
async def sse01(background_tasks:BackgroundTasks,session_id : Annotated[str, Query(description='会话ID')]):
    background_tasks.add_task(make_email, session_id)  # 把接口收到的 session_id 传给后台任务
    return JSONResponse(
        content={
            "message": "你好!!现在开始发送邮件",
            "session_id": session_id
        },
        status_code=200,
        headers={"X-Custom": "custom-header"},
    )

async def email_generator(session_id: str):
    q = queue_dict.get(session_id)
    if not q:
        q = queue_dict[session_id] = Queue()   # 链式赋值：字典和 q 同时拿到新队列
    while True:
        msg = await q.get()
        yield f'data: {msg}\n\n'

@app.get('/stream')
async def get_stream(session_id : Annotated[str, Query(description='会话ID')]):
    return StreamingResponse(
        email_generator(session_id),
        media_type='text/event-stream'
    )

class BodyParms(BaseModel):
    query: str = Field(..., description='查询内容')
    session_id: str = Field(..., description='会话ID')   # 与 /sse01、/stream 保持一致用 str


queue_dict2 = {}
async def make_answer(query, session_id):
    global queue_dict2
    if session_id not in queue_dict2:
        queue_dict2[session_id] = Queue()
    q = queue_dict2[session_id]
    await q.put({'event' : 'message', 'data': f'问题: {query}'})
    await q.put({'event' : 'message', 'data': '哈哈1'})
    await q.put({'event' : 'message', 'data': '哈哈2'})
    await q.put({'event' : 'final', 'data': '结束'})


@app.post('/sse02')
async def sse02(background_tasks:BackgroundTasks,body_params:Annotated[BodyParms, Body(description='请求参数')]):
    print(body_params.__dict__, type(body_params))
    # 不能用 *body_params：Pydantic 模型的 __iter__ 产出 (key, value) 元组对，不是值
    background_tasks.add_task(make_answer, body_params.query, body_params.session_id)
    return JSONResponse(content={"message": "开始查询信息造消息"}
                        ,status_code=200
                        ,headers={"xxx": "666"})


async def generate_answer(session_id):
    q = queue_dict2.get(session_id)
    if not q:
        q = queue_dict2[session_id] = Queue()
    while True:
        # q 是 Queue，不能下标取值；队列里存的是 {'event':..., 'data':...} 字典
        msg = await q.get()
        yield f'data: {msg["data"]}\n\n'
        if msg['event'] == 'final':
            break



class BodyParms(BaseModel):
    session_id: str = Field(..., description='会话ID')
    query: str = Field(..., description='查询内容')

queue_dict3 = {}
async def queue_answer(query, session_id):
    global queue_dict3
    import asyncio
    # 先建队列再取 q：之前先 get 拿到 None，后面 while not q 永远死循环
    await asyncio.sleep(0.2)  # 微调：延迟启动，让 consumer 先准备好
    if session_id not in queue_dict3:
        queue_dict3[session_id] = Queue()
    q = queue_dict3[session_id]
    await q.put({'event' : 'message','data' : f'{query}哈哈 1'})
    await q.put({'event' : 'message','data' : f'{query}哈哈 2'})
    await q.put({'event' : 'final','data' : '结束'})


@app.post('/sse03')
async def sse03(background_task:BackgroundTasks,body_params:Annotated[BodyParms, Body(description='请求参数')]):
    background_task.add_task(queue_answer, body_params.query, body_params.session_id)
    return JSONResponse(content = {'message' : '开始查询制造'}
                        ,status_code= 201
                        ,headers={'custom-header': 'x-custom'}
                        )

async def generate_answer_stream(session_id):
    # 消费端也可能先到：不存在就自己建队列，和生产端共享同一个
    if session_id not in queue_dict3:
        queue_dict3[session_id] = Queue()
    q = queue_dict3[session_id]
    while True:
        try:
            answer = await q.get()
            yield f'event: {answer["event"]}\n'
            yield f'data: {answer["data"]}\n\n'
            await asyncio.sleep(1)
            # a = 10/0  # 测试异常分支用；放开后每条消息都会抛错，final 分支永远走不到
            if answer["event"] == "final":
                break
        except Exception as e:
            yield f'event: error\n'
            yield f'data: {str(e)}\n\n'
            logger.info(f'异常了{e}')
            break


@app.get('/sse03/{session_id}')
async def get_sse03_session_info(session_id: str):
    return StreamingResponse(
        generate_answer_stream(session_id),
        media_type='text/event-stream'
    )



if __name__ == '__main__':
    if UPLOAD_DIR.exists():
        shutil.rmtree(UPLOAD_DIR)  # 每次启动前删除之前上传的文件
    UPLOAD_DIR.mkdir()
    # reload 模式必须传导入字符串，不能传 app 对象
    uvicorn.run('fastapi_study:app', host='0.0.0.0', port=8000, reload=True)