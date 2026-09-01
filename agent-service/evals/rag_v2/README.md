# RAG Eval v2（M0 基线 + M1 Embedding + M2 全局召回 + M3 Multi-Query）

该目录是在不修改 P12 冻结套件的前提下，为 RAG 优化建立的可复现基线。它评测当前真实链路：

```text
structured candidate search
→ candidate-filtered Qdrant Dense + Sparse RRF
→ heuristic multi-signal ranking
→ evidence retrieval
```

M0 冻结了 Hash/64 基线；M1 在不改变 Query Rewrite、候选范围和 reranking 的前提下，只比较真实 Embedding；M2 用显式 feature flag 隔离 candidate-filtered control 与 global-hybrid treatment；M3 再隔离受约束的 LLM Multi-Query。Cross-Encoder 仍未实现，CLI 会继续拒绝非 disabled 的 learned reranker 配置。

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

## M1 实际结果（2026-08-31）

三套真实 Embedding 索引均完整构建为 145,000 点、1024 维 Dense Cosine + Sparse IDF Collection，15 个 payload index 与 embedding identity 校验通过，最终 Qdrant 状态均为 `green / optimizer ok`。所有 Provider 请求为 0 retry、0 failure。机器可读的冻结摘要见 [`m1_results.json`](./m1_results.json)；含逐 case 结果和一次性 receipt 的原始报告保留在忽略提交的 `.local/` 中，并由摘要记录 SHA-256。

双语指标按 30 条中文与 10 条 mixed Dev case 等权到 case 加权；Hash 门槛为 nDCG@10 `>= 0.77924925`、MRR@10 `>= 0.91958350`：

| Profile | Overall nDCG@10 | Overall MRR@10 | 双语 nDCG@10 | 双语 MRR@10 | Embedding P95 | 完整 M1 估算费用 | 结果 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `openai-small-1024` | 77.56% | 92.19% | 77.24% | 90.42% | 320.78 ms | $0.2013 | 两项未过线 |
| `openai-large-1024` | 77.88% | 91.82% | 77.84% | 91.98% | 299.34 ms | $1.3081 | nDCG 差 0.081pp |
| `qwen37-1024` | 77.82% | 93.28% | 78.48% | 92.81% | 735.43 ms | $0.9035 | 唯一 Dev winner |

费用包含各 profile 的独立预检与完整索引/Dev；Qwen 还包含唯一一次 Test holdout 查询。三者合计使用 33,032,295 tokens，按 2026-08-31 冻结单价估算 `$2.4129`。这是基于 Provider 实报 token 的工程估算，不是账单；OpenAI 与 DashScope 各 `$5` 的用户报告余额均足够。

Qwen 的唯一一次 policy holdout 已完成并封存，但质量门禁失败，因此不得晋级生产：

| Test 指标 | Hash | Qwen | Delta | Gate |
| --- | ---: | ---: | ---: | --- |
| Recall@10 | 71.11% | 69.91% | -1.20pp | 最多下降 0.50pp，失败 |
| nDCG@10 | 79.36% | 78.97% | -0.39pp | 通过 |
| MRR@10 | 92.50% | 93.65% | +1.15pp | 通过 |
| 中文 nDCG@10 | 81.02% | 79.77% | -1.25pp | 最多下降 1.00pp，失败 |

Holdout 同时保持 100% evidence coverage、0 security leakage、0 version mismatch、0 citation mismatch，且直接复用 Dev Collection（`upserted=0`、`unchanged=145000`）。结论是工程实现和模型实验完成，但 active Embedding 保持不变；`qwen37-1024` 只作为 M2 全局召回实验候选。不得根据本次 Test case 调参或重跑，下一次晋级必须使用新的 hidden holdout。

## M2：全局候选召回的有限标注契约

M1 的 judgment 只完整覆盖 structured candidate pool。直接用它评测全局检索会把 Qdrant-only 商户错误地默认为 `relevance=0`。M2 因此采用可复现的两阶段协议：

