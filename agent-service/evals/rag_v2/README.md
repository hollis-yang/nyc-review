# RAG Eval v2（M0 基线 + M1 Embedding 实验）

该目录是在不修改 P12 冻结套件的前提下，为 RAG 优化建立的可复现基线。它评测当前真实链路：

```text
structured candidate search
→ candidate-filtered Qdrant Dense + Sparse RRF
→ heuristic multi-signal ranking
→ evidence retrieval
```

M0 冻结了 Hash/64 基线；M1 在不改变 Query Rewrite、候选范围和 reranking 的前提下，只比较真实 Embedding。全局候选召回、LLM Query Rewrite 和 Cross-Encoder 仍未实现，CLI 会对这些未实现配置 fail-fast。

## 冻结数据契约

- `cases.dev.json`：80 条，可用于开发与调参；40 英文、30 中文、10 中英混合。
- `cases.test.json`：80 条 policy holdout；语言分布相同，不得用于调参。文件已提交到仓库，因此不是真正的秘密测试集。
- 两个 split 的 `intentGroup` 和 query 无重叠，但不是 merchant-disjoint：共有 12 个 judged merchant、其中 9 个 binary-relevant merchant 重叠。因此 test 是 policy holdout，而不是独立商户测试集。
- 每个 split 固定包含 30 条 semantic alias/composition、12 条预算边界、10 条营业时间边界、8 条无障碍硬约束、8 条否定表达、6 条 branch/geo isolation 和 6 条拼写或口语噪声用例。`out_of_dictionary_paraphrase` 表示来自面向 OOD 设计的 phrase bank，不保证当前规则完全无法识别；semantic 场景中，dev 有 14/14/2 条分别识别 0/1/2 个目标 tag，test 为 15/14/1。
- `judgments` 完整覆盖业务层实际返回的 structured candidate pool；未标注返回率必须为 0。
- 每个 split 有 466 个 pipeline-level hard negatives，其中 60 个位于 structured candidate pool。最终 `hardNegativeReturnRate` 同时反映 structured filtering 与 ranking 泄漏，不能解释为纯 reranker benchmark。
- `adversarial_documents.json` 提供旧数据版本、安全评论和安全博客评论 fixture，用于隔离 Qdrant 回归测试。

相关性等级固定为：

- `3`：满足全部硬约束和两个语义偏好；
- `2`：满足全部硬约束并命中一个语义偏好；
- `1`：满足硬约束但没有命中语义偏好，是合法 fallback；
- `0`：违反至少一个硬约束。

Recall、Precision 和 MRR 以 `relevance >= 2` 作为二值相关阈值；Precision@5 固定以 5 为分母，nDCG 使用 `2^relevance - 1` 增益。重复 merchant 只在第一次出现时获得相关性增益，但重复位置仍占排名，避免通过重复结果刷高指标。

这些标签由冻结的 P13 merchant attributes 确定性生成，`labelSource=deterministic-derived-merchant-attributes`，不是人工标注。正式对外声称“人工评测集”前仍需独立 adjudication。

## 生成与校验

从 `agent-service` 目录运行：

```bash
uv run python -m evals.rag_v2.build_cases
uv run pytest tests/test_rag_v2_eval.py tests/test_p12_retrieval.py
```

Builder 绑定 `data/generated/nyc-real-p13-full` 的 `dataVersion` 与 `datasetSha256`。Runner 会重算 manifest 声明的每个 corpus 文件 SHA，并校验 case SHA、覆盖顶层阈值/allowlist/fixture 的 suite contract SHA、完整 adversarial fixture contract SHA、语言配额、相关性等级和 hard negatives；任何 corpus 或评测契约漂移都会被拒绝。

## M0 冻结基线

首次创建或同步隔离索引时不要传 `--reuse-index`：

```bash
uv run python -m evals.rag_v2.run_eval \
  --split dev \
  --qdrant-location ./.local/qdrant-rag-v2-m0-final \
  --collection hmdp_content_v2 \
  --output ./.local/rag-v2-dev.json
```

同步成功后会在 Qdrant 路径旁写入脱敏的 index sidecar manifest。它绑定 corpus、embedding、document-transform 源码指纹、Dense Cosine/Sparse IDF schema，以及远端模式下的 endpoint fingerprint。后续运行（包括 Hash provider）必须严格匹配；point count 和维度不足以证明索引身份：

```bash
uv run python -m evals.rag_v2.run_eval \
  --split dev \
  --reuse-index \
  --qdrant-location ./.local/qdrant-rag-v2-m0-final \
  --collection hmdp_content_v2 \
  --output ./.local/rag-v2-dev.json \
  --summary-output ./.local/rag-v2-dev-summary.json
```

