# LightRAG 生产级方案

> 基于 `kb_0515_graphrag` 项目思路，完整替换为 LightRAG 架构 + Neo4j + Milvus + MinIO 生产环境组件。
> 不含"当前 vs 生产"对比——每步直接给生产实现。

---

## 架构总览

```
        索引流水线                              查询流水线
─────────────────────────────      ─────────────────────────────────
Step 1  Entry    读文档（PDF/MD/HTML）
Step 2  Split    chunk_size=1200, overlap=100
Step 3  Extract  LLM抽取实体+关系+keywords
Step 4  Merge    增量消歧（精名→向量→LLM三级）
Step 5  Graph    Neo4j 图 + 双层倒排索引
Step 6~7         砍掉（社区检测+摘要不做）
Step 8  Embed    BGE-M3 → Milvus（两类向量）
Step 9  Store    Neo4j + Milvus + MinIO 并行写入

                                   问题 → 关键词提取（高低层）
                                             │
                                   低层倒排→实体  高层倒排→概念
                                             │               │
                                   加权图游走（深度随分数衰减）
                                             │
                                   MinIO取原文 → LLM → 答案
```

**核心理念：不做预计算社区检测和摘要。索引只建"骨架"（图+倒排），查询时按需游走发现主题簇。**

---

## Step 1：文档入口

```python
class DocumentReader:
    """支持 PDF / Markdown / HTML / TXT，统一输出纯文本 + 元数据。"""

    def read(self, file_path: str) -> dict:
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            text = self._parse_pdf(file_path)       # pymupdf / pdfplumber
        elif ext in (".md", ".txt"):
            text = open(file_path, encoding="utf-8").read()
        elif ext in (".html", ".htm"):
            text = self._parse_html(file_path)       # beautifulsoup4
        else:
            raise ValueError(f"不支持: {ext}")

        return {
            "file_path": file_path,
            "file_title": Path(file_path).stem,
            "content": text,
            "content_hash": hashlib.md5(text.encode()).hexdigest(),  # 增量判重用
        }
```

- **content_hash** 是关键——后续增量更新靠它判断"这份文档有没有变过"。

---

## Step 2：文档切分

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1200,       # LightRAG 用大 chunk（GraphRAG 用 300）
    chunk_overlap=100,     # 避免切断实体边界
    separators=["\n## ", "\n### ", "\n# ", "\n", "。", ".", " "],
)

chunks = []
for doc in splitter.split_documents([document]):
    chunks.append({
        "chunk_id": f"{file_title}-{idx:04d}",
        "title": extract_md_title(doc),   # 最近的 # 标题
        "content": doc.page_content,
        "content_hash": hashlib.md5(doc.page_content.encode()).hexdigest(),
        "part": idx,
    })
```

**chunk_size=1200 的原因：** 不做社区检测，不需要小 chunk 保证局部密度。大 chunk 减少 Step 3 的 LLM 调用次数（chunk 数少了一半以上）。

---

## Step 3：实体抽取（新增 keywords 字段）

```python
EXTRACT_PROMPT = """
你是知识图谱抽取助手。从文本中抽取实体和关系。

实体类型：设备/部件/概念/人物/组织/地点/操作/参数

关系要求：
- 关系描述用短语（如"包含""用于""是一种"）
- **额外输出 3~5 个 keywords**，描述该关系所属的抽象概念领域

输出 JSON：
{
  "entities": [{"name":"","type":"","description":""}],
  "relations": [{"source":"","target":"","description":"","keywords":["",""]}]
}
"""
```

**`keywords` 是 LightRAG 的核心创新。** 这个字段构建高层概念倒排索引，替代被砍掉的社区摘要。例如：

```json
{"source": "万用表", "target": "电压", "description": "测量",
 "keywords": ["电气测量", "仪器操作", "电压检测"]}
