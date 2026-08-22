def a(func):
    print(f"[装饰阶段] a 拿到 → {func.__name__}")
    def wrap_a():
        print("  [调用] 进入 a")
        func()
        print("  [调用] 离开 a")
    return wrap_a

def b(func):
    print(f"[装饰阶段] b 拿到 → {func.__name__}")
    def wrap_b():
        print("  [调用] 进入 b")
        func()
        print("  [调用] 离开 b")
    return wrap_b

@a
@b
def f():
    print("  [调用] 原函数 f 本体")

print("===== 装饰阶段结束，开始调用 f() =====")
f()