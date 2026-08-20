"""
author: anrf
date:7/31/2026
desc:
"""
import time
from abc import abstractmethod, ABC

from atguigu.query_process.state import QueryGraphState
from atguigu.tool.logger import logger
from atguigu.tool.task_utils import add_running_task, add_done_task, add_node_duration,get_emit, get_task_info

class NodeBase(ABC):

    name: str = "node_base"

    def __init__(self):
        """
        强制子类设置name
        """
        if self.name == "node_base":
            raise ValueError(f"{self.__class__.__name__} 必须设置 name 属性")

    def __call__(self, state: QueryGraphState):
        """
        节点执行入口
        """
        try:
            task_id = state.get("task_id")
            logger.info(f"{self.name} 开始执行...")
            add_running_task(task_id,self.name)

            # 从 task_utils 取 emit 回调（不能从 query_service 导入：它以 __main__ 启动，模块实例不同，拿到的是空字典）

            emit = get_emit(task_id)
            if emit:
                emit('progress', get_task_info(task_id))  # 节点开始：前端 progress 更新 running_list

            start_time = time.time()
            result = self.process(state)

            logger.info(f"{self.name} 结束执行...")
            add_done_task(task_id,self.name)
            duration = time.time() - start_time
            add_node_duration(task_id, self.name, duration)
            if emit:
                emit('progress', get_task_info(task_id))  # 节点结束：前端 progress 更新 done_list
            return result
        except Exception as e:
            logger.error(f"{self.name} 执行失败: {e}")
            raise

    @abstractmethod
    def process(self, state: QueryGraphState):
        """
        节点的核心处理逻辑
        :return:
        """
        pass
