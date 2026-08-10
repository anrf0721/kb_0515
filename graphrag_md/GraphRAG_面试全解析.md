
# GraphRAG 全流程面试深度解析

> 基于 `kb_0515_graphrag` 项目，覆盖索引流水线 9 步 + 查询流水线 + 生产优化 + token 策略 + 增量更新。
> 每步含：做了什么 → 数据结构流转 → 为什么这么设计 → 三个面试 Q&A。

---

## Step 1：入口 (Entry)

**做了什么：** 读取 `.md` / `.txt` 文件，校验存在性和格式，把原始文本读入内存。

**数据流转：**
```
local_file_path → md_content (纯文本字符串)
```

**输出：** `file_title`, `md_path`, `md_content`

---

## Step 2：文档切分 (Document Split)

**做了什么：** 两层切分——先按 Markdown 标题 `# ~ ######` 粗切为 sections，再对超长段落用 `RecursiveCharacterTextSplitter` 细切（chunk_size=300，overlap=30）。每个 chunk 分配稳定的 `chunk_id`。

**数据流转：**
```
md_content → chunks: [{chunk_id, title, content, part}, ...]
```

**关键设计：** `chunk_id` 格式为 `{file_title}-{idx:04d}`，后续实体/关系全部挂载此 id，实现全链路溯源。

---

## Step 3：实体与关系抽取 (Entity Extraction)

### 主体浓缩

| 步骤 | 做了什么 | 为什么这么做 |
|---|---|---|
| ① 逐 chunk LLM 抽取 | 每个文本块独立调 LLM，输出 `{entities, relations}` JSON | 长文本上下文窗口有限；独立抽取召回率更高；失败不牵连其他 chunk |
| ② 挂载 chunk_id | 每条实体/关系都记录来自哪个 chunk | 全链路溯源——最终答案能精确回指原文段落 |
| ③ 逐条校验 + 兜底 | 过滤空名、自环关系、空端点；类型/关系缺省值兜底 | 防止 LLM 幻觉脏数据摧毁下游图构建 |

**数据流转：**
```
chunks → raw_entities: [{name, type, description, chunk_id}]
       → raw_relations: [{source, target, description, chunk_id}]
```

### Mock 模式

未配置 API Key 时，用 **5 组中文触发词正则** 模拟抽取：

| 正则模式 | 关系类型 |
|---|---|
| `A (是\|为\|即) B` | 是一种 |
| `A (包括\|包含) B` | 包含 |
| `A 由 B 组成` | 由...组成 |
| `A (连接\|安装于) B` | 连接/安装于 |
| `A (用于\|用来) B` | 用于 |

另将 Markdown 标题作为 `type:"主题"` 实体——Mock 独有补偿逻辑。

### LLM 幻觉处理：四层防御

```
解析层: 非 JSON → 容错剥 markdown 包裹 → 兜底返回 {}
校验层: 空名实体 → continue；自环关系 → continue
兜底层: 类型缺失 → 默认"概念"；描述缺失 → 默认"相关"
合并层: 幻觉实体只出现 1 次 → 同名合并后孤立 → 自然淘汰
```

**核心理念：不判断"是不是幻觉"（做不到），而是让幻觉数据无法在后续流程中生存。**

### 面试 Q&A

**Q1: 为什么要逐 chunk 抽取而不是全文一次丢给 LLM？**
- 上下文窗口有限——真实文档动辄几万字
- 召回更充分——短文本中 LLM 对每个实体关系更敏感
- 天然可溯源——每条知识都知道来自哪个 chunk

**Q2: 抽取和合并为什么拆成两个节点？**
- 职责分离：抽取只管"挖出来"，合并只管"消歧去重"
- 两个节点可以独立升级（换 Prompt 不影响合并，换合并算法不需要动抽取）
- 天然冗余在合并阶段靠同名碰撞自动聚合

**Q3: Prompt 设计的三个关键约束是什么？**
- 限定实体类型（设备/部件/概念/人物/组织/地点/操作/参数）→ 本体论约束，防止噪音爆炸
- 关系描述用短语（"包含""用于"）→ 方便后续按三元组去重合并
- 强制 JSON 输出 → 保证可解析

---

## Step 4：实体合并/消歧 (Entity Merge)

### 主体浓缩

