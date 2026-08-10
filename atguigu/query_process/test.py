from utils.embedding_utils import get_bge_m3_ef

model = get_bge_m3_ef()
result = model.encode_documents(["测试","test"])

print(result)