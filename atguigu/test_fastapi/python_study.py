"""
author: anrf
date:8/19/2026
desc:
"""
x = "abc"
y = "def"
c = x + y          # 运行时才拼,内容编译期不知道
d = "abcdef"
print(c is d)      # False —— 这才是真的不保证驻留
