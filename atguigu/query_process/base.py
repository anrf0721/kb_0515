"""
author: anrf
date:7/31/2026
desc:
"""
from abc import ABC, abstractmethod

from atguigu.import_process.state import *
from atguigu.tool.logger import *


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
            logger.info(f'{self.name} 开始执行')
            result = self.process(state)

            logger.info(f'{self.name} 执行完毕')
            return  result
        except Exception as e:
            logger.error(f'{self.name} 执行异常: {e}')
            raise e