1. 用冻结的 M1 Dev query、Qwen winner index 和固定 treatment 配置，先融合最多 30 个商户，再通过与 control 相同的 heuristic multi-signal ranker 捕获每例最终 Top-K；
2. Builder 只对“本次 capture 实际返回的 structured branch external IDs + treatment Top-K”并集按同一 attribute policy 标注；
3. control 与 treatment 都使用生成的 schema-v3 suite。任何最终返回但不在有限并集内的商户都会 fail-closed，要求重新捕获和构建，不会自动判 0。

该策略每例最多新增 `candidateLimit`（当前为 10）个 judgment，避免无边界的 `80 × 5,000` 全语料笛卡尔标注。suite contract 会记录 structured、Qdrant-only、总 judgment pair 数和避免的 Cartesian pair 数，并绑定 candidate-universe fixture、配置、源码、语料、Embedding identity 与 index manifest 指纹。

先完整捕获 Dev treatment；`--global-retrieval-mode` 与 `--global-retrieval-enabled` 必须同时出现：

```bash
uv run --env-file ../.env python -m evals.rag_v2.run_eval \
  --split dev \
  --embedding-profile qwen37-1024 \
  --qdrant-location http://127.0.0.1:6333 \
  --collection nyc_review_content_v3_dashscope_qwen37_1024_v1 \
  --index-action reuse \
  --index-manifest .local/rag-v2-remote-index-bf6ad011a2118add-65530477dcfe.json \
  --discovery-pool-size 30 \
  --fusion-pool-limit 30 \
  --candidate-limit 10 \
  --warmup-cases 1 \
  --global-retrieval-mode global-hybrid \
  --global-retrieval-enabled \
  --candidate-universe-output .local/m2-candidate-universe.json \
  --output .local/m2-capture-report.json
```

捕获必须是 80/80 完整运行、复用既有 M1 index，且不允许 branch/ranking fallback、incomplete hydration、identity conflict/mismatch、rejected payload 或 `--limit-cases`。随后在隔离目录生成 suite；命令会同时复制 adversarial fixture，并拒绝覆盖已有产物：

```bash
uv run python -m evals.rag_v2.build_m2_cases \
  --candidate-universe .local/m2-candidate-universe.json \
  --output-directory .local/m2-suite
```

先跑 candidate-filtered control，再跑唯一变量为全局召回开关的 treatment：

```bash
uv run --env-file ../.env python -m evals.rag_v2.run_eval \
  --split dev \
  --cases .local/m2-suite/cases.m2.dev.json \
  --quality-gate evals/rag_v2/m2_quality_gate.json \
  --embedding-profile qwen37-1024 \
  --qdrant-location http://127.0.0.1:6333 \
  --collection nyc_review_content_v3_dashscope_qwen37_1024_v1 \
  --index-action reuse \
  --index-manifest .local/rag-v2-remote-index-bf6ad011a2118add-65530477dcfe.json \
  --discovery-pool-size 30 \
  --fusion-pool-limit 30 \
  --candidate-limit 10 \
  --warmup-cases 1 \
  --output .local/m2-control.json

uv run --env-file ../.env python -m evals.rag_v2.run_eval \
  --split dev \
  --cases .local/m2-suite/cases.m2.dev.json \
  --quality-gate evals/rag_v2/m2_quality_gate.json \
  --embedding-profile qwen37-1024 \
  --qdrant-location http://127.0.0.1:6333 \
  --collection nyc_review_content_v3_dashscope_qwen37_1024_v1 \
  --index-action reuse \
  --index-manifest .local/rag-v2-remote-index-bf6ad011a2118add-65530477dcfe.json \
  --discovery-pool-size 30 \
  --fusion-pool-limit 30 \
  --candidate-limit 10 \
  --warmup-cases 1 \
  --global-retrieval-mode global-hybrid \
  --global-retrieval-enabled \
  --baseline-report .local/m2-control.json \
  --output .local/m2-treatment.json

uv run python -m evals.rag_v2.compare_m2 \
  .local/m2-control.json .local/m2-treatment.json \
  --output .local/m2-comparison.json
```

