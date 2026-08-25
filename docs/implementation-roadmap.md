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

## M7：大规模地图与空间聚合（已完成）

- 固定 NYC 2020 NTA `26b` polygon 和 SHA-256，使用 point-in-polygon 建立商户的官方 neighborhood 归属。
- `/shop/map` 按缩放级别返回 Borough、Neighborhood 或商户 Marker，支持多分类筛选、viewport 查询和高密度降级。
- React 地图在拖动与缩放后防抖请求，丢弃过期响应，并通过聚合钻取避免数千 Marker 同屏。
- 地图位置、聚合计数和导入审计均可从固定数据集重建。

## M8：Real-only 商户、分层评论与增量 RAG（已完成）

- 活动 Profile 切换为 `real-medium`：从固定 OpenStreetMap 快照选择 5,000 个可回溯商户身份，覆盖五区和六分类，`merchantIdentityMode=REAL_ONLY`、`mockShops=0`。
- 增加 `real-small`、`real-medium`、`real-large` 和 `real-load` 四档 Profile；来源快照、种子、shopId 与每个文件 SHA-256 均进入双清单门禁。
- 使用带文件页、作者和许可的 Wikimedia Commons 分类示意图；图片只作近似视觉素材，绝不声明为对应商户实景。
- 生成 100,000 条 depth-0 合成根评论、40,000 条一级回复和 12,500 条二级回复，覆盖 1–5 星、不同情感/主题和 RAG 安全样本；UI 展示线程层级与合成内容标签。
- P10 增加图片来源/许可表、评论线程字段，以及博客、博客评论和优惠券的 `source_type`；生成内容写为 `SYNTHETIC`，在线创建路径由服务端强制写为 `USER_SUBMITTED`，双语 UI 分开展示。
- Qdrant 改为流式批量增量同步：内容哈希未变化时跳过，只 upsert 变化文档，并在成功后删除当前版本陈旧文档；每棵评论线程组成一份证据。
- OpenStreetMap 未提供的价格与营业时间保持 `null`/unavailable；筛选、预算、Verifier 和 UI 不再用伪造值补齐。
- 生成、升级、全新库初始化和验收流程见 [P8 Real Data Runbook](p8-real-data-runbook.md)。

## M9：P2/P3 商户字段补全与图片升级（已完成代码与数据包）

- P11 新增来源匹配、字段观测和最终解析字段；电话、官网、预订、营业状态、评分数量、价格区间、卫生等级与更新时间均可独立解析。
- 增加 OSM、官方站点 JSON-LD、FSQ 本地快照、NYC DOHMH 和开放许可图片 Provider；抓取与确定性生成分离，CI 不访问网络。
- 图片采用“商户严格匹配开放许可图片 → 分类开放许可回退”，并保留独立 `image_credits.json`；产品 UI 只显示结果，不显示置信度或数据来源标签。
- Spring 列表、地图和 Agent Tool 排除非营业商户；详情页支持图片滑动、电话、官网、预订、价格区间和卫生等级。
- Agent Candidate、Itinerary 与 Verifier 使用解析后的字段和营业状态；本阶段不执行 P4 的 RAG 检索/排序升级。
- 已生成六分类、五区均衡的 360 家 Pilot；完整 5,000 家增强包由同一 pipeline 生成。最终 MySQL 导入和全量 Qdrant 重建按计划留到收尾阶段。
- 运行和验收流程见 [P2/P3 Enrichment Runbook](p2-p3-enrichment-runbook.md)。

### P9.1：列表排序语义修正（已完成）

- Distance 优先使用浏览器位置；拒绝或不支持定位时明确回退到 Times Square，不再把固定坐标伪装成用户距离。
- Distance 在 Redis GEO 中完成全局升/降序分页；Popularity 与 Rating 先对完整分类排序，再进行数据库分页，不再只重排最近的一小批商户。
- Popularity 改为评价量、内容点赞、销量、收藏和有效优惠券订单组成的可解释平台热度；Rating 保持独立，并用评价量和商户 ID 稳定处理同分。
- 排序定义、接口与双语验收步骤见 [P9.1 Shop Ranking Runbook](p9-ranking-runbook.md)。

### P10/P11：全量官网图片与真实字段（已完成，可进行阶段导入验收）

