# RAG Eval v2（M0）

该目录是在不修改 P12 冻结套件的前提下，为 RAG 优化建立的可复现基线。它评测当前真实链路：

```text
structured candidate search
→ candidate-filtered Qdrant Dense + Sparse RRF
→ heuristic multi-signal ranking
→ evidence retrieval
```

M0 不实现真实多语言 Embedding、LLM Query Rewrite、全局候选召回或 Cross-Encoder；CLI 会记录这些配置，并对尚未实现的启用值 fail-fast，避免报告与实际运行不一致。

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

## 运行基线

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

正式冻结候选方案后才运行一次 `--split test`。`--limit-cases` 只用于 smoke test；部分运行会输出指标，但不会执行质量门禁，也会被 baseline loader 明确拒绝。Baseline 必须是完整、case count 匹配、带 latency profile 且通过自身门禁的 full/summary report，或仓库内 compact manifest。

## 指标和报告

质量指标包括 Recall@5/10、Precision@5、nDCG@5/10、MRR@10、硬约束满足率、证据覆盖率、未标注率、hard-negative final-return rate，以及 citation owner、merchant identity、source、security、data version 和 dataset SHA 完整性。品牌指标分为从同品牌第 2 个结果起计算的 `duplicateBrandRate`，以及只惩罚第 3 个及以后结果的 `excessiveBrandRate`。

报告输出 overall、`en`、`zh`、`mixed` 和 7 个 scenario 分组。语言分组使用不同 intent，只是 observational slice，不能把差异归因于语言本身；未来需要同一 intent 的成对翻译集才能做受控多语言比较。聚合使用未四舍五入的 query-level macro mean，最终序列化才保留 6 位小数。P50/P95/P99 采用 nearest-rank percentile。

当前能够可靠测量的阶段为：

- Structured Search、Candidate Ranking、Evidence Retrieval 和 Total：Eval 外层 wall clock；
- Embedding：Eval-only wrapper 记录请求数、文本数和总时长。

Query Planning、Qdrant、Fusion 暂时无法从现有服务接口中独立拆分；Rewrite、Global Retrieval 和 learned Reranker 尚未实现。这些字段在报告的 `stageAvailability` 中明确为 unavailable/disabled，不会用差值伪造耗时。Provider token/cost metadata 当前也不可获得，写为 `null`。

## M0 Hash/64 本地基线

冻结配置为 P13 full、145,000 文档、Hash v1/64 维、rules-v1、candidate-filtered retrieval、heuristic multi-signal ranking、Top 10、sequential local-disk Qdrant。隔离索引首次构建 145,000 条文档用时 102.28s，精确数值、报告 SHA 和源码指纹见 `baseline.hash64.local.json`；brand 与 hard-negative 字段均由最终 full report 原生输出。

| Split | Recall@10 | Precision@5 | nDCG@10 | MRR@10 | Hard constraints | Evidence | P95 total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dev | 59.10% | 80.00% | 75.44% | 89.66% | 94.63% | 100% | 6.33 s |
| Policy holdout | 71.11% | 82.00% | 79.36% | 92.50% | 95.63% | 100% | 8.71 s |

两个 split 的 security leakage、version/source/owner mismatch、未标注结果、重复 merchant ID 与第 3 个及以后同品牌集中均为 0。dev/test 分别有 14/16 个 hard negative 出现在最终结果中，macro return rate 为 2.50%/2.99%；同品牌第 2 个分店分别出现 3/4 次。硬约束没有达到路线图的 99% 目标，原因被定位到 `hours_time_boundary`：当前 `GeneratedNycShopToolService` 接受 `visit_time`，但尚未用营业时间过滤候选。M0 将它保留为显式能力缺口，而不是放宽或删除测试。

相同配置完整重复运行 dev 后，`overall/byLanguage/byScenario/integrity/requestCounts` 逐字段零差异，证明质量结果可复现；但 P95 从 6.33s 波动到 9.39s（1.483×），因此 1.25× 相对延迟门禁如实失败。M0 不事后放宽阈值，本地延迟只保留为观测值。

本地 Qdrant 对 145k collection 有明确性能警告；即使完整 `latencyProfileFingerprint` 相同，本次重复也证明 local-disk 噪声不足以支撑正式性能门禁，生产 P95 必须在 Qdrant Server 上重新冻结。所有最终报告对应 Git `6f152772e15be80624396598d83afc453919074c`，14 个 agent/eval source 文件均为 clean，scoped digest 为 `4ba10cd0...`；全仓库 dirty 仅来自并行 session 的 `nyc-review-web` 文件，manifest 已明确区分两者。
