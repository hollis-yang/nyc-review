# RAG v2 Optimization Roadmap

状态：Proposed

范围：`agent-service` 的 Embedding、候选召回、查询扩展、重排、评测与生产发布

基线日期：2026-08-31

## 1. 目标与结论

本路线图将当前“结构化候选 + 规则扩展 + Qdrant 候选内 Hybrid RAG + 人工加权重排”升级为可评测、可回退、可渐进发布的 RAG v2：

1. 使用真实的多语言语义 Embedding 取代生产与评测中的 64 维 Hash Embedding。
2. 将 Qdrant 从“已有候选内重排”升级为全局候选召回，与 Spring 结构化检索并行。
3. 在现有规则扩展之上增加受约束的 LLM Multi-Query，并始终保留原始查询与规则回退。
4. 在候选融合后增加可插拔的多语言 Cross-Encoder，只重排小规模候选集合。
5. 建立独立的困难评测集、消融实验、阶段延迟与成本指标，避免仅用一个接近饱和的 Recall@10 证明所有改动。

推荐实施顺序：

```text
M0 评测与观测基线
        ↓
M1 真实 Embedding 与索引版本化
        ↓
M2 全局 Hybrid 候选召回
        ↓
M3 受约束的 LLM Multi-Query
        ↓
M4 Cross-Encoder 重排
        ↓
M5 Shadow / Canary / Production rollout
```

不要同时启用所有优化后只跑一次总评测。每个里程碑都必须有单独的消融报告和回退开关。

## 2. 当前基线审计

| 领域 | 当前实现 | 已知限制 |
| --- | --- | --- |
| 语料 | 5,000 个 OSM 来源商户身份，145,000 个索引文档 | 商户身份真实；评论与部分业务内容为明确标记的合成内容 |
| Dense 向量 | `DeterministicHashEmbeddingService`，默认 64 维 | 不是神经网络语义 Embedding；中文与无词面重合的同义表达能力弱 |
| 真实 Embedding | 已有 OpenAI-compatible `/embeddings` Adapter | 默认、生产示例和 P12/P13 Eval 均未启用 |
| Sparse 向量 | token/hash sparse vector + Qdrant IDF | 可复现，但不是学习型 sparse encoder |
| 查询扩展 | 中英文别名词典 + canonical tags | 仅覆盖预定义表达，不能泛化到新的口语化或组合表达 |
| 候选生成 | Spring/Generated Adapter 先返回商户，Qdrant 使用 `shop_ids` Filter | 第一阶段漏召回后，Qdrant 无法恢复正确商户 |
| Fusion | Dense/Sparse 使用 RRF | 只在受限候选集合内融合 |
| 重排 | Hybrid 0.45 + tag 0.35 + distance 0.10 + rating 0.10 | 权重人工设定，没有独立的语义相关性模型 |
| Evidence | 商户 Fact + Review Thread，按来源、根评论与文本去重 | 还没有 claim-level grounding 或 citation faithfulness 评测 |
| Eval | 72 条查询：60 英文、12 中文 | 查询大量直接包含 canonical tag；Recall@10 已接近饱和，hard negative 不足 |
| 当前结果 | 99.54% Recall@10、100% evidence coverage | 评测固定使用 Hash Embedding，不能证明 Dense 语义能力 |
| 生产约束 | 4 GB AWS Lightsail，单 Agent Service | 本地大型 Embedding/Reranker 模型可能造成内存和延迟压力 |

### 2.1 现有结果的解释边界

当前 P12/P13 检索评测在 `evals/p12/run_retrieval_eval.py` 中显式使用：

```text
embedding_provider = hash
embedding_dimensions = 64
model_provider = heuristic
```

因此在 RAG v2 报告生成前：

- 可以声明系统实现了 Dense/Sparse Hybrid Retrieval。
- 不应把 99.54% Recall@10 归因于生产级语义 Embedding。
- 不应把“真实来源商户”表述成“145,000 份真实用户文档”。
- `reranking` 更准确的当前名称是 `multi-signal heuristic reranking`。

## 3. 目标架构

```text
Natural-language query
        │
        ▼
Typed constraint extraction
  - category / neighborhood / budget / party size
  - required tags / optional preferences / visit time
        │
        ▼
QueryPlanV2
  - original query
  - deterministic bilingual alias expansion
  - 0..N validated LLM rewrites
  - immutable hard constraints
        │
        ├───────────────────────────────────────┐
        ▼                                       ▼
Spring structured retrieval              Qdrant global hybrid retrieval
  - exact business filters                 - multilingual dense embedding
  - category / area / hours                - lexical sparse retrieval
  - budget / availability                  - RRF across query variants
        │                                       │
        └──────────────────┬────────────────────┘
                           ▼
                 Merchant-level aggregation
                 - group by shop_id
                 - source-aware deduplication
                 - structured/vector RRF fusion
                           │
                           ▼
                 Cross-Encoder reranking
                 - top-N only
                 - hard constraints cannot be overridden
                 - timeout / circuit-breaker fallback
                           │
                           ▼
                 Final candidates (top 5..10)
                    ├───────────────┐
                    ▼               ▼
              Evidence Agent   Itinerary Agent
                    └───────┬───────┘
                            ▼
                         Verifier
```

