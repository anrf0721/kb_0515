"""
author: anrf
date:7/31/2026
desc:
"""
import json
import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_dumps_tool import json_format
from atguigu.tool.logger import logger


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：智能文档切片
    """

    name = "node_document_split"

    def process(self, state: ImportGraphState):
        md_path = state.get('md_path', '')
        if not md_path:
            logger.error('路径没有提供')
            raise Exception('路径没有提供')
        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error('文件不存在')
            raise Exception('文件不存在')

        file_title = state.get('file_title', '')
        if not file_title:
            logger.warning('文件标题没有提供,已置为文件默认名')
            file_title = md_path_obj.stem

        with open(md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()
        if not md_content:
            logger.error('文件内容为空')
            raise Exception('文件内容为空')

        # 粗切
        md_content = md_content.replace('\r\n','\n').replace('\r', '\n')
        md_split_list = md_content.split('\n')
        # logger.info(f'文档切分结果:{md_split_list}')
        code_pattern = re.compile(r'^(```|~~~)[\w\s]*$')
        title_pattern = re.compile(r'^#+[\w\s]*$')
        is_in_block = False
        current_idx = 0
        section_dict_list = []
        for idx,line in enumerate(md_split_list):
            line = line.strip()
            match = re.match(code_pattern, line)
            if match:
                if not is_in_block:
                    is_in_block = True
                    marker = match.group(1)
                    logger.info(f'开始代码块:{marker}')

                else:
                    if marker == match.group(1):
                        is_in_block = False
                        marker = None
                        logger.info(f'结束代码块:{marker}')
            if not is_in_block and re.match(title_pattern, line):
                temp_list = md_split_list[current_idx:idx]
                # logger.info(f'开始切分:{temp_list}')
                content = '\n'.join(temp_list[1:])
                # logger.info(f'切分结果:{content}')
                section_dict = {
                    'title' : temp_list[0] if temp_list[0].startswith('#') else '无标题',
                    'content' : content,
                    'file_title' : file_title
                }
                section_dict_list.append(section_dict)
                current_idx = idx
        section_dict_list.append({
            'title': md_split_list[current_idx],
            'content': '\n'.join(md_split_list[current_idx:]),
            'file_title': file_title
        })
        # logger.info(f'切分结果:{section_dict_list}')

        # 长切短和
        MAX_LENGTH = 300
        OVER_LAP = 30
        final_section_list = []
        spliter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " "],
            chunk_size=MAX_LENGTH,
            chunk_overlap=OVER_LAP,
        )
        for section_dict in section_dict_list:
            title = section_dict.get('title', '无标题')
            content = section_dict.get('content','')
            if len(content) < MAX_LENGTH :
                final_section_list.append(
                    {**section_dict,
                     'part' : 0
                     }
                )
                logger.info(f'段落长度小于{MAX_LENGTH},跳过:{title}')
                continue
            if  '<table>' in content:


                final_section_list.append(
                    {
                    **section_dict,
                     'part': 0
                     }
                )
                logger.info(f'遇到表格,跳过:{title}')
                continue
            else :
                logger.info(f'段落长度大于{MAX_LENGTH},开始切分:{title}')

            spliter_chunk_list = spliter.split_text(content)
            for idx, chunk in enumerate(spliter_chunk_list):
                final_section_list.append(
                    {
                    'title' : title,
                    'content' :title + '\n\n' + chunk,
                    'file_title' : file_title,
                     'part': idx,
                    }
                )
        # logger.info(f'切分结果:{json_format(final_section_list)}')
        return {'file_title':file_title,'chunks' : final_section_list}
if __name__ == '__main__':
    node = NodeDocumentSplit()
    md_path=r'E:\尚硅谷\12_掌柜智库\11、掌柜智库01\资料\05-设备手册汇总\doc\hak180产品安全手册\hak180产品安全手册_new.md'
    init_state = {
        'md_path':md_path,
        # "file_title": "hak180产品安全手册"
    }
    res = node(init_state)
    logger.info(json_format(res))
    output_path = Path(__file__).parent.parent.parent / 'data' / 'chunks.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(res['chunks'], f, ensure_ascii=False, indent=2)
    logger.info(f'chunks.json 已生成，路径：{output_path}')
    logger.info(f'切片总数：{len(res["chunks"])}')