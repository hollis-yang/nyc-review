# NYC Review 固定生产发布流程

这份流程适用于当前单台 AWS Lightsail 生产环境。服务器只拉取 GHCR 镜像，
不拉源码、不编译代码。代码镜像与数据库发布统一绑定到完整的 40 位 Git SHA。

## 日常发布：只需要一个 SHA

### 1. 在 Mac 提交并推送

```bash
cd /Users/hollisyang/Desktop/hm-dianping
git status
git add <本次实际修改的文件>
git commit -m "简要描述本次修改"
git push origin main
```

不要提交 `.env.production`、API Key、密码或 `.DS_Store`。

### 2. 等待 GitHub Actions

等待 Spring、Agent、Web 三个任务全部成功。三个任务显示的是同一个 commit，
从任意一个任务复制完整的 40 位 commit SHA 即可。不要下载 `.dockerbuild`
Artifacts，它们只是构建记录。

### 3. 在 Mac 执行一条命令

```bash
cd /Users/hollisyang/Desktop/hm-dianping
./scripts/deploy/release-production.sh <完整40位commit SHA>
```

这条命令必须在 Mac 本地仓库中执行，不是在 AWS 浏览器 SSH 中执行。它会：

1. 确认 SHA 就是当前 `origin/main` commit，且仓库没有未提交文件；
2. 打包生产 Compose、部署脚本和数据库发布清单；
3. 把被 Git 忽略但列入清单的 SQL/Redis 数据文件一起上传 Lightsail；
4. 暂停入口并等待秒杀订单队列清空；
5. 只执行服务器尚未记录过的数据库变更；
6. 拉取 `sha-<完整SHA>` 的 Spring、Agent、Web 镜像并等待全部健康。

默认连接信息已经写入脚本：

```text
SSH key: /Users/hollisyang/Downloads/LightsailDefaultKey-us-east-1.pem
Server:  ubuntu@34.194.141.58
Path:    /opt/nyc-review
```

如果以后更换服务器或 SSH key，可以用环境变量覆盖，不需要修改脚本：

```bash
LIGHTSAIL_SSH_KEY=/新路径/key.pem \
LIGHTSAIL_SSH_TARGET=ubuntu@新IP \
NYC_REVIEW_REMOTE_ROOT=/opt/nyc-review \
./scripts/deploy/release-production.sh <完整40位commit SHA>
```

### 4. 验收

```bash
curl --fail --show-error http://34.194.141.58/
curl --fail --show-error http://34.194.141.58/api/shop-type/list
curl --fail --show-error http://34.194.141.58/agent-api/health
```

绑定域名后，将地址替换为 `https://你的域名`。

## 怎样加入下一次数据库更新

数据库发布清单是：

```text
deploy/production/database-release.tsv
```

每次新增一行，四列依次为：

```text
唯一变更编号    schema或overlay    MySQL SQL路径    Redis RESP路径或-
```

示例：

```text
20260901_add_user_badge_v1	schema	src/main/resources/db/migrations/016_add_user_badge.sql	-
20260901_badge_seed_v1	overlay	data/generated/nyc-real-p13-full/badge_overlay.sql	data/generated/nyc-real-p13-full/badge_overlay.resp
```

要求：

- 一个变更编号上线后永远不要修改或复用；后续修正必须新增一行和新编号；
- SQL 必须能安全重跑；需要同时改 Redis 时，使用 `redis-cli --pipe` 格式的 RESP；
- `data/generated/...` 可以继续被 Git 忽略，一键脚本会按清单从 Mac 打包；
- 当前清单已经包含密码登录、优惠券覆盖、用户社交、评论互动和演示账户数据；
- 自动流程不会创建数据库备份，这是当前生产策略；数据库变更无法通过旧 SHA 自动回滚。

## 哪些情况不使用这个脚本

完整替换 P13 数据集不属于增量数据库更新。它可能删除或重建大量业务数据，
仍需使用独立的 P13 导入流程：上传完整数据目录、暂停应用、导入 MySQL 与地图
SQL、重新运行 Redis seed、重建 Agent 索引并单独验收。

修改 `.env.production`（例如更换 DeepSeek API Key）也只在服务器完成：

```bash
cd /opt/nyc-review
nano .env.production
./scripts/deploy/check-production-config.sh .env.production
docker compose --env-file .env.production -f compose.production.yml \
  up -d --wait --wait-timeout 900
```

不要输出、截图或提交 `.env.production`。

## 代码回滚与故障恢复

普通代码回滚可以在 Lightsail 执行原脚本：

```bash
cd /opt/nyc-review
./scripts/deploy/update-production.sh <上一个成功版本的完整40位SHA>
```

数据库发布失败时，一键脚本会尝试重新启动之前配置的应用镜像。已经成功执行并
记录的数据库变更不会再次执行。代码镜像回滚不会撤销数据库或 Redis 变更。

## 永远不要做

```bash
docker compose down -v
```

`-v` 会删除数据库、Redis、RabbitMQ、Qdrant、上传文件、TLS 证书和 Agent
运行记录。也不要在服务器执行 `docker compose build` 或使用 `main` 镜像标签。
