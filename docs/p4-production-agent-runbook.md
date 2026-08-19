# P4 Production Agent Runbook

P4 把 P3 的可控执行闭环升级为可观测、可评测、可恢复的 Agent 工程，并将秒杀订单 MQ 从 Redis Stream 迁移为 RabbitMQ。Redis 仍负责缓存、登录态、库存预扣和生产侧待发布恢复，但不再承担订单消息消费。

## 1. 执行增量迁移

现有 `hmdp_new` 只需执行一次：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/p6_rabbitmq_profile_memory.sql
```

脚本新增 `tb_agent_user_memory`，使用 `CREATE TABLE IF NOT EXISTS`，不会清空 P3 的收藏、行程、提醒或 Action Audit。`p2_redis_stream_order.sql` 虽保留历史文件名，但 P4 仅继续使用其中的订单唯一键迁移。

## 2. 启动 RabbitMQ

手动启动开发环境时，RabbitMQ AMQP 默认地址为 `localhost:5672`：

```properties
HMDP_RABBITMQ_HOST=localhost
HMDP_RABBITMQ_PORT=5672
HMDP_RABBITMQ_USERNAME=guest
HMDP_RABBITMQ_PASSWORD=guest
```

确认 Broker 可用：

```bash
rabbitmq-diagnostics -q ping
```

如果使用 Homebrew 管理 RabbitMQ，可通过 `brew services start rabbitmq` 启动。Docker 是可选的一键环境，不是本地开发的必要条件。

## 3. RabbitMQ 秒杀可靠性

订单链路：

1. Lua 原子检查 Redis 库存与一人一单。
2. Lua 预扣库存，并写入 `seckill:pending:order:{orderId}` 和 ZSET 恢复索引。
3. Spring 发布持久化 JSON 消息到 `hmdp.voucher.order.exchange`，等待 correlated Publisher Confirm 与 return 检查。
4. Confirm 后移除 Redis 待发布记录；Broker 暂时不可用时定时任务会重新发布。
5. `hmdp.voucher.order.queue` 消费消息并在 MySQL 事务中扣减库存、创建订单。
6. 消费失败执行最多五次指数退避重试；仍失败的消息带异常头发布到 `hmdp.voucher.order.error.queue`。
7. 重复消息由订单 ID、一人一券唯一索引和事务回滚共同保证幂等。

RabbitMQ 只替换 MQ 角色。原有 React 手动秒杀入口、Redis Lua 原子校验和 MySQL 乐观扣库存仍然保留，Agent 仍然只能创建提醒。

## 4. Profile 用户资产

登录后调用：

```bash
curl -H 'authorization: 43996d90e8fb4b2b8112a911a0452d4a' \
  http://127.0.0.1:8081/profile/assets
```

响应包含：

- `favorites`：AI Guide 批准收藏的商铺
- `itineraries`：保存的行程、地点和预算估算
- `vouchers`：AI Guide 领取或用户手动购买的优惠券订单
- `reminders`：秒杀提醒
- `memories`：从已批准收藏推导的分类、街区和标签偏好

Profile 提供对应 Tabs。AI Memory 可以修改或删除；更新和删除均按当前登录用户隔离。商铺没有优惠券时，详情页不渲染 Voucher 区域；营业时间直接展示，不再提供展开按钮。

## 5. Agent Trace、恢复与安全

```bash
curl -H 'authorization: <current-user-token>' \
  http://127.0.0.1:8090/v1/agent/runs/<run-id>/trace

curl -H 'x-metrics-token: <metrics-token>' \
  http://127.0.0.1:8090/v1/agent/metrics
```

Trace 覆盖约束模型、用户偏好工具、每个 Agent Node、Action Planner、批准执行和 Run 总耗时。Metrics 聚合次数、失败、P50/P95 延迟和模型 Token。

Run Store 保存完整请求和尝试次数。Agent Service 重启时，只恢复尚未创建 Action 的只读阶段 Run；已经进入人工审批的操作不会自动执行。每个 Run 还有总超时，避免后台任务无限占用资源。

Run、SSE、Trace、取消和 Action API 均验证 owner key；owner key 是登录 token 的 SHA-256，不保存原始 token。创建接口有滑动窗口限流和 Prompt Guard；写工具仍由固定 Tool Catalog 与人工确认双重限制。

## 6. 自动质量门禁

```bash
cd agent-service
uv run python -m evals.run_eval --output .local/p4-eval-report.json
```

`evals/quality_gate.json` 约束 Multi Agent 的完成率、Verifier 通过率、约束匹配、引用覆盖、P95 延迟和 Trace 失败数。任一指标回退时命令以非零状态退出，可直接接入 CI。

## 7. 可选完整 Docker 环境

```bash
docker compose -f docker-compose.p4.yml up --build
```

在执行前停止占用 `3306`、`5672`、`6379`、`6333`、`8080`、`8081`、`8090` 和 `15672` 的本地服务。RabbitMQ 管理页为 `http://127.0.0.1:15672`。

## 8. 自动化验证

```bash
uv run --project agent-service ruff check agent-service/app agent-service/tests agent-service/evals
uv run --project agent-service pytest agent-service/tests -q
uv run --project agent-service python -m evals.run_eval
mvn clean -Dtest='!HmDianPingApplicationTests' test
cd hmdp-react && npm run build
docker compose -f docker-compose.p4.yml config --quiet
```
