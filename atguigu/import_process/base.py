"""
author: anrf
date:7/31/2026
desc:
"""
from abc import ABC, abstractmethod

from atguigu.import_process.state import *
from atguigu.tool.logger import *
from atguigu.tool.task_utils import *


class NodeBase(ABC):
    name : str = 'node_base'
    def __init__(self):
        if self.name == 'node_base':
            raise Exception('请设置节点名称')

    @abstractmethod
    def process(self,state:ImportGraphState):
        pass

    def __call__(self, state:ImportGraphState):
        try:
            task_id = state.get('task_id')
            logger.info(f'{self.name} 开始执行')
            add_running_task(task_id, self.name)
            start_time = time.time()
            result = self.process(state)
            add_done_task(task_id, self.name)
            logger.info(f'{self.name} 执行完毕')
            duration = time.time() - start_time
            add_node_duration(task_id, self.name,duration)
            return  result
        except Exception as e:
            # exc_info=True 输出完整堆栈，方便定位具体出错行号（仅 {e} 无法定位）
            logger.error(f'{self.name} 执行异常: {e}', exc_info=True)
            raise e

