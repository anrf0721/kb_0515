"""
author: anrf
date:8/3/2026
desc:
"""
# 滑动窗口算法示例
# import time
# from collections import deque
#
# list = [i for i in range(10)]
# dq = deque(maxlen=5)
# current_time = time.time()
# for i in list:
#     # 先清理过期请求
#     while dq and current_time - dq[0] > 3:
#         dq.popleft()
#     if dq and len(dq) == dq.maxlen:
#         need_wait_time = 3 - (current_time - dq[0])
#         if need_wait_time > 0:
#             time.sleep(need_wait_time)
#             current_time = time.time()
#             while dq and current_time - dq[0] > 3:
#                 dq.popleft()
#     dq.append(current_time)
#     print(i,dq)



# 指数退避重试示例（本地模拟，不需要联网）

# import time
#
# max_retries = 5
#
# class MockResponse:
#     """模拟 API 返回：奇数正常，偶数 429"""
#     def __init__(self, i):
#         self.status_code = 200 if i % 2 != 0 else 429
#
#     def json(self):
#         return {"result": "ok"}
#
#
# for i in range(10):
#     for attempt in range(max_retries):
#         resp = MockResponse(i)               # 模拟发请求
#
#         if resp.status_code == 200:
#             print(f"第{i}个成功, 状态码: {resp.status_code}")
#             break
#
#         if resp.status_code == 429:
#             wait = 2 ** attempt               # 1, 2, 4, 8, 16 秒
#             print(f"429 限流, 第{attempt+1}次重试, 等{wait}s")
#             time.sleep(wait)
#             continue
#     else:
#         print(f"第{i}个请求失败，已重试{max_retries}次，跳过")

# 异步

import asyncio
import time

MAX_CONCURRENT = 5


async def fetch_one(sem, i):
    async with sem:
        t0 = time.perf_counter()
        await asyncio.sleep(0.5)               # 模拟 0.5s IO
        elapsed = time.perf_counter() - t0
        print(f"第{i}个完成, 耗时: {elapsed:.2f}s")
        return i


async def main():
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    start = time.perf_counter()

    tasks = [fetch_one(sem, i) for i in range(20)]
    await asyncio.gather(*tasks)

    total = time.perf_counter() - start
    print(f"\n总耗时: {total:.2f}s (理论: {20 / MAX_CONCURRENT * 0.5:.1f}s)")


asyncio.run(main())