| 步骤 | 做了什么 | 为什么这么做 |
|---|---|---|
| ① 同名聚合 | 名称相同的实体合并，收集所有 chunk_id 和 description | 同一实体在多 chunk 出现，每次描述不同——合并拼出完整画像 |
| ② 别名消歧 | 硬编码别名表（"万能表"→"万用表"） | 防止同一实体在图上裂成两个节点 |
| ③ 分配稳定 ID | 每个实体分配 E0000、E0001 不可变 ID | 后续图构建、社区检测、查询全部依赖 ID 引用 |
| ④ 关系重映射+权重 | source/target 从字符串改成 ID；相同三元组合并，次数累计为 weight | weight = 跨 chunk 置信度信号，图算法用它加权 |

### 相比 Step 3 新增了什么

```
Step 3: name 字符串 → Step 4: ID 化 + 去重 + weight
"万用表""万用表" → E0000（唯一）
"万用表--包含--显示屏"×3 → E0000--包含-->E0001 (weight=3)
```

### 面试 Q&A

**Q1: 为什么实体必须从 name 转成 ID？**
- 不可变性：ID 永远唯一，不受别名影响
- 图算法前提：NetworkX 节点增删、社区检测基于 hashable ID
- 关系索引效率：`source_id → target_id` O(1)，字符串匹配 O(n)

**Q2: weight 到底代表什么？**
- weight = 该关系被独立抽取的次数，不等于"关系强度"而是"多可信"
- 社区检测用 weight 加权；查询时按 weight 排序展示高置信度关系

**Q3: 别名消歧为什么用硬编码而不用 LLM？**
- 演示版最小实现。生产级用 LLM 二次消歧，但需混合策略：先向量聚类粗筛候选对，再对高相似度对调 LLM 确认，减少 N² 调用。

---

## Step 5：图构建 (Graph Build)

### 主体浓缩

| 步骤 | 做了什么 | 为什么这么做 |
|---|---|---|
| ① 实体→节点 | 每个实体变成图节点，挂载 name/type/description | 从扁平列表转成可拓扑运算的图结构 |
| ② 关系→边 | 按 source_id→target_id 连线；同两端多关系合并 weight | weight 累加 = 多重验证信号 |
| ③ 双输出 | NetworkX 对象（内存，给算法） + graph_json（序列化，给持久化） | 算法消费 vs 跨进程传递，职责不同 |

### 相比 Step 4 新增了什么

```
Step 4: 两个独立 Python 列表 → Step 5: 有拓扑的图（可查邻居、算距离）
```

### 面试 Q&A

**Q1: 为什么用无向图而不是有向图？**
- Leiden/Louvain 等社区检测算法基于无向图
- 关系多数对称（"包含"与"被包含"方向意义不大）
- 有向图可存方向语义在属性中，查询按需读取

**Q2: 同一对实体有多个不同关系描述怎么办？**
- weight 累加，descriptions 去重保留所有说法
- 查询时 LLM 能看到"有人说是'包含'也有人说是'由...组成'"——比单一描述丰富

**Q3: 为什么双输出（_graph + graph_json）？**
- `_graph`（NetworkX）是"热数据"——O(1) 邻居查询、子图提取，给算法消费
- `graph_json`（dict）是"冷数据"——可 JSON 序列化，用于持久化和跨进程传递

---

## Leiden 算法详解

### 输入格式

一个 **带权无向 igraph 图**：
```python
import igraph as ig
import leidenalg as la

g = ig.Graph()
g.add_vertices(["E0000", "E0001", ...])          # 实体 ID
g.add_edges([("E0000", "E0001"), ...])           # 关系
g.es["weight"] = [3.0, 1.0, ...]                 # weight 来自 Step 4

partition = la.find_partition(g, la.ModularityVertexPartition)
# → 层次化社区，多 level
```

### 内部三阶段（迭代执行直到收敛）

| 阶段 | 做什么 | 与 Louvain 的区别 |
|---|---|---|
| 局部节点移动 | 每个节点尝试移到邻居社区，选模块度增益最大的 | 只重访"邻居变了"的节点（smart local move），更快 |
| 分区细化 | 在粗分区内部再拆分，确保社区连通 | **这是 Leiden 碾压 Louvain 的关键**——Louvain 可能产出断裂社区 |
| 图压缩 | 每个社区→超级节点，构建新图 | 与 Louvain 相同，形成层次化结构 |

