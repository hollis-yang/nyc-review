# 实施路线

## M1：NYC 传统业务系统

- 已建立可重复的 NYC Mock 数据生成器与 MySQL/Redis 导入包。
- 已保留六个顶级商户分类，并使用子分类、标签和结构化营业时间表达细粒度属性。
- 已提供杭州旧数据一次性归档、NYC 活动数据替换和导入审计记录。
- 已让 Spring Tool API 与 Qdrant 使用相同的 shopId、`dataVersion` 和数据集清单。
- 将地图、货币、距离、时区和地区选择切换到 NYC。
- 保留博客、评论、关注、Feed、点赞、签到和翻译。
- 已将秒杀 MQ 迁移为 RabbitMQ，保留 Redis Lua 预扣、用户手动秒杀、Publisher Confirm、重放和错误队列。

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

- 已实现普通优惠券领取、收藏、行程保存和秒杀提醒的人工审批。
- 已实现 Trace、重放、自动 Eval Gate、Prompt Guard 和模型版本记录；Dashboard 作为后续可视化增强。
- 已对六个只读领域能力增加 Streamable HTTP MCP Server；收藏、领券、保存、提醒和秒杀操作均不进入 MCP。

## M6：规模化数据与真实来源

- 新增 2,000 家商户的 `medium` Profile，保留固定随机种子、导入清单和全文件 SHA-256。
- 接入 NYC Open Data 的 DOHMH 餐厅公开数据快照，按 CAMIS 去重并覆盖纽约五区。
- 真实数据仅用于商户名称、地址、行政区、坐标和菜系；评论、博客、价格、评分、标签、营业时间、图片与优惠继续使用合成数据并明确披露。
- 来源元数据贯穿 MySQL、Spring Tool API、Agent Candidate、Qdrant payload、MCP 和中英文页面。
- 增加数据质量门禁，校验五区覆盖、引用完整性、外部 ID 唯一性与来源计数。
