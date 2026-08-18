# 实施路线

## M1：NYC 传统业务系统

- 建立可重复的 NYC Mock 数据生成器。
- 保留六个顶级商户分类，并使用子分类和标签表达细粒度属性。
- 将地图、货币、距离、时区和地区选择切换到 NYC。
- 保留博客、评论、关注、Feed、点赞、签到和翻译。
- 将秒杀订单升级为 Redis Stream，保留用户手动秒杀。

## M2：类型安全的 Agent Tool 层

- 新增独立 Agent API DTO，不向模型暴露通用 `Result<Object>` 或数据库接口。
- 为每个工具定义 JSON Schema、权限、超时、重试、幂等和审批策略。
- 在不连接模型的情况下完成工具集成测试。

## M3：单 Agent 与 RAG

- 建立 FastAPI Agent Service、模型抽象、SSE 和 Run 持久化。
- 索引商户介绍、评论和博客，返回可回溯引用。
- 建立单 Agent Eval 基线。

## M4：多 Agent

- 实现 Supervisor、Discovery、Evidence、Itinerary 和 Verifier。
- Evidence 与 Itinerary 并行执行。
- 与单 Agent 使用相同 Eval 对比准确率、延迟和费用。

## M5：Action、AgentOps 和 MCP

- 实现普通优惠券领取、收藏、行程保存和秒杀提醒的人工审批。
- 实现 Trace、重放、Eval Dashboard、Prompt/模型版本管理。
- 对只读领域能力增加 MCP Server；秒杀操作不进入 MCP。