对新配置做回归比较时可直接传入仓库内的冻结 baseline manifest，也可传同一 split 的完整报告：

```bash
uv run python -m evals.rag_v2.run_eval \
  --split dev \
  --reuse-index \
  --qdrant-location ./.local/qdrant-rag-v2-m0-final \
  --collection hmdp_content_v2 \
  --baseline-report evals/rag_v2/baseline.hash64.local.json \
  --output ./.local/rag-v2-candidate.json
```

M0 报告和索引身份保留为历史证据。M1 修改了 document transform 与 payload identity，因此不能把旧 Hash collection 冒充新源码构建的索引复用。

## M1：三模型、低费用安全运行

M1 冻结了三个 1024 维 profile；低层参数与 profile 冲突时直接拒绝：

| Profile | 模型 | API | 单次构建硬上限 |
| --- | --- | --- | ---: |
| `openai-small-1024` | `text-embedding-3-small` | OpenAI | $0.50 |
| `openai-large-1024` | `text-embedding-3-large` | OpenAI | $2.25 |
| `qwen37-1024` | `qwen3.7-text-embedding` | DashScope Native | $1.25 |

Qwen 使用 `text_type=document/query` 且只请求 `dense`，继续共用现有 lexical sparse，避免同时改变两条检索分支。Adapter 会把文档自动拆成最多 20 条/请求。三个上限合计只授权 OpenAI $2.75、Qwen $1.25；Provider 实报 token 达到上限时停止后续请求。

真实模型必须使用 Qdrant Server。先在仓库根目录启动对齐 Python Client 的 Server；持久卷不可用 `down -v` 删除：

```bash
docker compose -f compose.local.yml up -d qdrant
```

每个模型先做只读取语料、调用少量文档与查询、但不创建 Collection 的预检：

```bash
uv run --env-file ../.env python -m evals.rag_v2.run_eval \
  --embedding-profile openai-small-1024 \
  --qdrant-location http://127.0.0.1:6333 \
  --preflight-only \
  --output .local/m1-openai-small-preflight.json
```

把 profile 依次替换为 `openai-large-1024`、`qwen37-1024`。报告使用 Provider 返回的 token/100-document minhash sample 与 15% 安全余量估算全库；预估超过 profile 上限时，在任何索引写入前退出。

预检通过后串行构建，禁止三个模型并行：

```bash
uv run --env-file ../.env python -m evals.rag_v2.run_eval \
  --split dev \
  --embedding-profile openai-small-1024 \
  --qdrant-location http://127.0.0.1:6333 \
  --index-action build \
  --allow-paid-index-build \
  --baseline-report evals/rag_v2/baseline.hash64.local.json \
  --output .local/m1-openai-small-dev.json
```

Runner 会先原子写入 `state=building` sidecar，再开始付费调用；中断后使用完全相同的命令并把 `build` 改为 `resume`。Resume 只接受完全一致的 corpus、Embedding identity、源码指纹、Collection 和 endpoint，并从累计 token 预算中扣除先前尝试；已经成功 upsert 的内容通过 `content_sha256` 跳过。只有精确 145,000 点、Dense Cosine/Sparse IDF、15 个 payload indexes、identity filter、可见性探针和 Qdrant optimizer readiness 全部通过后，manifest 才切为 `state=complete`；`indexed_vectors_count` 仅作为近似观测值，不参与完成判定。

三个完整 Dev 报告产生后，应用预先冻结的 winner policy：

```bash
uv run python -m evals.rag_v2.compare_m1 \
  .local/m1-openai-small-dev.json \
  .local/m1-openai-large-dev.json \
  .local/m1-qwen37-dev.json \
  --output .local/m1-winner.json
```

Policy 会从 80 条 result rows 重算指标，并要求三个报告完整、绑定 committed baseline/gate SHA、通过相对门禁、无 fallback、同一 suite/control/source、索引 ready，且中英双语 nDCG@10 与 MRR@10 均比 Hash baseline 至少提升 0.5pp。主指标是 30 条中文与 10 条 mixed case 按用例数加权的 nDCG@10；候选间差距不超过 0.5pp 时，依次比较 overall nDCG、双语 MRR、费用、Embedding P95 和 profile ID，并输出固定种子的 paired bootstrap 区间。

Policy holdout 只能由 winner 运行一次，且拒绝覆盖已有输出：

