"""
author: anrf
date:8/1/2026
desc:
"""
import os

from dotenv import load_dotenv

load_dotenv()

class MineruConfig :
    """
    Mineru配置类
    """
    mineru_token = os.getenv('MINERU_TOKEN')
    mineru_base_url = os.getenv('MINERU_BASE_URL')