### 3.1 设计原则

1. **Hard constraints 与 semantic relevance 分离。** 区域、预算、营业时间和明确无障碍要求不能被高语义分数覆盖。
2. **原始查询永不丢失。** 规则扩展或 LLM Rewrite 只增加召回通道，不能替换用户原文。
3. **每个智能组件都有确定性 fallback。** Embedding、Rewrite、Reranker 失败时，系统仍能使用 Sparse + Structured Retrieval 返回结果。
4. **索引不可原地变更模型或维度。** 新 Embedding 必须进入新 Collection，验证完成后再切换。
5. **质量、延迟、成本同时评估。** 不接受只提高 Recall、却让延迟或成本不可控的方案。
6. **先证明增益，再写入简历。** 所有未来百分比必须来自冻结评测集和可复现报告。

## 4. 跨阶段数据契约

建议先引入下列领域对象，避免后续阶段继续传递松散的 `dict`。

### 4.1 `EmbeddingMetadata`

```python
class EmbeddingMetadata(BaseModel):
    provider: str
    model: str
    dimensions: int
    version: str
    query_prefix: str | None = None
    document_prefix: str | None = None
```

该 metadata 必须写入：

- Qdrant Collection/索引 manifest；
- Agent health metadata；
- Eval 报告；
- Trace 的 embedding span；
- Collection 切换检查。

### 4.2 `QueryPlanV2`

```python
class QueryPlanV2(BaseModel):
    original_query: str
    rule_expanded_query: str
    rewrite_queries: list[str]
    hard_constraints: UserConstraints
    semantic_tags: list[str]
    language: str
    rewrite_provider: str
    rewrite_prompt_version: str
```

约束：

- `rewrite_queries` 默认最多 3 条；
- 去重后必须包含 `original_query`；
- Rewrite 不得修改 `hard_constraints`；
- 单条 Rewrite 必须有长度上限；
- 无效 JSON、超时或模型错误时返回空 Rewrite 列表。

### 4.3 `MerchantRetrievalHit`

```python
class MerchantRetrievalHit(BaseModel):
    shop_id: int
    structured_rank: int | None
    dense_ranks: list[int]
    sparse_ranks: list[int]
    representative_document_ids: list[str]
    fusion_score: float
    retrieval_sources: list[str]
    hard_constraint_match: bool
```

该对象用于解释一个商户为什么进入候选集，并为 Trace、Eval 和 Reranker 提供统一输入。

## 5. M0：评测与可观测性基线

### 5.1 目标

在改变算法前建立可复现的 RAG Eval v2，为后续逐阶段对比 Dense、Sparse、Structured、Rewrite 和 Reranker 提供基线。

### 5.2 工作项

- [x] 新建 `agent-service/evals/rag_v2/`，不要覆盖现有 P12 冻结用例。
- [x] 创建最少 160 条冻结查询：80 英文、60 中文、20 中英混合。
- [x] 按 50% development / 50% policy holdout 划分，调参只能使用 development。仓库内 holdout 并非真正秘密数据，未来可在私有 CI artifact 中补充 hidden test。
- [x] 每条查询标注 0–3 级 merchant relevance，而不只是 expected ID 集合。
- [x] 单独标注 hard-constraint violations：区域、类别、预算、营业时间、无障碍。
- [x] 增加覆盖 structured filtering 与 ranking 的 hard negatives；每个 split 466 个，其中 60 个进入 structured candidate pool，不能表述为纯 reranker benchmark。
- [x] 增加面向词典外表达设计的口语、拼写错误、组合约束和否定表达，并冻结当前规则的实际识别覆盖审计。
- [x] 增加 branch/geo isolation、同名商户、跨 Borough、过期数据与 security-test 文档。过期数据使用隔离 eval fixture，因为 P13 语料没有自然 expired record。
- [x] 冻结 case SHA 与覆盖顶层评测语义的 suite contract SHA，并在报告中记录数据集 SHA、检索版本与 Embedding Metadata。
- [x] 让 Eval CLI 接受 Embedding、Rewrite、Global Retrieval 和 Reranker 参数；尚未实现的启用值 fail-fast。
- [x] 输出总体指标及 `en`、`zh`、`mixed` 和 scenario 分组指标。

