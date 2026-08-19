# 目标架构

## 服务边界

```text
React / TypeScript
  - NYC 地图、传统业务页面
  - AI 对话、Agent 步骤、引用、审批
        |
        | REST + SSE
        v
Python Agent Service
  - FastAPI
  - LangGraph 单 Agent / 多 Agent 工作流
  - RAG、Checkpoint、Eval
        |
        | 类型安全 OpenAPI；后续增加 MCP
        v
Spring Boot Business Backend
  - 用户、商户、博客、评论、关注
  - 优惠券、手动秒杀、订单
  - MySQL、Redis、Redisson、Lua、RabbitMQ
        |
        +--> Qdrant：评论和博客向量索引
        +--> SQLite Trace Store：模型、Agent、Tool 和 Action Trace
```

Spring Boot 是业务事实来源。Agent 不允许直连业务数据库，也不允许获得任意 SQL 或任意 HTTP 工具。Python Agent Service 只通过带用户身份和权限范围的领域 Tool API 访问业务能力。

## Agent 工作流

```text
Supervisor
    |
    v
Discovery
    |
    +-------------------+
    |                   |
    v                   v
Evidence            Itinerary
    |                   |
    +---------+---------+
              |
              v
           Verifier
              |
              v
          Supervisor
              |
              v
       Human confirmation
              |
              v
        Restricted Action
```

Agent 之间只交换结构化对象：`UserConstraints`、`CandidateSet`、`EvidencePack`、`ItineraryDraft` 和 `VerificationReport`。子 Agent 不共享完整用户对话历史。

## 工具权限

| 工具 | 类型 | Agent 自动执行 | 用户确认 |
| --- | --- | --- | --- |
| `search_shops` | 查询 | 是 | 否 |
| `get_shop_detail` | 查询 | 是 | 否 |
| `get_shop_evidence` | 查询/RAG | 是 | 否 |
| `get_available_vouchers` | 查询 | 是 | 否 |
| `calculate_route` | 计算 | 是 | 否 |
| `validate_itinerary` | 计算 | 是 | 否 |
| `favorite_shop` | 可撤销写入 | 否 | 是 |
| `save_itinerary` | 可撤销写入 | 否 | 是 |
| `claim_standard_voucher` | 有限写入 | 否 | 是 |
| `create_seckill_reminder` | 可撤销写入 | 否 | 是 |
| `seckill_voucher` | 手动专用 | 不暴露 | 用户在传统 UI 手动点击 |

## 数据集策略

- `nyc-small`：稳定的小型测试数据。
- `nyc-demo`：默认演示数据。
- `nyc-load`：压测时按需生成，不提交大文件。
- 杭州数据保留为 legacy 数据集，迁移过程不覆盖或删除。

Mock 数据使用固定随机种子生成。Eval 使用隐藏于 Agent 上下文之外的 Ground Truth，从而准确测量约束满足率、合法商户 ID 比例、引用正确率和动作安全性。
