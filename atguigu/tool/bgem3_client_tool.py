"""
author: anrf
date:8/7/2026
desc:
"""
import threading

from pymilvus.model.hybrid import BGEM3EmbeddingFunction

from atguigu.config.config import EmbeddingConfig

bgem3_client_model = None
def get_bge_model():
    global  bgem3_client_model
    if not bgem3_client_model:
        bgem3_client_model = BGEM3EmbeddingFunction(
            model_name=EmbeddingConfig.bge_m3_path,
            device = EmbeddingConfig.bge_device,
            use_fp16=EmbeddingConfig.bge_fp16,
            batch_size=EmbeddingConfig.bge_batch_size,
 )
    return bgem3_client_model

# 全局推理锁：模型是进程级单例，多用户并发时串行化前向传播，
# 防止 GPU 显存叠加 OOM / CPU 线程池竞争导致性能退化
_bge_infer_lock = threading.Lock()

def get_bge_embedding(text:list):
    bgem3_client_model = get_bge_model()
    with _bge_infer_lock:
        embedding = bgem3_client_model.encode_documents(text)
    # print(embedding)
    # for item in embedding['dense']:
    #     print(item,type(item))
    # for item in embedding['sparse']:
    #     print(item.__dict__,type(item))

    # return {
    #     'dense' : [list([float(dense_item) for dense_item in  item]) for item in embedding.get('dense')],
    #     'sparse' : [dict(zip(
    #         [int(indice) for indice in item.indices],
    #
    #         [float(data) for data in item.data]
    #
    #     )) for item in embedding.get('sparse')]
    #
    # }
    return {
        'dense' : [item.tolist() for item in embedding.get('dense')],
        'sparse' : [dict(zip(
            item.indices.tolist(),

            item.data.tolist()

        )) for item in embedding.get('sparse')]

    }

if __name__ == '__main__':
    print(get_bge_embedding(['hello world','haha']))