- 对 2,740 个已有官网的商户执行一次安全抓取，同时固定图片引用与 LocalBusiness JSON-LD，避免重复访问；图片仅保存远程引用，不缓存或重新分发原图。
- 全量包保持 5,000 个真实来源商户，展示图片覆盖 100%，其中 1,772 家（35.44%）具有商户专有图片；每家最终保留 1–3 张图。
- 外部评分从 0 增至 21 家、价格从 0 增至 152 家；电话覆盖 3,278 家、营业时间 2,831 家、预订链接 58 家。
- `nyc-real-v3-7577e407-m20260824` 已通过全量数据、来源、图片门禁和 5,000/5,000 NTA 地图投影验证；可按 Runbook 切换开发环境并逐页验收，旧数据库备份和 Qdrant 目录保留作回滚点。
- 复现步骤与校验值见 [P10/P11 Full Enrichment Runbook](p10-p11-full-enrichment-runbook.md)。

### P11.5：官网深层图片与菜单价格（已完成，可进行阶段导入验收）

- 在 P10/P11 首页抓取基础上增加同域菜单、图库、Location、服务/价格页和有限 Sitemap 抓取，并识别 `srcset`、懒加载、CSS 背景图与 PDF 菜单；图片仍只保存经安全和内容校验的远程引用。
- 全量处理 2,735 个可用官网与 6,570 个页面；官网图片覆盖 1,825 家，和严格匹配 Wikimedia 图片合并后共有 1,871 家商户使用专有图片，覆盖率由 35.44% 提升到 37.42%。
- 从官网 JSON-LD、菜单/服务网页和 48 份可解析 PDF 中获取价格分布；外部价格覆盖由 152 家提升到 918 家，其中 844 家的 `avgPriceCents` 由官网价格确定性派生，不再标为合成价格。
- 深层页面也带来少量附带字段增量：外部评分 22 家、电话 3,290 家、营业时间 2,837 家、预订链接 108 家；本阶段未引入付费评分 Provider。
- 新增 `p11-5` 管线阶段、`nyc-real-v4-*` 版本、P11 基线增量门禁、脏 URL 单站隔离和离线回归测试；5,000 家商户的 NTA 地图投影全部通过。
- 当前检查点是 `nyc-real-v4-0f51676d-m20260824`；生成、导入、Qdrant 隔离与验收步骤见 [P11.5 Runbook](p11-5-deep-content-runbook.md)。

### P12：混合检索与固定评测（已完成，可进行隔离索引验收）

- 不修改 P11.5 的 MySQL/Redis 数据，新增 `p12-rag-v1` 检索版本与 `hmdp_content_v2` Collection。
- 将商户身份/属性 FACT 与评论/博客 EVIDENCE 分层，新增中英文查询扩展、稠密+稀疏 RRF、候选池重排、证据去重和品牌多样性。
- Discovery 从最多 100 个结构化候选中选择最终 5 个；Preview、Run、Trace 与只读 MCP 使用同一检索链路。
- 固定 72 条中英文、六类别用例，并以 Recall@10、证据覆盖、约束满足、重复商户、注入泄漏、版本一致性和 P95 延迟作为门禁。
- 完整索引、评测、启动和未来新数据双基准方式见 [P12 RAG Quality Runbook](p12-rag-quality-runbook.md)。

## P13 已完成；后续 P14–P17

P10/P11/P11.5/P12/P13 已完成。P13 保持 5,000 家真实来源商户身份和 shop ID 不变，修复了“外部评分人数被显示为本地可浏览评论数”的数据契约，重构了评分、评论线程、笔记和笔记评论，并以免费官网/Wikimedia/NYC 来源继续提升图片和商户字段覆盖率。最终检查点为 `nyc-real-v5-8b645404-m20260824`；100,000 条根评论和 63,500 条回复通过重复、评分、计数与线程门禁，独立 P13 RAG 的 Recall@10 为 99.54%。完整导入与验收步骤见 [P13 5K 数据质量 Runbook](p13-data-quality-runbook.md)。后续按 P14 稳定性与性能、P15 Qdrant Server、P16 发布候选一致性与回滚、P17 项目包装推进；正式范围见 [P10–P17 Delivery Roadmap](p10-p17-roadmap.md)。
