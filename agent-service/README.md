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

默认使用只读的 Mock Adapter，方便在 Java Tool API 完成前验证工作流。生产环境必须设置 `HMDP_AGENT_ADAPTER=http` 并配置后端服务地址。

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

启动时会把商户介绍、商户评论、博客、顶层评论和嵌套评论写入 Qdrant。默认 Hash Embedding 只用于离线开发；部署时使用 `.env.example` 中的 OpenAI-compatible Embedding 配置。

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