### 5.3 新增指标

质量：

- Recall@5 / Recall@10
- Precision@5
- nDCG@5 / nDCG@10
- MRR@10
- Hard-constraint satisfaction rate
- Evidence coverage
- Duplicate merchant ID、duplicate brand（第 2 个起）与 excessive brand concentration（第 3 个起）
- Hard-negative final-return rate
- Citation source mismatch rate
- Security leakage count
- Dataset/version mismatch rate

性能与成本：

- P50/P95/P99 total retrieval latency
- Query planning、Embedding、Structured Search、Qdrant、Fusion、Reranker 分阶段延迟
- 每次查询的 Rewrite/Embedding/Reranker 请求数
- 每次查询的 token 或 provider usage
- 初次索引时间、增量索引时间与 Collection 大小

### 5.4 建议文件

```text
agent-service/evals/rag_v2/
├── cases.dev.json
├── cases.test.json
├── quality_gate.json
├── build_cases.py
├── run_eval.py
├── metrics.py
└── README.md
```

### 5.5 暂定质量门禁

这些门禁在第一次 v2 baseline 后冻结；测试集结果不用于调参。

| 指标 | 暂定 Gate |
| --- | --- |
| Security leakage | `0` |
| Version mismatch | `0` |
| Duplicate merchant ID rate | `0` |
| Excessive brand concentration | 同品牌第 3 个及以后结果为 `0` |
| Hard-negative final-return rate | 不得高于 baseline 0.5 个百分点以上 |
| Evidence coverage | `>= 99%` |
| Hard-constraint satisfaction | `>= 99%` |
| Recall@10 | 不低于 v2 baseline 0.5 个百分点以上 |
| nDCG@10 | 最终方案相对 v2 baseline 至少提升 3 个百分点 |
| 中文 nDCG@10 | 不低于英文增益趋势，且不得回归超过 1 个百分点 |
| P95 latency | Total latency 不超过同一完整 profile baseline 的 1.25 倍；独立阶段只有在可可靠测量后再冻结门禁 |

### 5.6 验收标准

- [x] 同一配置的确定性排名结果可复现；非确定性 provider metadata 当前标记为 unavailable，不伪造数值。
- [x] Hash Embedding baseline 可以完整复现。
- [x] 报告能明确区分真实 Embedding 与 Hash Embedding。
- [x] 报告中不存在未标注的模型、维度、Collection 或数据版本。

### 5.7 M0 完成记录（2026-08-31）

实现与运行说明见 [`evals/rag_v2/README.md`](./evals/rag_v2/README.md)，冻结结果见 [`evals/rag_v2/baseline.hash64.local.json`](./evals/rag_v2/baseline.hash64.local.json)。当前 Hash/64 local-disk baseline：dev `Recall@10=59.62%`、`nDCG@10=76.28%`、`P95=9.91s`；policy holdout `Recall@10=71.14%`、`nDCG@10=79.79%`、`P95=6.82s`。两个 split 的证据覆盖率均为 100%，security/version/source/owner mismatch、重复 merchant ID 与第 3 个及以后同品牌集中均为 0；同品牌第 2 个结果分别出现 3/4 次，hard-negative final-return rate 为 2.66%/2.78%。完整重复运行 dev 后，原始 quality/integrity summary 与基线逐字段一致，relative gate 通过，重复 `P95=8.02s`。

硬约束满足率分别为 94.63% 和 95.63%，尚未达到 99% 暂定目标；失败集中在营业时间场景，证明当前 structured candidate service 尚未执行 `visit_time`。M0 保留该失败信号，后续阶段不得通过删除用例或放宽 oracle 隐藏缺口。

当前服务只能可靠拆出 Structured Search、Candidate Ranking、Evidence Retrieval、Embedding wrapper 和 Total 外层耗时；Query Planning、Qdrant、Fusion、Rewrite、learned Reranker 与 provider token/cost 在报告中明确标为 unavailable/disabled。

评测边界已写入 suite contract：dev/test 的 intent 与 query 无重叠，但有 12 个 judged merchant（9 个 binary-relevant）重叠；语言 slice 不是同 intent 的成对翻译对照；`out_of_dictionary_paraphrase` 记录 phrase-bank 来源，并不保证规则完全未识别。冻结 baseline 生成于带并行 session 修改的 dirty worktree，manifest 已记录当时 Git SHA 和该事实。

## 6. M1：真实多语言 Embedding 与索引版本化

### 6.1 目标

将 Hash Embedding 限定为测试实现，让生产与正式 Eval 使用通过对照实验选出的真实多语言语义 Embedding。

### 6.2 Embedding 接口调整

将当前统一的 `embed(texts)` 拆分为查询与文档方法：

