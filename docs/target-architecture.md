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
        +--> Qdrant：商户内容与合成评论线程向量索引
        +--> SQLite Trace Store：模型、Agent、Tool 和 Action Trace
        |
        | 类型安全 OpenAPI
        v
Spring Boot Business Backend
  - 用户、商户、博客、评论、关注
  - 优惠券、手动秒杀、订单
  - MySQL、Redis、Redisson、Lua、RabbitMQ

Local Coding Agent Harness
        |
        | Streamable HTTP MCP（仅六个只读领域工具）
        v
Python Agent Service
```

Spring Boot 是业务事实来源。Agent 不允许直连业务数据库，也不允许获得任意 SQL 或任意 HTTP 工具。Python Agent Service 只通过带用户身份和权限范围的领域 Tool API 访问业务能力。

MCP Server 复用相同的 Shop、RAG、Route 和 Verifier 服务。它只发布表格中的六个查询/计算工具；所有写操作继续由产品 UI 人工审批或手动执行。

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

- `nyc-small` / `nyc-demo`：稳定的全 Mock 测试与历史演示数据。
- `nyc-medium-hybrid`：P6 历史 Profile；2,000 家商户中仅一部分餐厅身份来自 NYC Open Data。
- `nyc-real-small`：12 家公开来源商户与 60 条合成根评论，用于快速 P8 契约测试。
- `nyc-real-medium`：当前活动 Profile；5,000 家公开来源商户、100,000 条合成根评论及 52,500 条分层回复。
- `nyc-real-large`：10,000 家公开来源商户与 200,000 条合成根评论，用于扩展验证。
- `nyc-real-load`：15,000 家公开来源商户与 300,000 条合成根评论，用于按需压测。
- 活动数据库仅保留 NYC 数据；历史杭州快照不再由导入器创建，也不参与运行时或验收。

Mock 数据使用固定随机种子生成。`nyc-hybrid-v1` 作为历史兼容数据保留；当前 `nyc-real-v1` 从固定 OpenStreetMap/Overpass 快照选择全部商户身份，任何 Mock 身份都会被数据验证器和 Agent 启动门禁拒绝。`dataVersion` 绑定 real-data Profile、OSM 快照 SHA-256 与随机种子，`manifest.json` 和 `import_manifest.json` 再固定每个文件、shopId 和导入包哈希。

P8 对 provenance 使用两层契约：

- Merchant provenance：名称、地址、坐标、Borough、NTA、分类映射、OSM 标签、外部 ID、来源链接和抓取时间。
- Content provenance：描述、图片、评论线程、博客、博客评论、优惠和其他平台行为分别声明来源。Wikimedia 图片只是带许可的分类示意图；seed 评论、评分、博客和优惠都是 `SYNTHETIC`。在线创建的博客和评论由服务端强制标为 `USER_SUBMITTED`，不得信任客户端传入的来源字段。

公开来源没有提供的价格与营业时间保持 `null`。DTO、筛选、预算计算和 Verifier 必须传播 unknown/unavailable，不允许在任何服务层用默认价格或营业时段掩盖缺失值。真实商户身份也不能让合成评论看起来像真实顾客评价。

Qdrant 索引采用稳定文档 ID、`dataVersion`、数据集 SHA-256 和内容哈希。完整数据集 SHA 同时进入 payload、point ID、同步 scope 与检索 filter，因此即使两个包意外复用版本和数字 ID，也不能交叉返回证据。Loader 流式产生商户介绍、评论线程、博客与博客评论文档，并从每条记录读取内容来源；`nyc-real` seed 不是显式 `SYNTHETIC` 时拒绝索引。Store 按配置批次比较哈希并 upsert 变化项；成功完成后才清理当前数据版本的陈旧 ID。该过程避免每次启动清空 Collection，并允许通过 total、upserted、unchanged、deleted 指标审计同步结果。

Eval 使用隐藏于 Agent 上下文之外的 Ground Truth，从而准确测量约束满足率、合法商户 ID 比例、引用正确率和动作安全性。
