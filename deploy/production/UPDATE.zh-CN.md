# NYC Review 固定发布流程

这份流程适用于当前单台 Lightsail 生产环境。服务器只拉取 GHCR 镜像，
不拉源码、不在服务器编译。生产环境始终使用 `sha-<完整 40 位提交 SHA>`，
不使用会移动的 `main` 标签。

## A. 普通代码更新（默认流程）

适用于 React 前端、Spring 后端、Python Agent、各自 Dockerfile，以及前端
Nginx 配置的修改。

### 1. 在 Mac 测试并提交

```bash
cd /Users/hollisyang/Desktop/hm-dianping
git status
git add <本次实际修改的文件>
git commit -m "简要描述本次修改"
git push origin main
```

不要提交 `.env.production`、API Key、密码或 `.DS_Store`。

### 2. 等待 GitHub Actions

打开仓库的 Actions 页面，等待 Spring、Agent、Web 三个任务全部成功。
从成功任务中复制完整 40 位 commit SHA。不要下载 `.dockerbuild` Artifacts，
它们只是构建记录。

### 3. 在 Lightsail 发布

```bash
cd /opt/nyc-review
./scripts/deploy/update-production.sh <完整40位commit SHA>
```

脚本会依次验证配置、拉取固定标签镜像、更新容器、等待健康检查，并打印
最终状态。MySQL、Redis、RabbitMQ、Qdrant、上传文件和 Agent 运行记录均
保存在持久卷中，不会因普通代码发布而清空。

### 4. 验收

```bash
curl --fail --show-error http://34.194.141.58/
curl --fail --show-error http://34.194.141.58/api/shop-type/list
curl --fail --show-error http://34.194.141.58/agent-api/health
```

绑定域名后，将地址替换为 `https://你的域名`。

## B. 部署配置更新

修改 `compose.production.yml`、Caddy、部署脚本、环境变量模板或数据库 SQL
时，除完成 A-1 和 A-2 外，还要在 Mac 重新生成并上传部署包：

```bash
cd /Users/hollisyang/Desktop/hm-dianping
./scripts/deploy/package-production-bundle.sh
scp -i /Users/hollisyang/Downloads/LightsailDefaultKey-us-east-1.pem \
  dist/nyc-review-production-bundle.tar.gz \
  ubuntu@34.194.141.58:/tmp/
```

在 Lightsail 覆盖配置（不会覆盖 `.env.production`）：

```bash
tar -xzf /tmp/nyc-review-production-bundle.tar.gz -C /opt/nyc-review
cd /opt/nyc-review
./scripts/deploy/check-production-config.sh .env.production
```

如果同一次提交也发布了新镜像，再执行 A-3。

## C. 生产环境变量更新

只在服务器编辑真实环境文件：

```bash
cd /opt/nyc-review
nano .env.production
./scripts/deploy/check-production-config.sh .env.production
docker compose --env-file .env.production -f compose.production.yml up -d --wait --wait-timeout 900
```

不要输出、截图或提交 `.env.production`。每个密码和服务 Token 必须不同。

## D. 数据库结构更新

`/docker-entrypoint-initdb.d` 只会在空 MySQL 数据卷首次创建时运行。给已有
生产数据库增加或修改结构时，必须先创建 Lightsail 快照或数据库备份，再
单独执行可重复、向后兼容的迁移脚本。不要通过删除 MySQL 数据卷来应用迁移。

## E. P13 数据更新

P13 是独立的数据发布，不属于普通代码更新：重新生成数据包、上传服务器、
设置目录为文件 `0644`/目录 `0755`，暂停应用层，导入 MySQL 和地图 SQL，
重新运行 `redis-seed`，再启动应用和 Agent。完成后必须验证：

- `tb_shop_type` 为 6 条；
- `tb_shop` 中 `OPENSTREETMAP` 为 5000 条（或新版本声明的数量）；
- `tb_data_import` 有且只有一个 active 导入；
- Agent 和 Qdrant 健康。

## F. 回滚普通代码版本

找到上一个成功部署的完整 SHA，在 Lightsail 执行：

```bash
cd /opt/nyc-review
./scripts/deploy/update-production.sh <上一个完整40位commit SHA>
```

当前已知稳定版本为：

```text
529cf2090e0b3b55fe0b035c88077c5f99980092
```

代码镜像回滚不会自动回滚数据库迁移或 P13 数据，因此二者必须使用独立的
备份和恢复方案。

## 永远不要做

```bash
docker compose down -v
```

`-v` 会删除数据库、Redis、RabbitMQ、Qdrant、上传文件、TLS 证书和 Agent
运行记录。也不要在服务器执行 `docker compose build` 或使用 `main` 镜像标签。