```python
class EmbeddingService(Protocol):
    @property
    def metadata(self) -> EmbeddingMetadata: ...

    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def aclose(self) -> None: ...
```

原因：部分检索模型要求 query/document 使用不同指令或前缀；统一接口会损失检索能力。

### 6.3 Provider 工程化

- [ ] 复用持久化 `httpx.AsyncClient`，不在每个 batch 内重新创建连接池。
- [ ] 配置 connect/read timeout；禁止无限等待。
- [ ] 对 429、可重试 5xx 和连接错误执行有上限的指数退避。
- [ ] 限制批次数量、字符/token 预算和并发数。
- [ ] 验证返回数量、顺序、维度、NaN/Inf 和空向量。
- [ ] Trace 只记录 provider/model/dimensions/latency/count，不记录 API Key。
- [ ] Query Embedding 增加有界 LRU/TTL Cache，Key 包含 normalized query 与 embedding version。
- [ ] 文档增量同步继续使用 `content_sha256` 跳过未变化内容，并把 embedding version 纳入复用条件。
- [ ] 为 Provider 失败增加明确的错误类型，供 Sparse-only fallback 与指标聚合使用。

### 6.4 配置建议

保留现有变量并增加：

```text
NYC_REVIEW_AGENT_EMBEDDING_VERSION=
NYC_REVIEW_AGENT_EMBEDDING_BATCH_SIZE=64
NYC_REVIEW_AGENT_EMBEDDING_MAX_CONCURRENCY=2
NYC_REVIEW_AGENT_EMBEDDING_TIMEOUT_SECONDS=
NYC_REVIEW_AGENT_EMBEDDING_MAX_RETRIES=
NYC_REVIEW_AGENT_EMBEDDING_QUERY_PREFIX=
NYC_REVIEW_AGENT_EMBEDDING_DOCUMENT_PREFIX=
NYC_REVIEW_AGENT_ALLOW_HASH_EMBEDDINGS=false
```

生产环境在 `embedding_provider=hash` 且未显式允许时应拒绝启动。测试环境继续默认允许 Hash Embedding。

### 6.5 Embedding 模型选择实验

至少比较：

1. 当前 64 维 Hash Embedding；
2. 当前代码已支持的 OpenAI-compatible 真实 Embedding baseline；
3. 一个适合中英文检索的多语言候选模型。

模型选择不能只看 Recall@10。必须同时比较中文/混合查询 nDCG、P95、索引时间、存储和费用。

重点用例应避免词面重合，例如：

```text
Query: 适合带轮椅长辈去的地方
Document: step-free entrance and accessible seating
```

### 6.6 Qdrant 索引迁移

禁止在现有 64 维 Collection 中直接写入新维度向量。

建议流程：

1. 创建新 Collection，例如 `nyc_review_content_v3_<embedding_version>`。
2. 使用现有数据集 SHA 与新 Embedding Metadata 构建完整索引。
3. 验证文档数、payload index、vector dimensions、来源分布和 security-test 排除逻辑。
4. 运行 M0 全量 Eval 与 smoke query。
5. 在 Shadow 环境同时查询旧/新 Collection，比较结果与阶段延迟。
6. 通过配置切换 active collection。
7. 保留旧 Collection 一个发布窗口，确认稳定后再由人工删除。

回滚只需要恢复旧 Collection 配置；不得在回滚时重新生成旧向量。

### 6.7 主要修改文件

```text
agent-service/app/rag/embeddings.py
agent-service/app/config.py
agent-service/app/runtime.py
agent-service/app/rag/qdrant_store.py
agent-service/evals/rag_v2/run_eval.py
agent-service/tests/test_runtime_qdrant.py
agent-service/tests/test_qdrant_rag.py
```

### 6.8 验收标准

- 正式 Eval 报告明确显示非 Hash Provider。
- 新 Collection 的 embedding metadata 与运行配置完全一致。
- Provider 失败时不会删除旧点或切换不完整 Collection。
- 中文与中英混合查询的 nDCG/MRR 相对 Hash baseline 有稳定提升。
- 相同内容的增量启动不会重新 Embedding 145,000 个文档。

## 7. M2：全局 Hybrid 候选召回

### 7.1 目标

解除 Qdrant 对 Spring 候选 ID 的完全依赖，使语义检索能够恢复结构化第一阶段漏掉的相关商户。

### 7.2 双路召回

Discovery 阶段并行执行：

1. **Structured branch**：保留 Spring/Generated Adapter，负责精确业务过滤与传统排序。
2. **Global Qdrant branch**：不传 `shop_ids`，在完整数据集 scope 内执行 Dense/Sparse Hybrid Retrieval。

Qdrant 全局 Filter 必须继续包含：

- `retrieval_version`
- `data_version`
- `dataset_sha256`
- `security_test != true`

