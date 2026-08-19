# NYC AI 全栈改造验收标准

本文档定义本项目改造过程中不可回退的四项能力。任何阶段性重构都必须通过这些验收条件。

## 1. 原有后端核心能力

以下能力必须继续可用，并通过自动化测试覆盖：

- 用户手动参与普通优惠券购买和秒杀活动。
- 秒杀资格与库存通过 Redis Lua 原子校验。
- 秒杀订单通过 RabbitMQ 可靠异步落库；必须包含 Publisher Confirm、生产侧待发布恢复、消费重试、幂等消费和独立错误队列。
- Redis GEO 附近商户查询。
- 店铺缓存以及缓存穿透、击穿、雪崩保护。
- Redis ZSet 点赞、热门排序和关注 Feed。
- Redis Set 关注关系与共同关注。
- Redis Bitmap 用户签到。
- Redisson 分布式锁、Redis ID Worker 和 MySQL 事务一致性。

秒杀规则：LLM 不进入秒杀请求关键路径。用户必须在前端手动点击秒杀按钮，React 直接调用后端秒杀 API。Agent 只允许查询活动、解释规则、创建提醒和跳转到秒杀页面。

## 2. 翻译功能

以下兼容接口必须保留：

- `POST /translate/blog`
- `POST /translate/comment`
- `POST /translate/shop`

模型访问后续可以迁移到统一 `ModelGateway`，但接口语义、Redis 翻译缓存和中英文页面能力不得删除。模型服务不可用时，业务 API 应返回受控错误，不得影响非 AI 核心功能。

## 3. 多 Agent

最终系统必须包含实际运行的多 Agent 工作流，而不是仅在架构图中声明：

- `SupervisorAgent`：解析请求、分派任务、汇总结果。
- `DiscoveryAgent`：调用结构化商户查询工具。
- `EvidenceAgent`：检索评论、博客和商户证据。
- `ItineraryAgent`：计算预算、营业时间、距离和路线。
- `VerifierAgent`：验证商户 ID、预算、时间和引用。

`EvidenceAgent` 与 `ItineraryAgent` 在获得候选商户后并行执行。系统必须支持 `single` 和 `multi` 两种运行模式，并使用同一套 Eval 数据比较质量、延迟和成本。

## 4. RAG

RAG 至少索引以下第一方 Mock 内容：

- 商户介绍。
- 商户评论。
- 探店博客。
- 嵌套评论。

每个检索片段必须包含 `shopId`、内容类型、分类、区域、语言、创建时间等元数据。Agent 输出中的主观结论必须包含可回溯引用。用户内容一律作为不可信数据处理，评论中的指令不得覆盖系统指令。

## 5. Read-only MCP

本地 coding agent harness 通过 Streamable HTTP MCP 复用相同的 Shop、RAG、Route 与 Verifier 服务。工具清单只能包含 `search_shops`、`get_shop_detail`、`get_shop_evidence`、`get_available_vouchers`、`calculate_route` 和 `validate_itinerary`。

MCP 不得发布收藏、保存行程、领券、提醒或秒杀写操作；秒杀仍只能由用户在传统 UI 手动发起。配置 `HMDP_AGENT_MCP_API_KEY` 时，无正确 Bearer key 的 MCP 请求必须返回 401。

## 完成定义

完整演示必须同时通过以下两条路径：

1. 用户在 NYC 地图和店铺页浏览商户，并手动参加秒杀；后端通过 Lua 和可靠异步订单链路完成处理。
2. 用户在 AI 工作台提出多约束请求；多 Agent 调用领域工具和 RAG，返回带引用的候选方案、预算及路线，并在用户确认后执行保存行程或领取普通优惠券等可审计操作。