### 与 greedy_modularity 的对比

| | greedy_modularity（本项目） | Leiden（生产级） |
|---|---|---|
| 输出 | 单层 level:0 | 多层 level:0,1,2... |
| 连通性保证 | ❌ | ✅ |
| 速度 | 小图够用 | 大图更快 |
| 依赖 | 零额外 | 需要 leidenalg+igraph |

---

## Step 6：社区检测 (Community Detection)

### 主体浓缩

| 步骤 | 做了什么 | 为什么这么做 |
|---|---|---|
| ① 拆连通分量 | 按连通性拆为独立子图，≤2 节点直接当社区 | 连通分量间无关联，混在一起跑聚类没意义 |
| ② 贪心模块度聚类 | `greedy_modularity_communities(sub, weight="weight")` | weight 高 = 强引力，紧密节点分到同组 |
| ③ 社区截断 | > community_max_size(20) 的社区按 ID 硬切 | Step 7 要调 LLM 写摘要，太大塞不进 token 窗口 |

### 相比 Step 5 新增了什么

```
Step 5: 全局平铺图 → Step 6: 语义群落 = 主题聚类
```

### 面试 Q&A

**Q1: 为什么先拆连通分量再检测？**
- 贪心模块度对不连通图无意义——模块度定义依赖"组内边密度 vs 随机期望"，不连通组件间无边，强行合并反而拉低模块度

**Q2: weight 在算法里起什么作用？**
- weight = 社区检测的"引力"。weight=3 的边比 weight=1 的更能把两端节点拉进同一社区。本质是把 Step 4 的"跨 chunk 验证次数"转化为图上的连接强度

**Q3: 为什么用 greedy_modularity 而不是 Leiden？**
- 演示优先：NetworkX 内置，零额外依赖；Leiden 需要安装 leidenalg+igraph（Windows 痛苦）。生产环境必须换 Leiden

---

## Step 7：社区摘要 (Community Summary)

### 主体浓缩

| 步骤 | 做了什么 | 为什么这么做 |
|---|---|---|
| ① 收集社区上下文 | 捞出实体属性、**只取社区内部关系**（`nb in eids`）、关联 chunk（前 3 个 × 300 字） | 社区内部关系才是核心内容；截断适配 token 窗口 |
| ② LLM 生成摘要 | 上下文拼 Prompt → LLM → `{title, summary, full_content}` | 三层粒度：抬头标题、快速摘要、详细全文 |
| ③ Mock 兜底 | 无 LLM 时 title=实体名拼接，summary=关系罗列 | 无 API Key 也能运转 |

### 相比 Step 6 新增了什么

```
Step 6: [{community_id, entity_ids}] → Step 7: [{community_id, title, summary, full_content}]
从"冰冷 ID"变为"可读自然语言"——全局搜索的答案源
```

### 面试 Q&A

**Q1: 为什么预计算摘要而不是查询时实时生成？**
- 速度：查询时遍历调 LLM 太慢（几十秒），预计算后只需向量匹配（毫秒）
- 一致性：索引时生成完整快照，不受查询措辞影响

**Q2: title/summary/full_content 三层设计意图？**
- title → 向量匹配主文本（短，检索精度高）
- summary → global search map 输入（2~4 句，token 友好）
- full_content → 最终答案素材（详细，可追溯）

**Q3: 上下文截断策略（20 实体、30 关系、3 chunk × 300 字）的优化方向？**
- 实体应按"在社区内部度数"降序排列——核心实体优先展示给 LLM
- 当前无排序，是明确的优化点

---

## Step 8：向量化 (Embedding)

### 主体浓缩

| 步骤 | 做了什么 | 为什么这么做 |
|---|---|---|
| ① Chunk 向量化 | `embed(chunk.content)` → 向量 | 传统语义检索基线（兜底） |
| ② 实体向量化 | `embed(name + description)` → 向量 | Local Search 入口——匹配实体→图扩散 |
| ③ 社区向量化 | `embed(title + summary)` → 向量 | Global Search 入口——匹配摘要→map-reduce |

### 三类向量对应三种查询路径

```
chunk_embeddings     → 传统语义检索（兜底）
entity_embeddings    → Local Search（种子实体→图扩散→原文）
community_embeddings → Global Search（匹配社区→摘要→map-reduce）
```

