# P3 可控执行 Agent Runbook

P3 将 P2 的只读推荐升级为需要人工确认的执行闭环：标准标签归一化、近似结果解释、个性化偏好、Run 历史、审批/拒绝/重试、Spring 幂等写入和 MySQL 审计。AI Guide 只提供多 Agent 产品入口；Single Agent 仅保留在离线 Eval 中作为工程基线。

## 1. 执行 P3 数据库迁移

在现有 `hmdp_new` 上执行一次：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/p5_agent_actions.sql
```

迁移新增：

- `tb_shop_favorite`
- `tb_saved_itinerary`
- `tb_seckill_reminder`
- `tb_agent_action_audit`

脚本使用 `CREATE TABLE IF NOT EXISTS`，重复执行不会清空已有数据。

## 2. 启动服务

Spring 和 Agent Service 沿用 P2 配置。Agent Service 必须使用 HTTP Adapter，批准操作才能进入 Spring：

```bash
cd agent-service
HMDP_AGENT_ADAPTER=http \
HMDP_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
HMDP_AGENT_RAG_ADAPTER=qdrant \
HMDP_AGENT_QDRANT_LOCATION=./.local/qdrant \
HMDP_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-small \
HMDP_AGENT_MODEL_PROVIDER=deepseek \
uv run uvicorn app.main:app --port 8090
```

前端登录 token 会按请求透传，不需要把个人 token 固化到 Agent Service 环境变量。

## 3. 验证暂停、审批与恢复

创建多 Agent Run：

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -H 'authorization: <current-user-token>' \
  -d '{"mode":"multi","query":"Dinner in Midtown for 2 under $120"}'
```

推荐完成后，Snapshot 状态应为 `waiting_confirmation`，`actions` 中会出现收藏、保存行程，以及候选商户存在对应券时的普通券领取或秒杀提醒。

```bash
curl -sS http://127.0.0.1:8090/v1/agent/runs/<run-id> \
  -H 'authorization: <current-user-token>'
```

批准或拒绝单项操作：

```bash
curl -sS -X POST \
  http://127.0.0.1:8090/v1/agent/runs/<run-id>/actions/<action-id>/approve \
  -H 'authorization: <current-user-token>'

curl -sS -X POST \
  http://127.0.0.1:8090/v1/agent/runs/<run-id>/actions/<action-id>/reject \
  -H 'authorization: <current-user-token>'
```

相同 `actionId` 重复批准不会重复写入。失败操作保留 `failed` 状态，并可以在 UI 中重试。所有提案处理完后 Run 转为 `completed`。

秒杀边界保持不变：Agent 只能创建提醒，`seckill_voucher` 不在模型 Tool Catalog，实际秒杀仍由用户在商户页面手动发起。

## 4. 历史、个性化和指标

已登录用户的 Run 历史按 token 的 SHA-256 隔离：

```bash
curl -sS 'http://127.0.0.1:8090/v1/agent/runs?limit=5' \
  -H 'authorization: <current-user-token>'
```

批准收藏后，Spring 会根据收藏商户统计偏好。后续未明确分类或街区的请求会使用这些偏好补全约束，并在结果 `metadata.personalization` 中说明。

本地运行指标：

```bash
curl -sS http://127.0.0.1:8090/v1/agent/metrics
```

指标包含各状态 Run 数、审批操作状态数和事件总量。

## 5. 双语与 DeepSeek 翻译

默认语言为英语。进入 `Profile → Edit Profile → Language` 可切换到中文，选择会保存在浏览器本地。

- 英语模式隐藏 DeepSeek 翻译入口。
- 中文模式显示博客、评论和 AI Prompt 的 DeepSeek 翻译入口。
- 中文内容页会翻译到中文；AI Prompt 可翻译到英文后再提交。

## 6. Docker Compose

确认 `data/generated/nyc-small` 已生成并在根目录 `.env` 配置 DeepSeek 后：

```bash
docker compose -f docker-compose.p3.yml up --build
```

入口：React `8080`、Spring `8081`、Agent `8090`、Qdrant `6333`。首次创建 MySQL Volume 时会依次执行基础 schema、P1 迁移、P3 action migration 和 NYC mock 数据导入。

## 7. 自动化验证

```bash
uv run --project agent-service ruff check agent-service/app agent-service/tests agent-service/evals
uv run --project agent-service pytest agent-service/tests -q
uv run --project agent-service python -m evals.run_eval
mvn clean -Dtest='!HmDianPingApplicationTests' test
cd hmdp-react && npm run build
```
