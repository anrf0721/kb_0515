"""
author: anrf
date:7/31/2026
desc:
"""
from pathlib import Path

from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_dumps_tool import *
from atguigu.tool.logger import *


class NodeEntry(NodeBase):
    """
    入口节点：任务分发
    """

    name = "node_entry"

    def process(self, state: ImportGraphState):
        # 防御性编程
        local_file_path = state.get('local_file_path','')
        if not local_file_path:
            logger.error('路径没有提供')
            raise Exception('路径没有提供')

        local_file_path_obj = Path(local_file_path)
        if not local_file_path_obj.exists():
            logger.error('文件不存在')
            raise Exception('文件不存在')


        logger.info(f'{local_file_path_obj}开始进行入口处理')
        file_title = local_file_path_obj.stem
        file_name = local_file_path_obj.name
        suffix = local_file_path_obj.suffix

        if suffix.lower() == '.md':
            return {'file_title':file_title,
                    'md_path' : str(local_file_path_obj),
                    'is_md_read_enabled' : True
                    }
        elif suffix.lower() == '.pdf':
            return {'file_title':file_title,
                    'pdf_path' : str(local_file_path_obj),
                    'is_pdf_read_enabled' : True
                    }
        else:
            logger.error('不支持的文件格式')
            raise Exception('不支持的文件格式')


if __name__ == '__main__':
    node = NodeEntry()
    init_state = {'local_file_path':r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册.pdf'}
    result = node(init_state)
    logger.info(json_format(result))