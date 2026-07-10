# hm-dianping

黑马点评全栈项目，后端使用 Spring Boot、MySQL 和 Redis，前端使用 React、TypeScript 与 Vite，并通过 Nginx 提供 SPA 静态资源和 API 反向代理。

## 环境要求

- Java 17
- Maven 3.9+
- MySQL 8+
- Redis 6+
- Node.js 20+
- npm 10+
- Nginx（仅部署时需要）

## 本地配置

应用不会在仓库中保存数据库密码或第三方 API Key。先创建本地环境文件：

```bash
cp .env.example .env
```

编辑 `.env`，填入本机数据库密码和 DeepSeek API Key。从项目根目录启动时，Spring Boot 会通过 `spring.config.import` 自动读取该文件，无需手动执行 `source`。操作系统环境变量的优先级高于 `.env`，因此部署环境仍可直接注入同名变量覆盖本地值。

环境变量说明：

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `HMDP_DB_URL` | 否 | JDBC 地址，默认连接本机 `hmdp_new` 数据库 |
| `HMDP_DB_USERNAME` | 否 | 数据库用户名，默认 `root` |
| `HMDP_DB_PASSWORD` | 是 | 数据库密码，无默认值 |
| `HMDP_REDIS_HOST` | 否 | Redis 地址，默认 `localhost` |
| `HMDP_REDIS_PORT` | 否 | Redis 端口，默认 `6379` |
| `HMDP_REDIS_DATABASE` | 否 | Redis 数据库编号，默认 `0` |
| `HMDP_REDIS_USERNAME` | 否 | Redis ACL 用户名，默认空 |
| `HMDP_REDIS_PASSWORD` | 否 | Redis 密码，默认空 |
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API Key，无默认值 |
| `DEEPSEEK_MODEL` | 否 | 翻译模型，默认 `deepseek-v4-flash` |
| `HMDP_IMAGE_UPLOAD_DIR` | 否 | 用户图片保存目录，默认 `./uploads/imgs`；Nginx 部署时应指向其图片目录 |

`.env` 和 `application-local.yaml` 已被 Git 忽略。`.env` 自动导入依赖当前工作目录；请从项目根目录启动后端。不要把真实凭据写入 `.env.example`、`application.yaml`、README 或提交记录。

## 初始化数据

创建 `hmdp_new` 数据库后导入当前数据集：

```bash
mysql -u root -p hmdp_new < src/main/resources/db/hmdp_new.sql
```

默认 Redis 地址为 `localhost:6379`，统一使用数据库编号 `0`。Spring Data Redis 与 Redisson 共用同一套连接配置。部分 GEO、秒杀库存和 Feed 数据需要按项目初始化流程写入 Redis；不要直接运行整个测试类，因为其中包含清表和测试数据回填操作。

## 启动后端

确认 MySQL、Redis 和环境变量均已就绪：

```bash
mvn spring-boot:run
```

后端默认监听 `http://127.0.0.1:8081`。

## 启动前端开发环境

```bash
cd hmdp-react
npm ci
npm run dev
```

Vite 默认监听 `http://127.0.0.1:3000`，并将 `/api` 代理到后端 8081 端口。

生产构建：

```bash
cd hmdp-react
npm run build
```

构建结果位于 `hmdp-react/dist`。

## Nginx 部署

当前桌面部署约定为：

- React 静态资源：`nginx-1.18.0/html/hmdp-react`
- 用户上传图片：`nginx-1.18.0/html/hmdp/imgs`
- Nginx 监听端口：`8080`
- Spring Boot 上游端口：`8081`

部署到 Nginx 时，请将 `HMDP_IMAGE_UPLOAD_DIR` 设置为上述用户图片目录的绝对路径。上传接口仅接受 JPEG、PNG 和 WebP，单文件最大 5MB。

将 `hmdp-react/dist` 中的内容部署到 React 静态资源目录后，检查并重新加载 Nginx 配置。SPA 路由需要保留 `try_files $uri $uri/ /index.html`，API 请求需要把 `/api` 前缀代理到 Spring Boot。

## 验证

```bash
cd hmdp-react
npm run build
npm run lint
```

后端测试类目前包含数据构造和 Redis 回填方法，在完成测试隔离前，不要对包含真实数据的数据库直接执行完整 `mvn test`。

## 安全说明

- 真实密钥如果曾进入 Git 历史，应立即在对应服务中轮换。
- 从当前文件删除密钥不会自动清除历史提交中的副本。
- Git 历史清理会改写提交历史，需要单独评估并协调所有协作者。