### Hash Embedding 原理

```python
# 演示用：MD5 hash → 256 维伪向量，零依赖、零 GPU
tokens = 分词(text)             # 英文词 + 中文字 + 中文 bigram
for tok in tokens:
    idx = md5(tok) % 256        # 映射到某个维度
    sign = +1 or -1             # 随机正负
    vec[idx] += sign
vec = L2_normalize(vec)         # 单位向量
```

共享 token 的文本 → hash 冲突在相同位置 → 余弦相似度 > 0 → 能匹配上

### 面试 Q&A

**Q1: 为什么三类向量而不是一类？**
- 不同粒度问题需要不同检索入口："万用表测电压步骤"（chunk）、"万用表有哪些部件"（实体）、"文档讲了什么"（社区摘要）

**Q2: 实体用 name+description，社区用 title+summary，拼接策略为何不同？**
- 实体 name 太短（3 字），不加 description 区分度为零
- 社区 title+summary 已有 50~100 字，足够表达语义，加 full_content 反稀释关键词

**Q3: L2 归一化后点积当余弦，省了什么？**
- 每次 embed 出单位向量，查询时所有相似度计算都是点积——不需每次重新算模长和除法

---

## Step 9：图持久化 (Graph Store)

### 主体浓缩

**做了两件事：写 + 写的配套读。**

写（索引终点）：9 个字段逐个 `json.dump` 到 `data/` 目录。
读（查询起点）：`GraphStore.load()` 从 JSON 加载，构建 4 个内存索引。

**加载时构建的 4 个索引：**
```python
_ent_by_id   = {id: 实体}     # O(1) 查实体
_chunk_by_id = {id: chunk}    # O(1) 查原文
_report_by_cid = {id: 报告}   # O(1) 查摘要
_adj         = {id: [(邻居, 关系)]} # O(1) 图扩散
```

### 面试 Q&A

**Q1: 为什么 9 个 JSON 文件而不是一个数据库？**
- 演示最小化：JSON 零依赖、git diff 友好、任何语言可读
- 按需加载：只做 local search 可不加载 community 相关文件
- 生产必换 Neo4j+Milvus+MinIO

**Q2: 邻接表为什么不直接复用 relations 列表？**
- relations 是边列表，查邻居需 O(E) 全量扫描；邻接表 O(degree) 直达，Local Search 核心操作

**Q3: graph_json 和 relations.json 是否冗余？**
- 刻意冗余，服务不同消费者：graph_json（前端可视化）vs relations.json+entities.json（检索引擎）

---

## 生产环境：Neo4j × Milvus × MinIO

### 三组件分工

| 组件 | 存什么 | 核心操作 | 为什么用它 |
|---|---|---|---|
| Milvus | 三类向量 | ANN 近似最近邻 | 百万向量毫秒级 TopK |
| Neo4j | 实体节点+关系边+社区标签 | Cypher 图遍历 | 1 跳邻居 O(1)，多跳路径 O(k) |
| MinIO/S3 | chunk 原文+摘要全文 | 按 ID 读 blob | 文本不适合图数据库；对象存储无限扩容 |

### 写入（索引时）

```python
# 并行写入三种存储
Neo4j: MERGE 节点/边，ON CREATE SET / ON MATCH SET
Milvus: 批量 insert + create_index(IVF_FLAT)
MinIO: 每个 chunk 存为独立对象 chunks/{chunk_id}.txt
```

### 读取（查询时）

```
用户问题 → Milvus（向量匹配实体）→ Neo4j（图扩散邻居）
         → MinIO（读原文 chunk）→ LLM（生成答案）
```

---

## 查询流水线 (Local / Global / Hybrid)

### 架构

```
START ──┬── NodeLocalSearch ──┬── NodeGenerate ── END
        └── NodeGlobalSearch ─┘     (两路并行)
```

### Local Search（局部搜索）

```
问题 → 向量匹配 Top5 实体 → 图扩散 1 跳邻居 → 收集关联 chunk → 原文兜底
```

适用："万用表怎么测电压"——具体细节问题

**为什么只扩散 1 跳？** 多跳噪音爆炸，token 限制也塞不下。

### Global Search（全局搜索）

