"""
author: anrf
date:7/31/2026
desc:
"""
from atguigu.import_process.base import *
from atguigu.import_process.state import *
from atguigu.tool.logger import *


class NodeTest(NodeBase):

    def process(self,state:ImportGraphState):
        logger.info(f'{self.name} 测试')
        return state

if __name__ == '__main__':
    node = NodeTest('my_test')
    init_state = {}
    print(node(init_state))