明确的 category/neighborhood 等 hard constraint 可以下推为 payload filter；可放宽条件只能作为 soft signal，不能直接过滤。

### 7.3 文档到商户的聚合

全局搜索返回的是文档，不是商户。必须先按 `shop_id` 聚合：

- 每个查询变体对单个商户最多保留固定数量的文档；
- 记录 best rank、best score、top-k mean 和命中文档种类；
- 优先保留 identity/attribute fact 与不重复的 review thread；
- 同一 root review、source ID 或标准化 excerpt 不得重复计分；
- 单一高频品牌不能占满候选池。

初始候选规模建议作为配置而不是硬编码：

```text
global document hits: 100..300
global merchant candidates: 30..60
structured merchant candidates: 30..100
fusion output: 20..40
final candidates: 5..10
```

具体值必须在 development set 上调优。

### 7.4 Structured/Vector Fusion

建议使用 merchant-level RRF，而不是直接相加未校准的 Spring 分数与向量分数：

```text
score(shop) = Σ 1 / (rrf_k + rank_from_each_channel)
```

通道至少包括：

- Spring structured rank
- Dense rank
- Sparse rank
- 每个 Query Rewrite 的 Hybrid rank

业务评分、距离与品牌多样性在 Fusion 后作为受控 tie-breaker；hard constraint 不作为可补偿分数。

### 7.5 建议代码结构

```text
agent-service/app/rag/global_retrieval.py
agent-service/app/rag/merchant_aggregation.py
agent-service/app/rag/candidate_fusion.py
```

`QdrantRagService` 保留底层检索与 Evidence API，避免继续膨胀为包含所有策略的单体类。

### 7.6 Trace 字段

```text
structuredCandidates
globalDenseDocuments
globalSparseDocuments
globalMerchants
fusionCandidates
structuredOnlyMerchants
qdrantOnlyMerchants
overlapMerchants
duplicateDocumentsSuppressed
duplicateBrandsSuppressed
hardConstraintFiltered
```

### 7.7 测试

- [ ] Spring 漏掉正确商户时，Qdrant 全局召回可以恢复。
- [ ] Qdrant Provider 失败时仍返回 Structured 分支结果。
- [ ] Structured 分支失败时，在权限与数据版本正常的前提下可使用 Qdrant 结果。
- [ ] Security-test 文档、其他数据版本和其他 corpus 永不进入候选。
- [ ] 单商户多文档不会导致其分数无上限累积。
- [ ] 品牌去重不破坏 hard-required 的唯一正确结果。
- [ ] Fusion 对输入顺序稳定，重复运行结果一致。

### 7.8 验收标准

- Hard-negative Eval 中，Global Retrieval 能恢复至少一类当前候选生成无法召回的正确商户。
- Recall@10 不回归，nDCG@10 有可测增益。
- Qdrant 或 Structured 单分支失败时，Run 能受控降级并在 metadata 中标记。

## 8. M3：受约束的 LLM Multi-Query

### 8.1 目标

在保留当前 bilingual alias expansion 的基础上，覆盖词典外的口语表达、同义改写和中英混合查询。

### 8.2 不选择 HyDE 作为第一步

本地生活场景中的 HyDE 容易生成不存在的商户属性、评价或环境描述。第一版使用 Multi-Query，只改写检索意图，不生成假想答案或假想商户文档。

### 8.3 Rewrite 输出契约

模型只能返回结构化 JSON：

```json
{
  "language": "zh",
  "queries": [
    "quiet wheelchair-accessible restaurants in Midtown",
    "calm step-free dining options near Midtown"
  ],
  "requiredConstraints": {
    "neighborhood": "Midtown",
    "wheelchairAccessible": true
  }
}
```

校验规则：

- `requiredConstraints` 必须与已解析的 `UserConstraints` 一致；不一致时丢弃 Rewrite。
- 不允许增加用户没有表达的硬约束。
- 不允许删除否定条件或把 soft preference 升级为 hard constraint。
- Rewrite 最多 3 条，去重并限制长度。
- 原始查询与规则扩展始终进入检索。
- Model failure、invalid JSON、timeout、rate limit 时返回规则扩展结果。

### 8.4 工程实现

建议新增：

```text
agent-service/app/rag/query_rewriter.py
agent-service/app/rag/query_plan_v2.py
```

Provider 接口：

```python
class QueryRewriteService(Protocol):
    async def rewrite(
        self,
        query: str,
        constraints: UserConstraints,
    ) -> QueryRewriteResult: ...
```

实现至少包括：

- `DisabledQueryRewriteService`
- `OpenAICompatibleQueryRewriteService`
- `FallbackQueryRewriteService`

### 8.5 缓存与成本