```
问题 → 向量匹配 Top5 社区摘要 → Map: 每个社区独立回答 → Reduce: 合并成最终答案
```

适用："文档整体讲了什么"——全局宏观问题

**为什么 Map-Reduce 拆两轮？** 一轮塞 20 个社区摘要超 token 限制；Map 先过滤压缩，Reduce 精确生成。

### Hybrid（混合）

两路上下文一起喂 LLM——既有细节又有全局视野。

### 面试 Q&A

**Q1: Local 和 Global 的本质区别？**
- Local 从"实体"出发（微观），Global 从"主题摘要"出发（宏观）
- Local 查不出全局性问题，Global 查不好细节性问题

**Q2: 为什么 Local Search 还补 search_chunks() 兜底？**
- 实体抽取不完美，可能漏实体。纯走实体路径会断。直接 chunk 匹配兜底保证至少有原文。

**Q3: Map-Reduce 为什么不一轮完成？**
- 一轮：20 个摘要超 token 限制。两轮：Map 过滤压缩到 5 个要点，Reduce 精确生成。且 Map 阶段可并行。

---

## Token 消耗全景分析

### 各步骤占比

```
Step 3  实体抽取      ████████████████████████████  ~80%
Step 7  社区摘要      ██████                        ~15%
查询    Global Map   █                             ~3%
查询    Generate      █                             ~2%
Step 1/2/4/5/6/8/9   零                              0%
```

### 优化策略

| 策略 | 原理 | 省多少 |
|---|---|---|
| 多 chunk 批处理 | 5 个 chunk 拼一次 LLM，省 System Prompt 重复 | ~20% |
| 模型降级+路由 | 80% 简单 chunk 走 gpt-4o-mini | ~70% cost |
| 结果缓存 | md5(chunk) → 已有结果直接复用 | 增量索引时 90% |
| 并行化 | 所有 chunk 零依赖，天然并行 | 省时间不省 token |
| 小社区模板化 | ≤2 实体社区不调 LLM | Step 7 省 30~50% |

**整体效果：75 万 tokens → 23 万 tokens，省 ~70%。**

---

## 生产环境增量更新

### 核心挑战

新增 1 篇文档到 1000 篇已有索引：既要让新知识"融入"，又不能破坏旧图结构。

---

### 第 1 层：增量 chunk 识别

**思路：** 不改切分逻辑，切完后逐 chunk 算 MD5 → 查 Neo4j，内容相同的跳过抽取。

**为什么 MD5 而不是 chunk_id？** `chunk_id` 是位置编号（`手册-0001`），文档增删段落会导致编号整体偏移，无法可靠判重。MD5 = 内容指纹，内容不变指纹就不变。

```python
def incremental_filter(chunks, db):
    new_chunks, existing_chunks = [], []
    for ch in chunks:
        h = md5(ch["content"])        # 内容指纹
        old = db.query("MATCH (c:Chunk {hash: $h}) RETURN c", h=h)
        if old:
            ch["_reuse"] = True        # 跳过抽取，从 Neo4j 捞出已有实体/关系复用
            existing_chunks.append(ch)
        else:
            ch["content_hash"] = h
            new_chunks.append(ch)       # 走完整 Step 3 抽取
    return new_chunks, existing_chunks
```

**效果：** 6 个 chunk 中 4 个未变化 → 只对 2 个新 chunk 调 LLM，省 67%。

---

### 第 2 层：实体身份判定（三道防线）

**思路：** 不再只靠同名聚合——要判断新实体是"已知实体（merge）"还是"全新实体（create）"。

```
防线 1: 精确名称匹配    → Neo4j 查同名 → 90% 命中，免费
防线 2: 向量相似度匹配  → Milvus TopK  → ≥0.95 直接合并，免费
                                         0.75~0.95 → 调 LLM 终裁
防线 3: 全新创建        → <0.75 或 LLM 判 different → CREATE
```

