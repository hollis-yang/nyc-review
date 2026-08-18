# NYC Mock Data Generator

生成可重复的 NYC 本地生活 Mock 数据。生成器只写入显式指定的输出目录，不连接 MySQL、Redis 或模型服务。

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

数据中的商户、用户、商户评论、博客、博客嵌套评论和优惠活动均为虚构内容。评论中会有少量带 `security_test` 标记的 Prompt Injection 样本，用于验证 RAG 不会把用户内容当作系统指令。