```

查询时，"电气测量"这个概念词会把所有测电相关的实体聚在一起——等价于社区检测但零预计算成本。

**每个 chunk 独立抽取，失败不阻塞：**

```python
for ch in chunks:
    try:
        data = llm.chat_json(EXTRACT_PROMPT, ch["content"])
    except Exception:
        data = {"entities": [], "relations": []}  # 优雅降级

    for ent in data.get("entities", []):
        name = (ent.get("name") or "").strip()
        if not name: continue                     # 防幻觉空实体
        raw_entities.append({**ent, "chunk_id": ch["chunk_id"]})

    for rel in data.get("relations", []):
        s, t = rel["source"].strip(), rel["target"].strip()
        if not s or not t or s == t: continue     # 防自环
        raw_relations.append({**rel, "chunk_id": ch["chunk_id"]})
```

**LLM 幻觉四层防御：** 格式解析容错 → 字段校验过滤 → 缺省值兜底 → 合并阶段自然淘汰（孤立噪声无法在图扩散中存活）。

---

## Step 4：实体合并（增量消歧）

生产环境的核心挑战：新文档不断来，不能每次全量重建。

```python
def resolve_identity(new_entity: dict, db: EntityDB) -> str:
    """三级防线判定新实体是"已知实体"还是"全新实体"。"""

    # ── 第 1 级：精确名称匹配（90% 命中，零成本） ──
    existing = db.find_by_name(new_entity["name"])
    if existing:
        return existing["id"]

    # ── 第 2 级：向量相似度匹配（处理同义词） ──
    vec = bge_m3.encode(new_entity["name"] + " " + new_entity.get("description", ""))
    candidates = milvus.search("entity_emb", vec, k=3)

    for cand, score in candidates:
        if score >= 0.95:
            return cand["id"]            # 高置信 → 直接合并
        if score >= 0.75:                # 模糊区间 → LLM 终裁
            if llm_judge_same(new_entity, cand):
                return cand["id"]

    # ── 第 3 级：全新实体 ──
    return db.create_entity(new_entity)
```

**合并后的数据：**

```python
entities = [{
    "id": "E0000",
    "name": "万用表",
    "type": "设备",
    "description": "多用途电子测量仪器；分为指针和数字两种",
    "chunk_ids": ["手册-0000", "手册-0002"],  # 跨 chunk 聚合
}]

relations = [{
    "source_id": "E0000",
    "target_id": "E0001",
    "description": "包含",
    "weight": 3,            # 被 3 个 chunk 独立验证——置信度信号
    "keywords": ["仪器结构", "设备组成"],
    "chunk_ids": ["手册-0000", "手册-0001", "手册-0002"],
}]
```

**weight 语义：不是关系强度，是"多少 chunk 独立抽到了同一关系"——高频 = 高置信。**

---

## Step 5：图构建 + 双层倒排索引

### 5.1 Neo4j 图存储

```python
# 批量写入节点
neo4j.run("""
    UNWIND $entities AS e
    MERGE (n:Entity {id: e.id})
    SET n.name = e.name, n.type = e.type,
        n.description = e.description, n.chunk_ids = e.chunk_ids
""", entities=entities)

# 批量写入边
neo4j.run("""
    UNWIND $relations AS r
    MATCH (s:Entity {id: r.source_id}), (t:Entity {id: r.target_id})
    MERGE (s)-[rel:RELATES {description: r.description}]->(t)
    SET rel.weight = COALESCE(rel.weight, 0) + r.weight,
        rel.keywords = r.keywords
""", relations=relations)
```

`MERGE` 语义天然支持增量——新文档写入自动去重，已有节点/边不会被覆盖。

### 5.2 双层倒排索引（Redis / Elasticsearch）

这是 LightRAG 替代社区摘要的关键：

```python
# 低层索引：实体名称 → 实体 ID 列表（精确匹配用）
low_index = {
    "万用表": [("E0000", 1.0)],
    "电压":   [("E0005", 0.9), ("E0003", 0.3)],
}