```python
def resolve_identity(new_ent, neo4j, milvus, llm):
    # 防线 1：精确名称
    exist = neo4j.query("MATCH (e:Entity {name: $n}) RETURN e", n=new_ent["name"])
    if exist: return exist["id"]

    # 防线 2：向量匹配 + 消歧
    vec = bge_m3.encode(new_ent["name"] + " " + new_ent["description"])
    for cand, score in milvus.search("entity_emb", vec, k=3):
        if score >= 0.95:                          # 高置信 → 直接合并
            return cand["id"]
        if score >= 0.75 and llm.judge_same(new_ent, cand):  # 模糊 → LLM
            neo4j.add_alias(cand["id"], new_ent["name"])     # 记别名，下次走防线1
            return cand["id"]

    # 防线 3：全新实体
    return neo4j.create_entity(new_ent)
```

**成本：** 100 个新实体，LLM 只被调 ~1 次。

---

### 第 3 层：图变更事务

**核心原则：只追加，不覆盖。**

```python
# 实体节点：ON CREATE 全写，ON MATCH 只追加 chunk_ids 和 description
neo4j.run("""
    UNWIND $entities AS e
    MERGE (n:Entity {name: e.name})
    ON CREATE SET n.id = e.id, n.type = e.type, n.description = e.description,
                  n.chunk_ids = e.chunk_ids, n.created_at = datetime()
    ON MATCH SET  n.chunk_ids = apoc.coll.union(n.chunk_ids, e.chunk_ids),
                  n.description = n.description + '；' + e.description,
                  n.updated_at = datetime()
""", entities=entities)

# 关系边：weight 只增不减
neo4j.run("""
    UNWIND $relations AS r
    MATCH (s:Entity {id: r.source_id}), (t:Entity {id: r.target_id})
    MERGE (s)-[rel:RELATES {description: r.description}]->(t)
    ON CREATE SET rel.weight = r.weight, rel.created_at = datetime()
    ON MATCH SET  rel.weight = rel.weight + r.weight, rel.updated_at = datetime()
""", relations=relations)
```

**为什么只追加不覆盖？** 已有节点可能被外部系统通过 `E0000` 引用，覆盖 name/type 会导致外部引用语义断裂。weight 只增不减 = 被反复验证的关系越来越可信。

---

### 第 4 层：社区局部重检测

**思路：** 新增/变更的实体只影响局部图结构。白天局部检测 → 夜间全量纠偏。

```python
def local_redetect(changed_entity_ids, neo4j):
    # 1) 取 2 跳邻域子图
    sub_G = neo4j.export_subgraph(radius=2, seeds=changed_entity_ids)

    # 2) 子图上做社区检测（Leiden/greedy_modularity）
    new_comms = leiden_or_greedy(sub_G, weight="weight")

    # 3) 只重写受影响的社区摘要（波及 ~5% 社区）
    for comm in new_comms:
        neo4j.update_community(comm, scope="local")
        llm.generate_summary(comm)  # 只为新社区调 LLM

def nightly_full_redetect(neo4j):
    # 凌晨 2 点：全图导出 → 全量 Leiden → 覆盖所有社区 + 摘要 → scope='global'
    full_G = neo4j.export_full_graph()
    partition = leiden(full_G, n_iterations=-1, seed=42)
    neo4j.replace_all_communities(partition, scope="global")
```

**两层检测关系：** 查询时优先用 `scope='local'` 的最新社区；社区年龄 > 24h 且存在 global 版本 → 用 global。

---

### 文档删除处理

**不做物理删除，做软降权。**

```python
def soft_delete_document(doc_id, neo4j):
    # 1) 所有 chunk 标记 inactive
    neo4j.run("MATCH (c:Chunk) WHERE c.doc_id = $id SET c.active = false, c.deleted_at = datetime()", id=doc_id)

    # 2) 孤立的实体/关系不删，但标记 deprecated
    neo4j.run("""
        MATCH (e:Entity) WHERE ALL(cid IN e.chunk_ids WHERE EXISTS {
            MATCH (ch:Chunk {chunk_id: cid}) WHERE ch.active = false
        }) SET e.deprecated = true
    """)

    # 3) 社区检测只用 active chunk 的关系
    # MATCH ... WHERE ALL(cid IN rel.chunk_ids WHERE EXISTS { (ch:Chunk) WHERE ch.active = true })
```

**为什么：** 外部系统可能通过实体 ID 做了引用（书签、问答历史），硬删除会导致悬挂引用。软降权保留拓扑结构。

---

### 图稳定性保证

