# P5 Read-only MCP Runbook

P5 把现有 NYC 领域能力接入本地 coding agent harness。MCP Server 位于 Agent Service，不直连 MySQL，也不创建第二套业务逻辑。

## 1. 数据与类别图标迁移

已有数据库执行一次幂等迁移，并清理 Shop Type 的 Redis 缓存：

```bash
mysql -u root -p nyc_review < src/main/resources/db/p7_p5_mcp_ui.sql
redis-cli DEL cache:shopType:list
```

新建数据库直接导入最新生成的 `data/generated/nyc-small/mysql_import.sql` 即可。

## 2. 启动 Spring 与 Agent Service

Spring 的受限 Tool API 仍需要当前有效的后端登录 token。MCP 使用独立服务密钥，二者不要混用：

```bash
cd agent-service
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>' \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=./.local/qdrant \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-small \
NYC_REVIEW_AGENT_MCP_API_KEY='<local-mcp-key>' \
uv run uvicorn app.main:app --port 8090
```

`GET /health` 的 `mcp` 应为 `enabled`。MCP 地址为 `http://127.0.0.1:8090/mcp`。

## 3. Coding Agent Harness 配置

不同 harness 的配置文件名不同，核心参数相同：

```json
{
  "mcpServers": {
    "nyc-review-nyc": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8090/mcp",
      "headers": {
        "Authorization": "Bearer <local-mcp-key>"
      }
    }
  }
}
```

不要把真实 key 提交到仓库。未设置 `NYC_REVIEW_AGENT_MCP_API_KEY` 时，仅适合本机无鉴权开发。

## 4. 协议级验证

下面客户端会完成 MCP initialize、列出工具并调用搜索：

```python
import asyncio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer <local-mcp-key>"}
    ) as client:
        async with streamable_http_client(
            "http://127.0.0.1:8090/mcp",
            http_client=client,
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print([tool.name for tool in tools.tools])
                result = await session.call_tool(
                    "search_shops",
                    {
                        "query": "quiet dinner in Midtown",
                        "category": "Food & Dining",
                        "neighborhood": "Midtown",
                        "desired_tags": ["quiet"],
                    },
                )
                print(result.structuredContent)


asyncio.run(main())
```

工具清单必须恰好是：

- `search_shops`
- `get_shop_detail`
- `get_shop_evidence`
- `get_available_vouchers`
- `calculate_route`
- `validate_itinerary`

`favorite_shop`、`save_itinerary`、`claim_standard_voucher`、`create_seckill_reminder` 和 `seckill_voucher` 都不应出现。

## 5. 自动化验证

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
uv run --project agent-service ruff check agent-service/app agent-service/tests
uv run --project agent-service pytest agent-service/tests -q
mvn -Dtest='!NycReviewApplicationTests' test
cd nyc-review-web && npm run build
```

`NycReviewApplicationTests` 会构造数据库和 Redis 数据，不要在承载有效数据的实例上执行。

如果 macOS 终端没有安装独立 Maven，但已安装 IntelliJ IDEA，可使用 IDE 自带的 Maven：

```bash
'/Applications/IntelliJ IDEA.app/Contents/plugins/maven/lib/maven3/bin/mvn' \
  -Dtest='!NycReviewApplicationTests' test
```

`npm run lint` 是独立的代码质量检查，不要与生产构建使用 `&&` 串联。当前仓库仍有一批历史 TypeScript ESLint 债务（主要是 `any`、空 `catch` 和 React Effect 规则），因此 P5 功能验收以 `npm run build` 为阻断项，lint 债务应单独清理且不能通过关闭规则掩盖。

Python 3.13 下 MCP SDK 可能输出 `IncompleteFieldDefinitionWarning`；只要 pytest 最终为通过，它不代表测试失败。