Paired gate 要求 Recall@10 不下降、nDCG@10 至少提升 0.5pp、至少救回一个 binary-relevant structured miss，同时约束 Precision/MRR/中文 nDCG、hard negative、完整性错误、Provider 请求/token 与 Total P95（不超过 control 的 1.25 倍）。报告原生记录 structured/global dense/global sparse/aggregation/hydration/fusion/total 阶段耗时、分支可用性、去重、身份冲突、hard-filter 与 structured-miss rescue 指标。

### M2 Dev 结果（2026-09-01）

最终冻结产物位于 `evals/rag_v2/m2/`，机器可读摘要见 `m2_results.json`。80 条 Dev query 使用 structured pool 30、fusion pool 30、Top-10 和既有 145,000-point Qwen index；索引为纯复用，未生成任何 document embedding。

| 指标 | Control | Global Hybrid | 变化 |
| --- | ---: | ---: | ---: |
| Recall@10 | 61.18% | 64.94% | +3.76pp |
| Precision@5 | 83.25% | 87.25% | +4.00pp |
| nDCG@10 | 78.30% | 82.98% | +4.68pp |
| MRR@10 | 92.23% | 96.67% | +4.44pp |
| 中文 nDCG@10 | 76.43% | 81.38% | +4.94pp |
| Hard constraint satisfaction | 94.25% | 100.00% | +5.75pp |
| Total P95 | 1.100s | 1.065s | 0.968× |

Treatment 恢复了 10/10 个 eligible case、20/20 个 binary-relevant structured miss；hard-constraint violation 从 46 降至 0，hard-negative return 从 12 降至 0。每次运行的 80 条评分样本使用 80 个 Provider 请求、4,380 query token，另有 1 条 warm-up 使用 1 个请求、57 tokens；capture/control/treatment 三次正式流程合计 243 个请求、13,311 tokens，估算费用 `$0.00093177`。独立 `compare_m2` gate 通过，且显式执行了 P95 ratio 检查；单臂 treatment 中因 feature profile 不同而出现的 latency warning 不代表 paired comparison 被跳过。

该结论仅适用于 deterministic bounded-union Dev evaluation。由于 treatment Top-K 参与 judgment pool，存在 selection leakage，不能据此直接晋级生产；必须新建未参与开发的 hidden holdout。生产 Compose 继续将 Global Retrieval 固定为关闭。

当前 Provider cost cap 是 **per-run** 保护，不会跨 capture/control/treatment 自动合并；M2 实测时必须把三份报告的 Provider token 与估算费用另行累计记录。Qwen index sidecar 的累计 ledger 只约束 build/resume，复用索引的查询费用不应误算为已被该 ledger 覆盖。

`cases.test.json` 的 M1 policy holdout 已经消费且在 M2 CLI/Builder 中永久封存；不得用于 capture、调参或晋级。M2 完成 Dev 决策后必须另建新的 hidden holdout。生产 Compose 的全局召回 flag 在完整 M2 晋级前保持关闭。

## M3：受约束的 LLM Multi-Query

M3 在 M2 global-hybrid 两臂都开启的前提下，仅切换 Query Rewrite。原始查询、确定性中英规则扩展和最多 3 条通过严格 JSON Schema 的 LLM rewrite 各自执行 Dense + Sparse 检索，再在 merchant level 做 query-variant RRF。模型必须逐字段回显已解析的 hard constraints，并保留 required/excluded tags；不一致、无效 JSON、429、超时或 Provider 错误在在线路径降级为 rules-only，而正式 Eval 在第一条 fallback 或不完整 variant 时立即终止。