| 保证 | 手段 |
|---|---|
| **实体 ID 永不变更** | `resolve_identity()` 优先返回已有 ID，全新才分配新 ID |
| **关系 weight 只增不减** | `ON MATCH SET weight = weight + r.weight` |
| **名称/类型不覆盖** | `ON MATCH` 只追加描述，不动已有属性 |
| **删除不破坏拓扑** | 软降权，节点和边物理保留 |
| **社区变更可追溯** | scope=local/global 双版本，按时间择优 |

### 面试 Q&A

**Q1: 新实体如何判断是"全新"还是"已有别名"？**
- 精名（免费 90%）→ 向量（免费 8%）→ LLM（付费 ~1%）。LLM 确认后写入别名，下次走防线 1 命中。

**Q2: 删除旧文档时实体和关系怎么处理？**
- 软降权三步：chunk 标记 inactive → 孤立的实体/关系标 deprecated → 社区检测自动忽略 inactive chunk 的边。不物理删除，保留历史引用。

**Q3: 大规模增量更新时社区重检怎么不炸？**
- 变更传播半径=2，80% 社区不受影响。白天局部重检波及 ~5% 社区摘要，夜间全量 Leiden 统一纠偏。Cost 从 O(N) 降为 O(Δ)。

---

## 全流程一图总结

```
┌───────────── 索 引 流 水 线 ─────────────┐
│                                            │
│  Step 1: 读取 .md → md_content             │
│  Step 2: 切分 → chunks (带 chunk_id)        │
│  Step 3: 逐 chunk LLM 抽取 → raw_entities   │
│                        → raw_relations      │
│  Step 4: 合并消歧 → entities (ID化)         │
│                   → relations (带 weight)   │
│  Step 5: 构建 NetworkX 图 → _graph          │
│  Step 6: 社区检测 → communities (语义簇)     │
│  Step 7: LLM 社区摘要 → community_reports    │
│  Step 8: 三类向量化 → embeddings            │
│  Step 9: 持久化落盘 → data/*.json           │
│                                            │
└─────────────────┬──────────────────────────┘
                  │
┌─────────────────▼──── 查 询 流 水 线 ──────┐
│                                            │
│  GraphStore.load() ← 加载 9 个 JSON         │
│  ┌──────────────────┐                      │
│  │ Local Search      │ 实体匹配→图扩散→原文  │
│  └──────┬───────────┘                      │
│  ┌──────┴───────────┐                      │
│  │ Global Search     │ 社区摘要→Map-Reduce  │
│  └──────┬───────────┘                      │
│         ▼                                   │
│  NodeGenerate → LLM → 最终答案              │
│                                            │
└────────────────────────────────────────────┘
```

---

## 专题：提示词工程 vs 上下文工程

### 概念区分

| 维度 | 提示词工程 (Prompt Engineering) | 上下文工程 (Context Engineering) |
|---|---|---|
| 核心问题 | LLM **"怎么做事"** | LLM **"看到什么"** |
| 稳定性 | 静态，写一次很少变 | 动态，每次调用都不同 |
| 对质量的影响 | 决定输出**可用性**（格式对错） | 决定输出**准确性**（内容对错） |
| 本项目体现 | 每个节点的 `*_SYSTEM` 常量 | 每次拼装的 `user` 消息内容 |

**一句话：** Prompt 决定 LLM **会不会做这个任务**，Context 决定 LLM **掌握了多少信息来做这个任务**。

### 代码中的体现

```python
# ===== Prompt Engineering =====
# 定义角色、输出格式、本体论约束
EXTRACT_SYSTEM = (
    "你是知识图谱抽取助手……实体类型尽量使用：设备/部件/概念/人物/组织/地点/操作/参数。"
    '输出 JSON: {"entities":[{"name":"","type":"","description":""}],'
    '"relations":[{"source":"","target":"","description":""}]}'
)

# ===== Context Engineering =====
# 决定喂什么、喂多少、怎么排序
user = (
    f"实体列表:\n" + "\n".join(ent_lines[:20]) + "\n\n"     # ← 截断20个实体
    f"关系列表:\n" + "\n".join(sorted(set(rel_lines))[:30])    # ← 截断30条关系
    f"原文片段:\n" + "\n---\n".join(ctx_lines)               # ← 每chunk截300字
)
```

### 在不同阶段的表现差异