# 高层索引：概念关键词 → 实体 ID 列表（来自 relation.keywords）
high_index = {
    "电气测量": [("E0005", 0.95), ("E0002", 0.8), ("E0008", 0.85)],
    "仪器操作": [("E0000", 0.8), ("E0003", 0.7), ("E0006", 0.6)],
    "安全规范": [("E0020", 0.9), ("E0021", 0.7)],
}
```

**为什么双层：** 没有社区摘要了，但仍需要"按主题找实体"。高层索引用 keywords 把同主题实体聚在一起——等价于社区检测的语义聚类。

---

## Step 6~7：砍掉

**不做社区检测和社区摘要。** 原因：

| 砍掉原因 | 如何弥补 |
|---|---|
| 社区检测 O(n log n)，不支持增量 | 查询时双层关键词游走，现场发现主题簇 |
| 社区摘要 LLM 调用数 = 社区数，成本高 | 索引阶段零额外 LLM 调用 |
| 每次增删文档 → 社区重组 → 摘要作废 | 无社区结构，天然支持增量 |

**代价：** 全局性问题（"文档讲了什么"）精度不如 GraphRAG 的预写摘要。查询时需要 LLM 现场归纳。

---

## Step 8：向量化（两类，非三类）

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-m3")  # 1024 维，中英双语

# 实体向量：name + description
for ent in entities:
    text = f"{ent['name']} {ent['description']}"
    ent_vec = model.encode(text, normalize_embeddings=True)
    milvus.insert("entity_emb", [{"id": ent["id"], "vector": ent_vec.tolist()}])

# Chunk 向量：content
for ch in chunks:
    ch_vec = model.encode(ch["content"], normalize_embeddings=True)
    milvus.insert("chunk_emb", [{"id": ch["chunk_id"], "vector": ch_vec.tolist()}])
```

**两类向量：** entity_embeddings（低层检索种子） + chunk_embeddings（语义兜底）。社区向量不存在——没有社区。

**为什么 BGE-M3 替代 hash embedding：** hash embedding 只捕捉字面重叠（"万用表"和"万能表"完全不同）。BGE-M3 能理解"万能表就是万用表"——生产必备。

---

## Step 9：持久化 — Neo4j + Milvus + MinIO

**三组件并行写入：**

```python
import asyncio

async def persist(state: dict):
    await asyncio.gather(
        # 1. Neo4j：图拓扑 + 属性
        write_to_neo4j(state["entities"], state["relations"]),

        # 2. Milvus：两类向量（IVF_FLAT 索引，毫秒级 ANN）
        write_to_milvus(state["entity_embeddings"], state["chunk_embeddings"]),

        # 3. MinIO：原文 blob，按 chunk_id 存储
        write_to_minio(state["chunks"]),
    )
```

**各组件职责：**

| 组件 | 存什么 | 核心操作 | 为什么是它 |
|---|---|---|---|
| **Neo4j** | 实体节点 + 关系边 + 属性 | Cypher 图遍历、MERGE 增量 | 图数据库原生支持，SQL 做不到 1 跳邻居 O(1) |
| **Milvus** | 实体向量 + chunk 向量 | ANN 近似最近邻搜索 | 百万级向量毫秒级 TopK |
| **MinIO/S3** | chunk 原文文本 | 按 ID 读 blob | 文本几 KB~MB，对象存储便宜且无限扩容 |

**读取侧索引重建（GraphStore 改造）：**

```python
class GraphStore:
    def __init__(self):
        self.neo4j = Neo4jClient(uri=NEO4J_URI)
        self.milvus = MilvusClient(uri=MILVUS_URI)
        self.minio = MinioClient(endpoint=MINIO_ENDPOINT)
        # 倒排索引从 Redis 加载
        self.low_index = RedisIndex("entity_names")
        self.high_index = RedisIndex("concept_keywords")

    def search_entities(self, query: str, k: int = 5):
        qv = bge_m3.encode(query)
        results = self.milvus.search("entity_emb", [qv], limit=k)
        return [(self.neo4j.get_entity(r["id"]), r["score"]) for r in results]

    def neighbors(self, entity_id: str):
        return self.neo4j.run("""
            MATCH (e:Entity {id: $eid})-[r]-(n)
            RETURN n, type(r) AS rel_type, r.weight AS weight
        """, eid=entity_id)

    def get_chunk(self, chunk_id: str) -> str:
        return self.minio.get(f"chunks/{chunk_id}.txt")
```