- Cache Key 包含 normalized query、constraints、model 和 prompt version。
- 只缓存通过 schema 与 constraint validation 的结果。
- 记录 Rewrite 次数、延迟、token、cache hit 与 fallback reason。
- Query Rewrite 使用单独的并发限制，不能耗尽主 Agent Model 连接预算。

### 8.6 检索融合

每个 Query Variant 独立执行 Hybrid Retrieval，再在 merchant level 使用 RRF 融合。不要先把所有 Rewrite 拼成一个超长字符串后只生成一个向量。

应保留 query provenance：最终候选需要知道自己由 original、rule expansion 或哪个 rewrite 召回。

### 8.7 测试

- [ ] 中文、英文和中英混合查询都能生成合法 Rewrite。
- [ ] Rewrite 不能改变预算、人数、区域和 required tags。
- [ ] 原始查询始终参与召回。
- [ ] Invalid JSON、provider timeout 和 429 会回退且不导致 Run 失败。
- [ ] 相同 QueryPlan 的缓存结果稳定。
- [ ] Prompt injection 输入仍在 API 边界被拒绝，不能借 Rewrite 绕过审批或工具策略。

### 8.8 验收标准

- 词典外 paraphrase 子集的 Recall/nDCG 明显优于 M2。
- 已在词典覆盖范围内的简单查询不得显著回归。
- Rewrite 增加的 P95 与 provider cost 在 M0 冻结的预算内。

## 9. M4：多语言 Cross-Encoder 重排

### 9.1 目标

使用查询与候选文本的联合相关性模型，对 Fusion 后的小规模候选进行排序，提高 Top-5 的相关性与顺序质量。

### 9.2 执行位置

```text
Structured/Qdrant Fusion → Top 20..30 → Cross-Encoder → Final Top 5..10
```

不要对 145,000 文档或数百个候选直接运行 Cross-Encoder。

### 9.3 Rerank 输入

每个商户构造有长度上限的 `MerchantRerankText`：

```text
name
category / subcategory
borough / neighborhood
source-backed attributes
business hours
price information when available
canonical evidence tags
top 1..2 representative evidence excerpts
```

原则：

- 合成评论必须保留 provenance，不得伪装成真实评价。
- 同一 review root 只允许一个 excerpt。
- 缺失字段保持缺失，不编造默认值。
- 输入截断策略必须确定且可测试。

### 9.4 Provider 与 fallback

```python
class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
    ) -> list[RerankScore]: ...
```

实现至少包括：

- `DisabledReranker`
- `HeuristicReranker`（当前逻辑，作为 fallback）
- `HttpCrossEncoderReranker` 或资源允许的本地实现

生产约束：

- 4 GB Lightsail 上默认不部署未经压测的大型本地模型。
- Reranker 必须支持 batch、并发上限、timeout 和 circuit breaker。
- Provider 失败时保留 M3 Fusion 顺序。
- Hard constraint filter 在 Reranker 前后都要验证；Cross-Encoder 无权恢复不合格候选。

### 9.5 分数组合

第一版不要直接相加未经校准的 Cross-Encoder 分数、rating、distance 和 RRF score。

推荐顺序：

1. 先执行 hard-constraint filter；
2. 使用 Cross-Encoder 产生主相关性顺序；
3. 仅在分数接近或完全相同时使用距离、rating 和品牌多样性 tie-break；
4. 如果后续要学习组合权重，必须使用 development set，并在 hidden test 上验证。

### 9.6 测试

- [ ] Reranker 提升相关候选顺序但不能引入 hard-constraint violation。
- [ ] Provider 返回缺失、重复或 NaN 分数时拒绝该批结果并 fallback。
- [ ] Timeout/circuit open 时保留 Fusion 顺序。
- [ ] 输入构建不会包含 security-test 文档或跨用户数据。
- [ ] 长 Evidence 能按确定规则截断。
- [ ] 结果可追踪到 reranker model/version 与输入文档 ID。

### 9.7 验收标准

- Precision@5、MRR 或 nDCG@5 相对 M3 有明确增益。
- Recall@10 和 hard-constraint satisfaction 不回归。
- P95、资源使用和 provider cost 满足 M0 Gate。
- 关闭 Reranker Feature Flag 后能立即恢复 M3 行为。

## 10. M5：生产可观测性、Shadow 与发布

### 10.1 Feature Flags

建议增加：

```text
NYC_REVIEW_AGENT_GLOBAL_RETRIEVAL_ENABLED=false
NYC_REVIEW_AGENT_QUERY_REWRITE_PROVIDER=disabled
NYC_REVIEW_AGENT_QUERY_REWRITE_MAX_QUERIES=3
NYC_REVIEW_AGENT_RERANKER_PROVIDER=disabled
NYC_REVIEW_AGENT_RERANKER_CANDIDATE_LIMIT=20
NYC_REVIEW_AGENT_RAG_SHADOW_ENABLED=false
NYC_REVIEW_AGENT_RAG_SHADOW_SAMPLE_RATE=0.0
```

