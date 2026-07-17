<div align="center">

![cloud-logo](img/icon.png)

# 网盘自动转存

网盘签到、自动转存、命名整理、发推送提醒、刷新媒体库、生成CAS、生成STRM一条龙，内置自动修复异常任务能力。

[![zread](https://img.shields.io/badge/Ask_AI-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/OzoO0/cloud-auto-save-x)

[![wiki][wiki-image]][wiki-url] [![github releases][gitHub-releases-image]][github-url] [![docker pulls][docker-pulls-image]][docker-url] [![docker image size][docker-image-size-image]][docker-url]

[wiki-image]: https://img.shields.io/badge/wiki-Documents-green?logo=github
[gitHub-releases-image]: https://img.shields.io/github/v/release/OzoO0/cloud-auto-save-x?logo=github
[docker-pulls-image]: https://img.shields.io/docker/pulls/ozoo0/cloud-auto-save-x?logo=docker&&logoColor=white
[docker-image-size-image]: https://img.shields.io/docker/image-size/ozoo0/cloud-auto-save-x?logo=docker&&logoColor=white
[github-url]: https://github.com/OzoO0/cloud-auto-save-x
[docker-url]: https://hub.docker.com/r/ozoo0/cloud-auto-save-x
[wiki-url]: https://github.com/Cp0204/quark-auto-save/wiki

![run_log](img/run_log.png)

</div>

> \[!CAUTION]
> ⛔️⛔️⛔️ 注意！资源不会每时每刻更新，**严禁设定过高的定时运行频率！** 以免账号风控和给网盘服务器造成不必要的压力。雪山崩塌，每一片雪花都有责任！

> \[!NOTE]
> 开发者≠客服，开源免费≠帮你解决使用问题；本项目 Wiki 已经相对完善，遇到问题请先翻阅 Issues 和 Wiki ，请勿盲目发问。

## 项目简介

网盘自动转存（Cloud Auto Save X 简称 CASX）是一个基于 FastAPI + Vue3 的 Web 应用，提供网盘自动转存功能，可以帮助你：

- 🔄 **自动转存**：定时或自动（根据节目状态和任务进度）运行，自动转存各种网盘分享链接中的文件
- 🔄 **数据同步**：支持 OpenList、网盘直连、NAS 本地目录等多种同步方式，适合多网盘与本地资料库统一管理
- 📝 **智能规则**：在为手动配置重命名规则并且配置TMDB配置时，支持自动识别-重命名
- 🧩 **文件过滤**：通过过滤规则排除不需要的文件或文件夹，支持高级过滤功能
- 📊 **任务管理**：支持多任务管理，支持全局统一设置及单任务独立设置，支持任务筛选、排序、暂停、停止、继续等操作
- 🔍 **资源搜索**：智能搜索网盘资源，自动识别链接可用性，自动定位到分享目录
- 🎬 **影视发现**：浏览豆瓣热门影视榜单，一键快速创建任务，智能填充配置
- 📅 **追剧日历**：追踪节目播出时间，了解转存进度，支持海报视图和日历视图
- ✅ **自动签到**：每日自动签到领空间（支持：夸克网盘、天翼云盘、百度网盘）
- 🔔 **通知推送**：支持多个通知推送渠道，及时了解转存状态
- 🔌 **插件系统**：支持多种插件扩展功能，包括媒体库局部刷新、下载任务推送、strm 文件生成等
- 🔄 **自动修复异常任务**：自动识别并修复异常任务，如分享链接失效、账号被限流等
- 🔄 **多网盘复制与秒传加速**：支持网盘到网盘、网盘到本地、本地到网盘的复制，并自动为后续分发准备秒传数据
- 🔄 **STRM 302直连与反代**: 支持生成302直连STRM，支持飞牛影视反代，并可结合多账号自动负载与 CAS 数据实现更顺滑的直连体验

## 核心功能

### 网盘支持情况

| 网盘名称  | 签到 | 302 |
|:-----:|:--:|:---:|
| 夸克网盘  | ✅  | ✅  |
| 天翼云盘  | ✅ | ✅  |
| 百度网盘  | ✅ | ❌  |
| 阿里云盘  | ❌ | ❌ |
| 115网盘 | ❌ | ✅ |
| 123网盘 | ❌ | ❌ |
| UC网盘  | ❌ | ✅ |
| 迅雷网盘  | ❌ | ❌ |
| 移动云盘  | ✅ | ✅ |
| 光鸭云盘  | ❌ | ❌ |

### 自动转存

- 分享链接自动识别资源存放文件夹
- 转存任务文件智能重命名（需配置TMDB API密钥）
- 智能搜索资源并自动填充（集成 CloudSaver、PanSou，支持有效性检查、失效过滤）
- 支持自动修复异常任务（如分享链接失效、账号被限流等）
- 支持自动解压压缩包（仅限夸克高级会员）
- 支持一次性转存任务

### 数据同步

- 支持 OpenList、网盘直连、本地目录等多种同步端点
- 支持网盘与网盘、网盘与 NAS、本地资料库之间的数据同步
- 支持同步任务统一管理，便于查看进度、执行状态和异常信息
- 适合把常用网盘内容同步到本地媒体库，或在多个网盘之间建立副本

### 网盘复制与秒传加速

- 支持本地到网盘、网盘到本地、网盘到网盘的文件复制
- 支持流式复制与下载复制两种方式，可按场景选择速度优先或空间优先
- 支持 115、天翼云盘、移动云盘等账号间更高效的同盘复制体验
- 复制完成后会自动准备可复用的秒传数据，方便后续把同一文件快速分发到其他网盘
- 即使文件先落到本地或临时目录，也能继续为后续上传准备可复用的数据

### CAS 数据任务

- 支持按账号扫描 `302_path` 下的视频文件，批量生成 CAS 数据
- 已生成的数据可直接服务于 302 反代、预览和多网盘分发场景
- 支持任务创建、暂停、停止、继续和查看明细进度
- 任务状态会持久保存，服务重启或中断后可继续处理未完成任务
- 适合首次接入 302 反代时做一次性预热，也适合后续按需补全

### 多网盘 302 与智能反代

- 支持飞牛影视反代（其它系统会陆续适配）
- 当飞牛挂载本地资源时，自动识别内外网，如果网盘中同样存储对应资源，自动切换到网盘资源进行302直连
- 智能负载策略，根据网盘负载情况智能切换到不同网盘进行302直连（需要网盘中有资源）
- 支持同类型多账号自动负载，减少单账号压力，提升预览可用性
- 多网盘自动负载无需手动同步，配合 CAS 能力实现主网盘有资源、子网盘少操作甚至免操作即可实现302直连反代
- 配合 STRM 使用时，可进一步提升媒体库预览和播放体验

注：不建议将反代端口直接暴露给公网，可能存在安全风险。建议搭配Web反代服务使用。

## 部署

### Docker 部署

Docker 部署提供 WebUI 进行管理配置，部署命令：

```shell
docker run -d \
  --name cloud-auto-save-x \
  -p 5115:5115 \ # 映射端口，:前的可以改，即部署后访问的端口，:后的不可改
  -p 5225:5225 \ # 反代端口，:前的可以改，即部署后访问的端口，:后的不可改
  -v ./cloud-auto-save-x/data:/app/backend/data \ # 必须，配置持久化
  -v ./cloud-auto-save-x/media:/media \ # 可选，模块alist_strm_gen生成strm使用
  -v ./cloud-auto-save-x/strm:/strm \ # 可选，项目本身生成strm使用
  -v ./cloud-auto-save-x/nasfile:/app/backend/data/sync/nasfile \ # 可选，用于同步任务Local使用，可与网盘数据同步
  --network bridge \
  --restart unless-stopped \
  ozoo0/cloud-auto-save-x:latest
  # registry.cn-hangzhou.aliyuncs.com/ozoo0/cloud-auto-save-x:latest # 国内镜像地址
```

docker-compose.yml

```yaml
name: cloud-auto-save-x
services:
  cloud-auto-save-x:
    image: ozoo0/cloud-auto-save-x:latest
    container_name: cloud-auto-save-x
    network_mode: bridge
    ports:
      - 5115:5115
      - 5225:5225
    restart: unless-stopped
    volumes:
      - ./cloud-auto-save-x/data:/app/backend/data
      - ./cloud-auto-save-x/media:/media
      - ./cloud-auto-save-x/strm:/strm
      - ./cloud-auto-save-x/nasfile:/app/backend/data/sync/nasfile
```

管理地址：<http://yourhost:5115>

| 环境变量             | 默认         | 备注                           |
| ---------------- | ---------- | ---------------------------- |
| `PORT`           | `5115`     | 管理后台/302端口                       |
| `REVERSE_PORT`   | `5225`     | 反代端口                       |
| `DEBUG`          | `0`        | 开启调试模式，打印更多日志信息 |
| `DB_DRIVER`      | `sqlite3`  | 数据库驱动，可选 `sqlite3` / `mysql` |
| `DATABASE_URL`   | 空         | 完整数据库连接串，配置后优先级最高 |
| `SQLITE_PATH`    | `./data/app.db` | SQLite 数据库文件路径 |
| `APP_DATA_DIR`   | `./data`   | 项目运行数据目录，缓存等文件会落在这里 |
| `DB_HOST`        | `127.0.0.1`| MySQL 主机地址，仅 `DB_DRIVER=mysql` 时生效 |
| `DB_PORT`        | `3306`     | MySQL 端口，仅 `DB_DRIVER=mysql` 时生效 |
| `DB_NAME`        | `xxm`      | MySQL 数据库名，仅 `DB_DRIVER=mysql` 时生效 |
| `DB_USER`        | `root`     | MySQL 用户名，仅 `DB_DRIVER=mysql` 时生效 |
| `DB_PASSWORD`    | 空         | MySQL 密码，仅 `DB_DRIVER=mysql` 时生效 |
| `DB_CHARSET`     | `utf8mb4`  | MySQL 字符集，仅 `DB_DRIVER=mysql` 时生效 |
| `DRAMA_RUNTIME_RETRY_MAX_ATTEMPTS`        | `0`        | 最大重试次数，默认3次，0表示不重试 |
| `DRAMA_RUNTIME_RETRY_BACKOFF_SECONDS`        | `1`        | 重试延迟时间，默认1秒 |
| `DRAMA_RUNTIME_RETRY_MAX_BACKOFF_SECONDS`        | `8`        | 最大重试延迟时间，默认8秒 |
| `DRAMA_RUNTIME_RETRY_JITTER_RATIO`        | `0.2`        | 重试延迟随机化比例，默认0.2 |
| `DL302_COPY_PART_CONCURRENCY`        | `4`        | dl302 下载模式分片并发数，值大于 1 时会优先对 HTTP/HTTPS 源启用并发 Range 下载 |
| `DL302_COPY_PART_SIZE_MB`        | `10`        | dl302 下载模式单分片大小（MB），与 `DL302_COPY_PART_CONCURRENCY` 配合控制并发下载粒度 |

### 使用 MySQL

项目默认使用 `sqlite3`。如果需要切换到 MySQL，有两种配置方式：

1. 直接配置完整连接串：

```env
DB_DRIVER=mysql
DATABASE_URL=mysql+pymysql://root:your_password@127.0.0.1:3306/xxm?charset=utf8mb4
APP_DATA_DIR=./data
```

2. 使用分项配置：

```env
DB_DRIVER=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=xxm
DB_USER=root
DB_PASSWORD=your_password
DB_CHARSET=utf8mb4
APP_DATA_DIR=./data
```

说明：

- `DATABASE_URL` 优先级最高，配置后会覆盖 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`
- `APP_DATA_DIR` 是项目运行数据目录，不是 MySQL 数据文件目录
- 首次切换到 MySQL 前请先手动创建数据库，例如 `CREATE DATABASE xxm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`
- 配置完成后请执行数据库迁移，再启动服务

如果使用 `docker-compose`，可以这样写：

```yaml
name: cloud-auto-save-x
services:
  cloud-auto-save-x:
    image: ozoo0/cloud-auto-save-x:latest
    container_name: cloud-auto-save-x
    network_mode: bridge
    ports:
      - 5115:5115
      - 5225:5225
    restart: unless-stopped
    environment:
      DB_DRIVER: mysql
      DB_HOST: 127.0.0.1
      DB_PORT: 3306
      DB_NAME: xxm
      DB_USER: root
      DB_PASSWORD: your_password
      DB_CHARSET: utf8mb4
      APP_DATA_DIR: /app/backend/data
    volumes:
      - ./cloud-auto-save-x/data:/app/backend/data
      - ./cloud-auto-save-x/media:/media
      - ./cloud-auto-save-x/strm:/strm
      - ./cloud-auto-save-x/nasfile:/app/backend/data/sync/nasfile
```

如果是源码运行，请在 `backend/.env` 中写入上述配置，然后执行：

```shell
cd backend
alembic upgrade head
```



<details open>
<summary>WebUI 预览</summary>

![dashboard](img/96fd01ae-dc64-42f2-992c-4faf6daab0bb.png)

![discover](img/57b6b274-2b26-44df-9a28-f53e8def0582.png)

![calendar](img/76083cce-5c3e-406c-87fa-51ae8a31bcd2.png)

![calendar-year](img/8cdb803a-4107-49ac-84b4-7a215a527a5f.png)

![account](img/48c4b746-5d82-419d-8054-c3bf8514bbc5.png)

</details>

## 使用说明

### 正则处理示例

| pattern                        | replace                 | 效果                                                 |
| ------------------------------ | ----------------------- | -------------------------------------------------- |
| `.*`                           | <br />                  | 无脑转存所有文件，不整理                                       |
| `\.mp4$`                       | <br />                  | 转存所有 `.mp4` 后缀的文件                                  |
| `^【电影TT】花好月圆(\d+)\.(mp4\|mkv)` | `\1.\2`                 | 【电影TT】花好月圆01.mp4 → 01.mp4【电影TT】花好月圆02.mkv → 02.mkv |
| `^(\d+)\.mp4`                  | `S02E\1.mp4`            | 01.mp4 → S02E01.mp402.mp4 → S02E02.mp4             |
| `TV_REGEX`                          | <br />                  | [魔法匹配](#魔法匹配)剧集文件                                  |
| `^(\d+)\.mp4`                  | `{TASKNAME}.S02E\1.mp4` | 01.mp4 → 任务名.S02E01.mp4                            |

**默认规则**：在已配置TMDB后，留空则增加兜底智能匹配。

更多正则使用说明：[正则处理教程](https://github.com/ozoo0/cloud-auto-save-x/wiki/正则处理教程)

> \[!TIP]
>
> **魔法匹配和魔法变量**：在正则处理中，我们定义了一些“魔法匹配”模式，如果 表达式 的值以 $ 开头且 替换式 留空，程序将自动使用预设的正则表达式进行匹配和替换。
>
> 更多说明请看[魔法匹配和魔法变量](https://github.com/ozoo0/cloud-auto-save-x/wiki/魔法匹配和魔法变量)


### 刷新媒体库

在有新转存时，可触发完成相应功能，如自动刷新媒体库、生成 .strm 文件等。配置指南：[插件配置](https://github.com/ozoo0/cloud-auto-save-x/wiki/插件配置)

媒体库模块以插件的方式的集成，如果你有兴趣请参考[插件开发指南](https://github.com/ozoo0/cloud-auto-save-x/tree/main/plugins)。

### 更多使用技巧

请参考 Wiki ：[使用技巧集锦](https://github.com/ozoo0/cloud-auto-save-x/wiki/使用技巧集锦)


## 声明

本项目基于个人兴趣开发并开源，仅供学习与交流使用，不包含任何破解行为，只是对网盘官方 API 的封装与调用，所有数据均来源于各大网盘官方，本人不对网盘内容及官方 API 变更所导致的任何后果负责。

## 致谢

本项目参考 [Cp0204/quark-auto-save](https://github.com/Cp0204/quark-auto-save/releases/tag/v0.8.4) 思路进行整体重构，感谢 [Cp0204](https://github.com/Cp0204) 的开源贡献。

## ❤️ 支持项目

如果觉得这个项目对你有帮助，你可以通过以下方式支持我：

1. ⭐ 给项目点个 Star，让更多的人看到
2. 📢 分享给更多有需要的朋友
3. ☕ 请作者喝杯冰阔乐~

<div align="center">
<img src="img/wechat.jpg" alt="微信" height="300">
    <img src="img/ali.jpg" alt="支付宝" height="300" style="margin-right: 20px">
</div>


## Sponsor

CDN acceleration and security protection for this project are sponsored by Tencent EdgeOne.

<a href="https://edgeone.ai/?from=github" target="_blank"><img title="Best Asian CDN, Edge, and Secure Solutions - Tencent EdgeOne" src="https://edgeone.ai/media/34fe3a45-492d-4ea4-ae5d-ea1087ca7b4b.png" width="300"></a>

## Star History

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=OzoO0/cloud-auto-save-x&type=Date&theme=dark" />
  <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=OzoO0/cloud-auto-save-x&type=Date" />
  <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=OzoO0/cloud-auto-save-x&type=Date" />
</picture>