---

## Step 10：查询 — 双层关键词图游走

**GraphRAG 做法回顾：** Local（向量+1 跳）+ Global（社区 Map-Reduce）+ Hybrid。

**LightRAG 做法：** 双层关键词驱动的加权图游走 + chunk 兜底。只有一条路径，没有并行。

### 10.1 关键词提取

```python
KEYWORD_PROMPT = """
从用户问题中提取两类关键词，输出 JSON：
- low_level: 具体的实体/术语/操作名（如"万用表""电压""测量"）
- high_level: 抽象的概念领域（如"仪器操作""电气测量""安全规范"）

{"low_level": ["",""], "high_level": ["",""]}
"""

def extract_keywords(query: str) -> tuple[list[str], list[str]]:
    kw = llm.chat_json(KEYWORD_PROMPT, query)
    return kw.get("low_level", []), kw.get("high_level", [])
```

### 10.2 双层索引匹配种子实体

```python
def find_seeds(low_kw: list[str], high_kw: list[str]) -> dict[str, float]:
    seeds: dict[str, float] = {}

    # 低层倒排：精确名称匹配
    for kw in low_kw:
        for ent_id, score in low_index.search(kw):
            seeds[ent_id] = max(seeds.get(ent_id, 0), score)

    # 高层倒排：概念关键词匹配
    for kw in high_kw:
        for ent_id, score in high_index.search(kw):
            seeds[ent_id] = max(seeds.get(ent_id, 0), score * 0.8)  # 概念匹配权重稍低

    # 向量兜底：关键词倒排没命中时用 entity_embeddings
    if not seeds:
        for ent, score in milvus.search_entities(query, k=5):
            seeds[ent["id"]] = score

    return dict(sorted(seeds.items(), key=lambda x: x[1], reverse=True)[:10])
```

### 10.3 加权图游走（深度随分数衰减）

```python
def weighted_walk(seeds: dict[str, float], max_depth: int = 2,
                  decay: float = 0.5) -> dict[str, dict]:
    """从种子实体出发，按权重衰减做多跳游走。"""
    visited: dict[str, dict] = {}
    frontier = seeds.copy()

    for depth in range(max_depth):
        next_frontier: dict[str, float] = {}
        for ent_id, score in frontier.items():
            if ent_id in visited:
                continue
            visited[ent_id] = neo4j.get_entity(ent_id)
            # 取邻居，分数衰减
            for nb, rel in neo4j.neighbors(ent_id):
                rel_weight = rel.get("weight", 1)
                new_score = score * decay * (1 + math.log1p(rel_weight))
                if new_score > 0.1:  # 阈值截断
                    next_frontier[nb["id"]] = max(
                        next_frontier.get(nb["id"], 0), new_score
                    )
        frontier = next_frontier

    return visited
```

### 10.4 收集原文 + chunk 兜底

```python
# 收集游走到的实体关联的 chunk
chunk_ids = set()
for e in visited.values():
    for cid in e.get("chunk_ids", []):
        chunk_ids.add(cid)

# chunk 向量兜底（无条件执行）
# 补上"图游走覆盖不到但原文直接相关的 chunk"
for ch, _ in milvus.search_chunks(query, k=5):
    chunk_ids.add(ch["chunk_id"])

# 从 MinIO 拉原文
chunks = [minio.get(f"chunks/{cid}.txt") for cid in chunk_ids][:8]
```

**为什么 chunk 兜底无条件执行：** 不是"实体匹配失败才兜底"，而是每次都跑。补的是图游走覆盖不到的隐性语义关联——例如实体抽取时遗漏的概念，或太抽象的问题（"有哪些风险"）。

### 10.5 LLM 生成

```python
context = {
    "entities": list(visited.values()),
    "relations": collect_relations(visited),  # visited 实体之间的边
    "chunks": chunks,
}
answer = llm.chat(GEN_PROMPT, f"问题：{query}\n上下文：{format_json(context)}")
```

