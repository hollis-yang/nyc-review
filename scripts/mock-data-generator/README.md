# NYC Mock Data Generator

生成可重复的 NYC 本地生活 Mock 数据。生成器只写入显式指定的输出目录，不连接 MySQL、Redis 或模型服务，因此生成动作本身不会修改正在运行的环境。

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile small \
  --output /tmp/hmdp-nyc-small
```

支持的 Profile：

- `small`：36 家商户，用于单元测试和 Testcontainers。
- `demo`：250 家商户，用于产品演示和 Agent Eval。
- `load`：20,000 家商户，用于按需压测，不应提交生成结果。

默认随机种子为 `20260817`。输出中的 `manifest.json` 记录 Profile、种子、数据版本、记录数量和每个文件的 SHA-256，可用于确认导入数据是否一致。

除业务 JSON 外，生成器还会输出：

- `mysql_import.sql`：首次运行时把当前传统业务表归档为 `legacy_hangzhou_tb_*`，然后事务化替换为 NYC 数据。重复导入同一数据集是安全的。
- `redis_seed.resp`：清理本项目的旧 GEO、缓存、Feed、点赞和秒杀派生键，重建 `shop:geo:*` 与 `seckill:stock:*`。它不执行 `FLUSHDB`，也不删除翻译缓存。
- `import_manifest.json`：记录 MySQL、Redis、Qdrant 共用的 shopId 列表、shopId SHA-256 与数据集 SHA-256。

应用迁移和导入包前必须停止 Spring Boot 与 Agent Service，并确认当前连接的是可替换数据的开发数据库：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/p4_nyc_domain.sql
mysql -u root -p hmdp_new < data/generated/nyc-small/mysql_import.sql
redis-cli --pipe < data/generated/nyc-small/redis_seed.resp
```

完整的首次初始化、验证查询和故障排查见 [P1 NYC 数据 Runbook](../../docs/p1-nyc-data-runbook.md)。

数据中的商户、用户、商户评论、博客、博客嵌套评论和优惠活动均为虚构内容。评论中会有少量带 `security_test` 标记的 Prompt Injection 样本，用于验证 RAG 不会把用户内容当作系统指令。