所有开关都应出现在 health/config summary，但不得暴露密钥或完整内部 Prompt。

### 10.2 Trace 与 Metrics

每次 Run 至少记录：

```text
queryPlanVersion
rewriteProvider / rewriteCount / rewriteFallbackReason
embeddingProvider / model / dimensions / version
embeddingLatencyMs / embeddingCacheHit
structuredCandidates / globalCandidates / overlapCandidates
denseHits / sparseHits / fusionCandidates
rerankerProvider / rerankerCandidates / rerankerLatencyMs
retrievalFallbacks
finalCandidates
totalRetrievalLatencyMs
```

聚合指标：

- 各 Provider error/timeout/429 rate；
- Cache hit rate；
- Shadow 新旧结果 overlap@5；
- Structured-only 与 Qdrant-only 正确结果比例；
- Rewrite 和 Reranker 每次查询的平均调用成本；
- P50/P95/P99 分阶段延迟。

### 10.3 Shadow 发布

1. 旧 Pipeline 继续返回用户结果。
2. 对固定比例请求异步运行新 Pipeline，不触发任何写操作。
3. 只保存结构化差异与指标，不把 Shadow 结果返回前端。
4. 比较 overlap@5、hard-constraint violations、候选来源和延迟。
5. Shadow 异常不能影响主请求；资源不足时优先丢弃 Shadow。

### 10.4 Canary 发布

1. 内部/测试账户启用新 Pipeline。
2. 通过 Feature Flag 扩大到小比例普通 Run。
3. 观察至少一个完整发布窗口的错误率、P95、fallback 和质量抽样。
4. 达到 Gate 后全量启用。

回滚顺序：

```text
Disable Reranker
    ↓
Disable Multi-Query
    ↓
Disable Global Retrieval
    ↓
Switch back to previous Qdrant Collection
```

回滚不需要删除新 Collection，也不应修改已经冻结的 Eval 报告。

## 11. 故障模式与预期降级

| 故障 | 预期行为 | 用户可见结果 |
| --- | --- | --- |
| Embedding Provider timeout | 使用 Query Cache；无缓存时跳过 Dense | Structured + Sparse 结果，metadata 标记 fallback |
| Embedding 维度不匹配 | 启动/索引阶段直接失败，不切换 Collection | 旧版本继续服务 |
| Qdrant 不可用 | 使用 Spring Structured Retrieval | 推荐可能变弱，但 Run 不因检索完全失败 |
| Spring 检索不可用 | 仅在所有权限和数据版本校验通过时使用 Qdrant | 标记 structured fallback |
| Rewrite invalid JSON | 丢弃 Rewrite | Original + rule expansion |
| Rewrite 超时/限流 | 使用缓存或规则扩展 | 不阻塞主流程到无限时长 |
| Cross-Encoder timeout | 保留 Fusion 顺序 | 无 reranker 增益，但结果仍可验证 |
| Shadow 资源不足 | 丢弃 Shadow | 主请求不受影响 |
| 新 Collection 评测失败 | 禁止切换 | 旧 Collection 继续服务 |

## 12. 安全与数据边界

- Rewrite 只处理用户查询与结构化约束，不接收未经清洗的 RAG 文档作为指令。
- Evidence 继续标记 `untrusted_content`；Reranker 只能评分，不能调用工具或执行 Action。
- 所有检索必须携带 data version 与 dataset SHA filter。
- Prompt、Trace 和 Eval Report 不保存 API Key、原始 authorization token 或生产密钥。
- 用户 owner isolation 继续由 Run Store 与 Spring 登录用户共同保证。
- Security-test 文档在 Candidate Retrieval、Rerank Input 和 Evidence Selection 三个阶段均需排除。
- 外部 Provider 的数据发送范围必须在部署文档中说明；不能默认发送用户身份字段。

## 13. 测试矩阵

### 13.1 单元测试

- Embedding query/document prefix、batch、retry、cache、dimension validation
- Query Rewrite schema、constraint preservation、deduplication、fallback
- Merchant aggregation、RRF fusion、brand/document deduplication
- Rerank input construction、truncation、score validation、fallback
- Feature Flag 与 production hash-embedding guard

### 13.2 集成测试

- 新 Collection 全量构建与增量同步
- Qdrant global query + payload filters
- Structured/Qdrant 双路并发与单路故障
- Rewrite → multi-query retrieval → merchant fusion
- Cross-Encoder Provider contract
- Trace/metrics 字段完整性

### 13.3 回归与性能