---

## Token 消耗优化

### 各步骤占比

```
Step 3  实体抽取      ████████████████████████  ~80%（chunk 数 × 1 次 LLM）
Step 10 关键词提取    █                           ~3%
Step 10 Generate       █                           ~2%
Step 4  LLM消歧       █                           ~5%（仅模糊 case 触发）
其余步骤               零                           ~10%
```

### 优化策略

| 策略 | 做法 | 预计节省 |
|---|---|---|
| **多 chunk 批处理** | 5 个 chunk 拼一次 Prompt，减少调用次数 | ~60% |
| **模型降级** | 80% chunk 走 mini 模型（gpt-4o-mini），只有关键 chunk 走大模型 | ~50% |
| **结果缓存** | chunk content md5 做 key，相同文本复用抽取结果 | ~30%（重复文档场景） |
| **并行化** | 所有 chunk 的 LLM 调用并发 | 耗时省 ~80%（但不省 token） |
| **关键词提取用轻量模型** | 关键词提取不用完整 LLM，用 KeyBERT / TF-IDF + 规则 | ~3% |

**综合可省 ~70% token，同时保持精度。**

---

## 增量更新方案

```
新文档来了：
  ① content_hash 判重 → 已处理过的跳过
  ② 新 chunk 走 Step 3 抽取
  ③ resolve_identity() 三道防线消歧
  ④ Neo4j MERGE 语义只增不改
  ⑤ 倒排索引追加新 keyword → entity 映射
  ⑥ Milvus 追加新向量
  ⑦ MinIO 写入新 chunk 原文
```

**已有实体 ID 永不变化**——外部引用的链接永久有效。

---

## 精简 Q&A

### Q1: 什么情况必须用 GraphRAG 而非 LightRAG？

**判断公式：** 全局理解精度 × 全局问题占比 × 文档稳定性。三者都高 → 必用 GraphRAG。

具体场景：
- 需要主题树可视化、答案一致性有合规要求
- 文档极稳定且查询量大（预计算一次，反复用）
- 对"全局归纳遗漏"零容忍（社区摘要质量 > 现场归纳质量）
- 多文档跨实体推理是主场景

**反之：** 文档频繁改、成本敏感、实时要求高 → LightRAG。

### Q2: 向量匹配实体时用了社区摘要吗？

**没有。** Local Search 只用 `entity_embeddings`（实体 name+description 向量化）。社区向量在 Global Search 的独立路径上，两者在 NodeGenerate 才合并。

### Q3: chunk 兜底搜索什么时候真正起作用？

每次 Local Search 都无条件执行兜底。价值体现在：
- 实体抽取遗漏了关键实体（LLM/Mock 不是 100% 准确）
- 问题太抽象没有对应实体（"有哪些风险""需要注意什么"）
- 跨社区的隐性语义关联，图边覆盖不到

### Q4: LightRAG 砍掉社区后，全局问题怎么回答？

靠 Step 3 新加的 `relation.keywords` 构建高层概念倒排索引。"电气测量""仪器操作"这些概念词把同主题实体聚在一起，查询时通过概念关键词扩散 → 图游走 → LLM 现场归纳。精度不如预写摘要，但成本低 1~2 个数量级。

### Q5: 两种 RAG 对"万用表怎么测电压"的底层流程差异？

```
GraphRAG Local:
  query → Milvus 向量匹配实体 → Neo4j 1跳扩散 → MinIO取原文 + chunk兜底 → LLM

GraphRAG Global:
  query → Milvus 向量匹配社区摘要 → Map(每社区独立回答) → Reduce(合并)

LightRAG:
  query → LLM提取关键词(低层"万用表""电压" + 高层"电气测量")
       → 低层倒排锁实体 + 高层倒排索概念 → 合并种子实体
       → 加权多跳游走(深度随分数衰减) → MinIO取原文 + chunk兜底 → LLM
```

### Q6: 选型口诀

```
文档频繁改、成本敏感、实时要求高 → LightRAG
文档稳定、全局精度要求高、需要主题结构 → GraphRAG
```
