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

RAG 至少索引以下内容：

- 带身份来源与内容来源的商户介绍。
- 以 depth-0 根评论为单位、包含 depth-1/depth-2 回复的商户评论线程。
- 探店博客与博客评论。

每个检索片段必须包含 `shopId`、内容类型、分类、区域、语言、创建时间、`dataVersion`、商户来源和内容来源等元数据。Agent Loader 必须读取博客、博客评论与评论自身的 `sourceType`，不得仅根据商户来源或内容类型硬编码；`nyc-real` seed 中缺少 `SYNTHETIC` 标记的生成内容必须失败关闭。Agent 输出中的主观结论必须包含可回溯引用，并明确说明引用评论是合成样本。用户内容一律作为不可信数据处理，评论中的指令不得覆盖系统指令。

P8 Qdrant 同步必须按批次流式处理并使用稳定文档 ID、内容哈希、数据版本与完整数据集 SHA-256：SHA 必须进入 payload、point ID、同步 scope 和检索 filter。未变化文档跳过，只 upsert 新增或变化文档；只有在本轮同步成功后才能删除当前数据集 scope 的陈旧文档。启动元数据必须报告 total、upserted、unchanged 与 deleted。

## 5. Read-only MCP

本地 coding agent harness 通过 Streamable HTTP MCP 复用相同的 Shop、RAG、Route 与 Verifier 服务。工具清单只能包含 `search_shops`、`get_shop_detail`、`get_shop_evidence`、`get_available_vouchers`、`calculate_route` 和 `validate_itinerary`。

MCP 不得发布收藏、保存行程、领券、提醒或秒杀写操作；秒杀仍只能由用户在传统 UI 手动发起。配置 `HMDP_AGENT_MCP_API_KEY` 时，无正确 Bearer key 的 MCP 请求必须返回 401。

## 6. 数据来源透明度

- 规模化 Mock 生成必须固定 Profile、种子、数据版本和 SHA-256。
- 公开来源商户必须有唯一外部 ID、来源名称、链接与抓取时间。
- P8 活动数据集必须声明 `merchantIdentityMode=REAL_ONLY`、`mockShops=0`，所有商户身份来自允许的公开来源，并覆盖五区和六个顶级分类；任何 Mock 或未知身份均导致启动失败。
- 商户身份来源与内容来源必须分开表达。真实商户名称和地址不能让合成描述、评论、评分、博客、优惠或平台活动看起来像公开来源或真实顾客内容。
- Wikimedia 图片必须包含文件页、作者、许可名称和许可链接，并在 UI 标为分类示意图；不得将近似图片表述为对应商户实景。
- 所有生成评论必须逐条标记 `SYNTHETIC`，包含有效的 root/parent/depth 关系；只有根评论带评分并计入商户评论数与平均分。
- 公开来源没有提供的价格与营业时间必须保持未知。筛选、预算、Verifier 和 UI 应返回 unavailable/unknown，不得生成确定值。
- 博客、博客评论、优惠和其他平台内容如果为生成内容，必须在 JSON、MySQL、Spring API、Agent payload 和 UI 中逐层保留 `SYNTHETIC` 标记。
- 在线用户创建博客、博客评论或其他内容时，来源只能由服务端写为 `USER_SUBMITTED`；客户端提交的 `sourceType` 不得覆盖该值。UI 必须用双语标签区分 `SYNTHETIC`、`USER_SUBMITTED` 与兼容的 legacy 内容。
- Spring、Agent、Qdrant 和 MCP 返回的同一商户必须保持一致的 `dataVersion` 与来源元数据。
- 数据质量门禁必须覆盖五区、六分类、主外键、商户身份唯一性、来源计数、图片许可、评论线程完整性和字段长度。

## 完成定义

完整演示必须同时通过以下两条路径：

1. 用户在 NYC 地图和店铺页浏览来源可回溯的真实身份商户，能够识别示意图片与合成评论，并手动参加秒杀；后端通过 Lua 和可靠异步订单链路完成处理。
2. 用户在 AI 工作台提出多约束请求；多 Agent 调用领域工具和增量 RAG，返回带内容来源标记的候选方案、可用时的预算及路线，并在用户确认后执行保存行程或领取普通优惠券等可审计操作。
