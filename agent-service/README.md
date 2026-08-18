# HM Dianping Agent Service

FastAPI + LangGraph 服务，负责单 Agent/多 Agent 编排、RAG、人工审批和 Eval。Spring Boot 仍是业务事实来源；本服务不得直连业务表执行任意查询或写入。

## 本地运行

```bash
cd agent-service
uv sync --dev
uv run uvicorn app.main:app --reload --port 8090
```

```bash
curl http://127.0.0.1:8090/health
```

默认使用只读的 Mock Adapter、离线约束解析器和 SQLite Run Store，方便无外部依赖地验证工作流。生产环境必须设置 `HMDP_AGENT_ADAPTER=http` 并配置后端服务地址。

## P2 Run API 与 SSE

产品入口只需要自然语言，不再要求前端手工填写结构化约束：

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -H 'authorization: <current-user-token>' \
  -d '{"mode":"multi","query":"Quiet vegan dinner in Midtown for 2 under $120"}'
```

使用响应中的 `run_id` 读取实时协作事件和最终快照：

```bash
curl -N http://127.0.0.1:8090/v1/agent/runs/<run-id>/events
curl -sS http://127.0.0.1:8090/v1/agent/runs/<run-id>
```

Run、事件与最终结果默认持久化到 `./.local/agent-runs.sqlite3`。接口同时支持 `single` 和 `multi`；多 Agent 仍由 Supervisor、Discovery、Evidence、Itinerary、Verifier 协作，Evidence 与 Itinerary 并行。

## P3 人工审批执行

推荐完成后，Agent Service 会持久化可选 action proposal，并将 Run 暂停为 `waiting_confirmation`。用户可逐项批准、拒绝或重试；批准后由 Spring 的受限 action endpoint 执行，并以 `actionId` 保证幂等。收藏偏好可补全后续未指定的分类或街区，Run 历史按登录 token 的不可逆 SHA-256 隔离。

```bash
curl -X POST /v1/agent/runs/<run-id>/actions/<action-id>/approve \
  -H 'authorization: <current-user-token>'
curl -X POST /v1/agent/runs/<run-id>/actions/<action-id>/reject
curl -H 'authorization: <current-user-token>' '/v1/agent/runs?limit=5'
curl /v1/agent/metrics
```

前端产品入口只暴露 Multi Agent；Single Agent 继续保留在 Eval 中用于质量和延迟对照。完整步骤见 [P3 Runbook](../docs/p3-agent-actions-runbook.md)。

## DeepSeek 模型网关

默认 `HMDP_AGENT_MODEL_PROVIDER=heuristic`，可离线运行。启用 DeepSeek：

```bash
HMDP_AGENT_MODEL_PROVIDER=deepseek \
DEEPSEEK_API_KEY=<your-key> \
DEEPSEEK_MODEL=deepseek-chat \
uv run uvicorn app.main:app --port 8090
```

也可使用 `HMDP_AGENT_MODEL_API_KEY`、`HMDP_AGENT_MODEL_NAME` 与 `HMDP_AGENT_MODEL_BASE_URL` 独立配置。模型失败时默认回退离线解析器，并在结果 `metadata.modelFallbackUsed` 中标记；设置 `HMDP_AGENT_MODEL_FALLBACK_TO_HEURISTIC=false` 可改为直接失败。

## 使用真实 Qdrant RAG 路径

先在仓库根目录生成纽约小型数据集：

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile small \
  --output data/generated/nyc-small
```

然后在 `agent-service` 目录启动。下面使用 Qdrant 本地持久化模式；若已有 Qdrant Server，可把 `HMDP_AGENT_QDRANT_LOCATION` 改成服务 URL。

```bash
HMDP_AGENT_RAG_ADAPTER=qdrant \
HMDP_AGENT_QDRANT_LOCATION=./.local/qdrant \
HMDP_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-small \
uv run uvicorn app.main:app --reload --port 8090
```

启动时会校验 `import_manifest.json` 与 `shops.json` 的 shopId 和 `dataVersion`，随后用商户介绍、商户评论、博客、顶层评论和嵌套评论完整重建目标 Qdrant Collection。Spring 候选商户带有相同的 `dataVersion`，检索时还会按该版本过滤，避免旧索引与新数据库串数据。默认 Hash Embedding 只用于离线开发；部署时使用 `.env.example` 中的 OpenAI-compatible Embedding 配置。

接入 Spring Boot Tool API 时再增加：

```bash
HMDP_AGENT_ADAPTER=http \
HMDP_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
HMDP_AGENT_BACKEND_AUTH_TOKEN=<current-user-token>
```

## 安全边界

- 只读检索工具可由 Agent 自动调用。
- 收藏、保存行程、领取普通优惠券和创建秒杀提醒必须经过人工审批。
- `seckill_voucher` 不在模型 Tool Catalog 中；用户手动秒杀由 React 直接调用 Spring Boot。
- RAG 返回的评论和博客必须标记为不可信内容，并携带可回溯引用。

## Eval

同一份用例对比 Single/Multi 的约束解析、合法商户 ID、引用覆盖率、Verifier 与延迟：

```bash
uv run python -m evals.run_eval
```
