"""
author: anrf
date:8/1/2026
desc:
"""
import json

def json_format(data):
    return json.dumps(data, indent=4, ensure_ascii=False)