```
Step 3 抽取:   Context = 单 chunk 原文（短，聚焦，不需截断）
              Prompt = 本体论约束 + JSON 格式强制 + 幻觉防御

Step 7 摘要:   Context = 实体 + 关系 + 原文 三合一拼装（需精心截断）
              Prompt = 信息压缩导向 + 三层输出粒度

查询阶段:     Context = 图扩散邻居 + 社区摘要 Map 结果（多源拼接）
              Prompt = 角色定义 + 禁止编造
```

---

## 专题：实体抽取/合并 vs 社区检测/摘要 的设计差异

### 两种不同的操作范式

| 维度 | 抽取 + 合并 (Step 3/4) | 社区检测 + 摘要 (Step 6/7) |
|---|---|---|
| **目标** | 从文本中"挖"出结构化知识 | 把知识"组织"成可读的语义单元 |
| **核心操作** | LLM 提取 → 同名聚合 → ID化 → 关系权重 | 图算法聚类 → LLM 生成摘要 |
| **LLM 角色** | **提取者**（从自然语言识别实体关系） | **总结者**（从已结构化数据生成摘要） |
| **输入** | 原始文本 chunks | 建好的图（entities + relations） |
| **数据流向** | 非结构化 → 结构化（文本 → 三元组） | 结构化 → 自然语言（三元组 → 摘要文本） |
| **Token 消耗** | ~80%（索引流水线绝对大头） | ~15% |

### 抽取 + 合并的四个设计原则

| 原则 | 做法 | 目的 |
|---|---|---|
| **逐 chunk 独立抽取** | 每个文本块单独调 LLM | 突破窗口限制；召回率更高；天然可溯源 |
| **本体论约束** | 限定实体类型 8 类，关系用短语 | 防止噪音爆炸，方便按三元组去重 |
| **同名聚合 + ID 化** | 同名字符串合并 → 分配 E0000 不可变 ID | 同一实体在多 chunk 的描述拼成完整画像 |
| **权重累加** | `(source_id, target_id, desc)` 三元组聚合，weight += 1 | weight = 跨 chunk 验证次数，越高越可信 |

### 幻觉防御：不判断"是不是幻觉"，而是让幻觉数据自然淘汰

```
解析层: 非 JSON → 剥 markdown 包裹 → 兜底返回 {}
校验层: 空名实体 → skip；自环关系 → skip
兜底层: 类型缺失 → "概念"；描述缺失 → "相关"
合并层: 幻觉实体只出现 1 次 → 同名合并后孤立 → 自然淘汰
```

### 社区检测 + 摘要的设计要点

**社区检测（纯算法，零 LLM）：**
- 先拆连通分量再检测——不连通组件间无边，混在一起跑聚类无意义
- weight 是"引力"——weight=3 的边比 weight=1 更能把两端节点拉进同一社区
- 大社区硬切（>20 实体）——防止 Step 7 的 LLM 摘要塞不进 token 窗口

**社区摘要（LLM + 精心截断）：**
- 上下文 = 实体[:20] + 社区内部关系[:30] + 相关 chunk[:3]×300 字
- 关系只取"社区内部"的（`nb in eids`），外部关系属于别的社区
- 三层输出设计：`title`（向量匹配主文本）→ `summary`（Global Search Map 输入）→ `full_content`（最终答案素材）

### 面试 Q&A

**Q1: 抽取和合并为什么要拆成两个节点？**
- 职责分离：抽取只管"挖出来"，合并只管"消歧去重"
- 独立升级：换 Prompt 不影响合并算法，换合并策略不需要动抽取
- 天然冗余在合并阶段靠同名碰撞自动聚合，幻觉实体自然淘汰

**Q2: 社区检测（Step 6）为什么不用 LLM？**
- 社区检测是纯图算法问题——模块度最大化、连通性判断，LLM 既不擅长也不经济
- 图算法 O(E log V) 毫秒级，换成 LLM 遍历判断是 O(N²) 次数 + 秒级延迟
- 社区检测的输入是 ID 列表，LLM 不理解图拓扑

**Q3: Context Engineering 在 Step 7 还有哪些优化空间？**
- 实体应按"社区内部度数"降序排列——核心实体优先展示给 LLM（当前无排序）
- 原文 chunk 应按与社区主题的相关性排序，而非按 chunk_id 顺序
- 关系描述可以由 weight 加权排序，高置信度关系优先