5 条 query variant 使用一次 Qwen query batch，并把结果写入既有 LRU cache；它只改变在线查询调度，不改变文档 transform，因此 145,000-point M1 index 的源码指纹仍保持 `40b101d1...`，本阶段没有重建文档向量。批处理失败只执行一次 Sparse-only 降级，不会扩散成 5 次付费重试。

正式协议使用两次完整 capture 构建有界 schema-v4 Dev suite，再运行 paired control/treatment：

```bash
# 1. 对冻结 M2 Dev suite 分别运行 --m3-capture-arm control/treatment。
#    两臂都显式开启 global-hybrid；treatment 额外设置：
--query-rewrite-provider openai \
--query-rewrite-model gpt-4o-mini-2024-07-18 \
--query-rewrite-max-queries 3 \
--query-rewrite-input-price-usd-per-million-tokens 0.15 \
--query-rewrite-output-price-usd-per-million-tokens 0.60

# 2. 构建只覆盖实际 Structured + 两臂 Top-K 并集的 Dev suite。
uv run python -m evals.rag_v2.build_m3_cases \
  --source-suite evals/rag_v2/m2/cases.m2.dev.json \
  --control-report .local/m3-capture-control.json \
  --treatment-report .local/m3-capture-treatment.json \
  --output-directory .local/m3-suite

# 3. 在 cases.m3.dev.json 上运行相同的 control/treatment 配置并比较。
uv run python -m evals.rag_v2.compare_m3 \
  .local/m3-control.json .local/m3-treatment.json \
  --output .local/m3-comparison.json
```

### M3 Dev 结果（2026-09-01）

冻结 suite 位于 `evals/rag_v2/m3/`，机器可读摘要见 `m3_results.json`。80 条 query、1,569 个有界 judgment pair 中有 4 个 treatment-only pair，且全部为 binary relevant；该 pooled Dev suite 同样存在 selection leakage，不能替代 hidden holdout。

| 指标 | M2 control | M3 Multi-Query | 变化 |
| --- | ---: | ---: | ---: |
| Recall@10 | 64.82% | 69.03% | +4.21pp |
| Precision@5 | 87.00% | 93.50% | +6.50pp |
| nDCG@10 | 83.01% | 91.65% | +8.64pp |
| MRR@10 | 96.67% | 98.75% | +2.08pp |
| 中文 nDCG@10 | 81.38% | 90.36% | +8.98pp |
| 词典外 Recall@10 | 42.31% | 48.53% | +6.22pp |
| 词典外 nDCG@10 | 72.06% | 90.45% | +18.39pp |
| Total P95 | 1.008s | 4.959s | 4.920× |

质量、安全、完整性、请求、token 与费用子门禁全部通过：hard-constraint satisfaction 和 evidence coverage 均为 100%，security/version/citation mismatch、hard-negative、重复 merchant、第 3 个同品牌结果、rewrite fallback、Provider retry/failure 均为 0。规则已覆盖子集 nDCG 只变化 `-0.0133pp`，否定表达 nDCG 提升 `18.81pp`。

批处理将 treatment 的 Qwen 网络请求从首轮的 468 降至 147，较 control 只增加 67，低于 +320 上限；最终 capture + formal 协议的 OpenAI rewrite 与 Qwen query 估算费用合计 `$0.05784`，没有产生 document embedding 成本。但 Total P95 的冻结上限是 1.25×，最终实测为 4.920×；独立 comparator 因此只保留一项失败并拒绝晋级。生产 Compose 继续固定关闭 Global Retrieval 与 Query Rewrite，后续必须换用显著更低延迟的 rewrite provider/本地模型并通过同一 gate，再建立新的 hidden holdout。

## 指标和报告