- RAG v2 dev/test Eval
- 当前 P12 Eval 保留为历史兼容回归
- Agent workflow tests
- 100-run / 10-concurrency Agent soak
- 独立 Retrieval benchmark：cold/warm cache
- Provider timeout、429、5xx 与 network partition fault injection
- 4 GB Lightsail 资源边界下的 CPU、RAM、Qdrant 与 Agent P95 验证

## 14. 消融实验矩阵

| ID | Embedding | Candidate Retrieval | Query Expansion | Reranker | 目的 |
| --- | --- | --- | --- | --- | --- |
| A | Hash | Structured + candidate-filtered Qdrant | Rules | Heuristic | 当前基线 |
| B | Real multilingual | 同 A | Rules | Heuristic | 隔离 Embedding 增益 |
| C | Real multilingual | Structured + global Qdrant | Rules | Heuristic | 隔离全局召回增益 |
| D | Real multilingual | Structured + global Qdrant | Rules + Multi-Query | Heuristic | 隔离 Rewrite 增益 |
| E | Real multilingual | Structured + global Qdrant | Rules + Multi-Query | Cross-Encoder | 最终方案 |
| F | Real multilingual | Global Qdrant only | Rules + Multi-Query | Cross-Encoder | 衡量 Structured 分支价值，不作为默认生产方案 |

每份报告必须包含配置快照、Git SHA、数据集 SHA、Collection、模型版本和完整分组指标。

## 15. 建议提交顺序

每个提交保持可运行、可测试、可回退：

1. `test: add rag-v2 hard-negative evaluation schema and metrics`
2. `refactor: split query and document embedding contracts`
3. `feat: add production embedding metadata retries and cache`
4. `feat: add versioned qdrant collection build and validation`
5. `feat: add global merchant retrieval and structured fusion`
6. `feat: add constrained multi-query rewriting with fallback`
7. `feat: add optional cross-encoder reranking`
8. `feat: add rag shadow mode and stage metrics`
9. `docs: publish rag-v2 benchmark and rollout results`

不要把 Provider 接入、Collection 迁移、全局检索和 Reranker 放在同一个大提交中。

## 16. 粗略工期与依赖

以下为单人顺序开发的建议区间，不是交付承诺：

| 阶段 | 预计工作量 | 前置条件 |
| --- | --- | --- |
| M0 Eval v2 | 3–5 天 | 相关性标签策略与 hard-negative 设计；正式对外评测仍需人工 adjudication |
| M1 Embedding | 4–6 天 | Provider 凭据、模型候选与新 Collection 空间 |
| M2 Global Retrieval | 4–6 天 | M1 Collection 与 merchant aggregation contract |
| M3 Multi-Query | 3–5 天 | 模型 Provider、prompt/schema 评测 |
| M4 Cross-Encoder | 4–7 天 | Provider/模型选择、资源与延迟预算 |
| M5 Rollout | 3–5 天 | Shadow 流量、指标采集与生产变更窗口 |

合计约 4–6 周。若只做最有价值的第一批交付，优先完成 M0–M2。

## 17. Definition of Done

RAG v2 只有在满足以下条件后才算完成：

- [ ] 正式配置不再使用 Hash Embedding。
- [ ] Eval 报告记录真实 Embedding provider/model/dimensions/version。
- [ ] Qdrant 能在全局 scope 中恢复 Structured 分支漏掉的正确商户。
- [ ] Original、rule-expanded 和 rewritten queries 的贡献可以独立追踪。
- [ ] Cross-Encoder 失败不会让整个 Agent Run 失败。
- [ ] Security leakage、version mismatch 和 duplicate merchant 均为零。
- [ ] Hidden test 的 nDCG/Precision 有可复现增益，Recall 与 hard constraints 不回归。
- [ ] P95、资源和费用满足冻结 Gate。
- [ ] 新 Collection 已通过 Shadow 和 Canary，旧 Collection 可一键回滚。
- [ ] README、环境变量示例、部署文档和测试命令同步更新。
- [ ] 所有简历指标均能对应到已保存的机器可读报告。

## 18. 简历表述门禁

在 M0–M5 完成前，继续使用当前可验证表述，不提前写入 Cross-Encoder、LLM Multi-Query 或真实语义 Embedding。

最终可以在真实报告生成后使用以下模板：

```text
Developed global Qdrant hybrid retrieval with multilingual embeddings,
constrained LLM multi-query rewriting, RRF fusion, and Cross-Encoder reranking;
improved nDCG@10 by X points while maintaining Y% Recall@10 and Z ms P95
latency across N frozen bilingual evaluation queries.
```

`X`、`Y`、`Z`、`N` 必须从 RAG v2 hidden-test 报告自动读取，不能人工估算。