```bash
uv run --env-file ../.env python -m evals.rag_v2.run_eval \
  --split test \
  --embedding-profile <winner-profile> \
  --qdrant-location http://127.0.0.1:6333 \
  --index-action reuse \
  --winner-manifest .local/m1-winner.json \
  --allow-policy-holdout \
  --baseline-report evals/rag_v2/baseline.hash64.local.json \
  --output .local/m1-winner-test.json
```

Runner 会再次核对 winner 的 Embedding、Dev retrieval/runtime、Collection、Qdrant endpoint 和 policy artifact SHA，并在第一条 holdout query 前原子创建不可重复的 attempt receipt；成功或失败都会封存该次尝试。

`--limit-cases` 只缩短查询评测，绝不会缩短索引。为防止把它误当成低费用 smoke，付费 `build/resume` 与 `--limit-cases` 的组合会被拒绝。

## 指标和报告

质量指标包括 Recall@5/10、Precision@5、nDCG@5/10、MRR@10、硬约束满足率、证据覆盖率、未标注率、hard-negative final-return rate，以及 citation owner、merchant identity、source、security、data version 和 dataset SHA 完整性。品牌指标分为从同品牌第 2 个结果起计算的 `duplicateBrandRate`，以及只惩罚第 3 个及以后结果的 `excessiveBrandRate`。

报告输出 overall、`en`、`zh`、`mixed` 和 7 个 scenario 分组。语言分组使用不同 intent，只是 observational slice，不能把差异归因于语言本身；未来需要同一 intent 的成对翻译集才能做受控多语言比较。聚合使用未四舍五入的 query-level macro mean，最终序列化才保留 6 位小数。P50/P95/P99 采用 nearest-rank percentile。

当前能够可靠测量的阶段为：

- Structured Search、Candidate Ranking、Evidence Retrieval 和 Total：Eval 外层 wall clock；
- Embedding：记录 logical query/document calls、Provider HTTP requests、cache hit、token、retry、failure、总时长和按冻结单价估算的费用；索引与查询 usage 分开保存。

Query Planning、Qdrant、Fusion 暂时无法从现有服务接口中独立拆分；Rewrite、Global Retrieval 和 learned Reranker 尚未实现。这些字段在报告的 `stageAvailability` 中明确为 unavailable/disabled，不会用差值伪造耗时。正式 M1 Eval 对 Provider 错误 fail-closed；在线 Runtime 才允许带 metadata 的 sparse-only fallback。

## M0 Hash/64 本地基线

冻结配置为 P13 full、145,000 文档、Hash v1/64 维、rules-v1、candidate-filtered retrieval、heuristic multi-signal ranking、Top 10、sequential local-disk Qdrant。隔离索引首次构建 145,000 条文档用时 102.28s，精确数值、报告 SHA 和源码指纹见 `baseline.hash64.local.json`；brand 与 hard-negative 字段均由最终 full report 原生输出。

| Split | Recall@10 | Precision@5 | nDCG@10 | MRR@10 | Hard constraints | Evidence | P95 total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dev | 59.10% | 80.00% | 75.44% | 89.66% | 94.63% | 100% | 6.33 s |
| Policy holdout | 71.11% | 82.00% | 79.36% | 92.50% | 95.63% | 100% | 8.71 s |

两个 split 的 security leakage、version/source/owner mismatch、未标注结果、重复 merchant ID 与第 3 个及以后同品牌集中均为 0。dev/test 分别有 14/16 个 hard negative 出现在最终结果中，macro return rate 为 2.50%/2.99%；同品牌第 2 个分店分别出现 3/4 次。硬约束没有达到路线图的 99% 目标，原因被定位到 `hours_time_boundary`：当前 `GeneratedNycShopToolService` 接受 `visit_time`，但尚未用营业时间过滤候选。M0 将它保留为显式能力缺口，而不是放宽或删除测试。

相同配置完整重复运行 dev 后，`overall/byLanguage/byScenario/integrity/requestCounts` 逐字段零差异，证明质量结果可复现；但 P95 从 6.33s 波动到 9.39s（1.483×），因此 1.25× 相对延迟门禁如实失败。M0 不事后放宽阈值，本地延迟只保留为观测值。

本地 Qdrant 对 145k collection 有明确性能警告；即使完整 `latencyProfileFingerprint` 相同，本次重复也证明 local-disk 噪声不足以支撑正式性能门禁，生产 P95 必须在 Qdrant Server 上重新冻结。所有最终报告对应 Git `6f152772e15be80624396598d83afc453919074c`，14 个 agent/eval source 文件均为 clean，scoped digest 为 `4ba10cd0...`；全仓库 dirty 仅来自并行 session 的 `nyc-review-web` 文件，manifest 已明确区分两者。