质量指标包括 Recall@5/10、Precision@5、nDCG@5/10、MRR@10、硬约束满足率、证据覆盖率、未标注率、hard-negative final-return rate，以及 citation owner、merchant identity、source、security、data version 和 dataset SHA 完整性。品牌指标分为从同品牌第 2 个结果起计算的 `duplicateBrandRate`，以及只惩罚第 3 个及以后结果的 `excessiveBrandRate`。

报告输出 overall、`en`、`zh`、`mixed` 和 7 个 scenario 分组。语言分组使用不同 intent，只是 observational slice，不能把差异归因于语言本身；未来需要同一 intent 的成对翻译集才能做受控多语言比较。聚合使用未四舍五入的 query-level macro mean，最终序列化才保留 6 位小数。P50/P95/P99 采用 nearest-rank percentile。

当前能够可靠测量的阶段为：

- Structured Search、Candidate Ranking、Evidence Retrieval 和 Total：Eval 外层 wall clock；
- Embedding：记录 logical query/document calls、Provider HTTP requests、cache hit、token、retry、failure、总时长和按冻结单价估算的费用；索引与查询 usage 分开保存。

M0/M1 历史报告仍无法从旧接口拆分 Query Planning、Qdrant 与 Fusion；M2/M3 的统一 Candidate Discovery 接口会直接暴露 global dense/sparse、Embedding、merchant aggregation、hydration、fusion 与 rewrite timing，不使用总时长差值伪造阶段耗时。Learned reranker 仍为 disabled。正式 M1–M3 Eval 对 Provider、rewrite/retrieval fallback、variant failure 与未标注商户 fail-closed；在线 Runtime 才允许带 metadata 的受控降级。

## M0 Hash/64 本地基线

冻结配置为 P13 full、145,000 文档、Hash v1/64 维、rules-v1、candidate-filtered retrieval、heuristic multi-signal ranking、Top 10、sequential local-disk Qdrant。隔离索引首次构建 145,000 条文档用时 102.28s，精确数值、报告 SHA 和源码指纹见 `baseline.hash64.local.json`；brand 与 hard-negative 字段均由最终 full report 原生输出。

| Split | Recall@10 | Precision@5 | nDCG@10 | MRR@10 | Hard constraints | Evidence | P95 total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dev | 59.10% | 80.00% | 75.44% | 89.66% | 94.63% | 100% | 6.33 s |
| Policy holdout | 71.11% | 82.00% | 79.36% | 92.50% | 95.63% | 100% | 8.71 s |

两个 split 的 security leakage、version/source/owner mismatch、未标注结果、重复 merchant ID 与第 3 个及以后同品牌集中均为 0。dev/test 分别有 14/16 个 hard negative 出现在最终结果中，macro return rate 为 2.50%/2.99%；同品牌第 2 个分店分别出现 3/4 次。硬约束没有达到路线图的 99% 目标，原因被定位到 `hours_time_boundary`：当前 `GeneratedNycShopToolService` 接受 `visit_time`，但尚未用营业时间过滤候选。M0 将它保留为显式能力缺口，而不是放宽或删除测试。

相同配置完整重复运行 dev 后，`overall/byLanguage/byScenario/integrity/requestCounts` 逐字段零差异，证明质量结果可复现；但 P95 从 6.33s 波动到 9.39s（1.483×），因此 1.25× 相对延迟门禁如实失败。M0 不事后放宽阈值，本地延迟只保留为观测值。

本地 Qdrant 对 145k collection 有明确性能警告；即使完整 `latencyProfileFingerprint` 相同，本次重复也证明 local-disk 噪声不足以支撑正式性能门禁，生产 P95 必须在 Qdrant Server 上重新冻结。所有最终报告对应 Git `6f152772e15be80624396598d83afc453919074c`，14 个 agent/eval source 文件均为 clean，scoped digest 为 `4ba10cd0...`；全仓库 dirty 仅来自并行 session 的 `nyc-review-web` 文件，manifest 已明确区分两者。
