<p align="center">
  <strong>青蓝 · QingLan</strong><br/>
  <sub> C/C++ 语言作业提交与自动测评打分平台</sub>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MPL-2.0" src="https://img.shields.io/badge/License-MPL--2.0-blue.svg"/></a>
  <img alt="Python 3.11" src="https://img.shields.io/badge/Python-3.11-3776ab.svg"/>
  <img alt="React 18" src="https://img.shields.io/badge/React-18-61dafb.svg"/>
  <img alt="SQLite" src="https://img.shields.io/badge/DB-SQLite_(WAL)-003b57.svg"/>
</p>

---

>[!important]
>本项目还处于β开发阶段，请不要使用
>本项目由我/qoder生成，不保证质量。如果你不喜欢ai全部生成，请不要使用该项目

## 功能

| 角色 | 能力 |
|---|---|
| **admin** | 创建/停用教师与学生账号、重置密码、CSV 批量导入学生、维护"教师 ↔ 学生"绑定关系、配置全站主题色与背景图 |
| **teacher** | 维护题库（题面 + 测试用例，区分样例与隐藏用例）、发布场次（作业/测试：时间窗、提交次数上限、计分策略）、查看总览与分数分布、下钻个人提交、手动调分与重判、放出测试结果 |
| **student** | 查看被布置的场次、读题（含样例输入输出）、浏览器内代码编辑器提交、按反馈策略查看判定与得分 |

其它：JWT 认证 + bcrypt 口令哈希、判题沙箱强制断网、自动备份脚本、`prefers-reduced-motion` 适配、背景图浏览器本地压缩。

## 架构

系统由四个进程组成，判题链路单向串行：

```
浏览器 ──HTTP──▶ web 容器 (FastAPI :8000)
                    │  写 submission(status=pending)
                    ▼
                 SQLite (WAL, backend/data/cg.db)
                    ▲
                    │  领任务循环
                 judge worker ──HTTP──▶ go-judge 沙箱 (:5050)
                                          编译 gcc -std=c11 -O2
                                          逐用例隔离运行
                    ◀── time / memory / status / stdout ──┘
```

- **判题沙箱与业务进程分离**：go-judge 是唯一真正执行不可信代码的地方，只允许 worker 访问，compose 中挂在 `internal` 网络上，容器内无法出网。
- **无 Redis、无消息队列**：待判队列就是 SQLite 的 `status='pending'` 行，用一条带 `RETURNING` 的原子 `UPDATE ... WHERE id = (SELECT ...)` 抢占，规模匹配单校用量。
- **服务器上前端与 API 同端口**：web 镜像多阶段构建，`npm run build` 产物由后端进程按 `STATIC_DIR` 一起托管（本机开发时页面 5173、API 8000，别搞混）。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy 2.0 · Pydantic |
| 数据库 | SQLite（WAL 模式）+ Alembic 迁移 |
| 认证 | PyJWT（HS256）+ bcrypt |
| 前端 | React 18 · TypeScript · Vite 5 |
| UI | Fluent UI React v9（官方 Fluent 2 实现）+ CodeMirror 6 编辑器 |
| 图表 / 内容 | recharts · react-markdown · dayjs · chroma-js |
| 判题 | go-judge（独立沙箱服务）+ 自研 worker 编排 |
| 部署 | Docker Compose 单机三容器 |

## 快速开始

### 本机开发（Windows + PowerShell 7）

```powershell
pwsh scripts/start-local.ps1      # 一键拉起沙箱 → 后端 → worker → 前端
pwsh scripts/stop-local.ps1       # 全部停止
```

脚本是幂等的：已运行的服务跳过，缺的虚拟环境/`node_modules`/判题镜像自动补齐。首次约 5 分钟（要构建含 gcc 的 go-judge 派生镜像）。

启动完成后：

| | |
|---|---|
| 前端 | http://localhost:5173 |
| API 文档 | http://127.0.0.1:8000/docs |
| 沙箱健康检查 | http://127.0.0.1:5050/version |
| 默认管理员 | `admin` / `admin123`（**登录后立刻改密码**） |

手动四终端方式、以及沙箱对 cgroup 命名空间的硬性要求，见 [`部署操作指南.md`](部署操作指南.md) 第一部分。

### 服务器部署

```bash
git clone <本仓库> ~/qinglan && cd ~/qinglan
cp .env.example .env            # JWT_SECRET 用 openssl rand -hex 32 生成
docker compose -f docker/compose.yml up -d --build
docker compose -f docker/compose.yml exec web python scripts/init_admin.py
```

访问 `http://<服务器IP>:8000`。完整分步（含 Docker 安装、SSH、cgroup 自检、备份 cron、FAQ）见 [`部署操作指南.md`](部署操作指南.md) 第二部分。

## 项目结构

```
qinglan/
├── backend/
│   ├── app/
│   │   ├── api/         # admin / auth / student / teacher 四组路由
│   │   ├── core/        # 配置、数据库连接、JWT 与口令
│   │   ├── judge/       # go-judge 适配器、输出比对、worker 主循环
│   │   ├── services/    # 计分、统计、反馈可见性
│   │   ├── models.py    # SQLAlchemy 表定义
│   │   └── schemas.py   # Pydantic 模型
│   ├── migrations/      # Alembic 版本
│   ├── tests/           # pytest + fixtures/*.c（TLE/MLE/RE/fork 炸弹等）
│   └── requirements.txt
├── frontend/
│   └── src/{api,components,pages}/
├── docker/              # 三个 Dockerfile + compose.yml
├── scripts/             # 备份、改密、导入学生、本地启停
├── 开发文档.md           # 需求定稿、DDL、接口表、判题链路、里程碑验收清单
└── 部署操作指南.md        # 本机运行 + 服务器部署，零基础分步
```

## 致谢与引用的项目

青蓝的代码库中**不包含下列任何项目的源代码**。它们要么作为独立的上游依赖被安装（`pip` / `npm`），要么作为独立服务通过网络调用。每个项目版权归原作者，遵循其各自的许可证；本项目的 MPL-2.0 许可**不覆盖**它们。

### 作为服务调用的项目（本项目的核心依赖）

| 项目 | 仓库 | 许可证 | 在本项目中的作用 |
|---|---|---|---|
| **go-judge** | [criyle/go-judge](https://github.com/criyle/go-judge) | MIT | 沙箱执行器。通过命名空间、seccomp、cgroup 资源限制与无网络环境运行不可信二进制，返回耗时/内存/退出状态。本项目使用其镜像 `criyle/go-judge:v1.12.3`，并在派生镜像 `docker/Dockerfile.gojudge` 中加装 gcc；经 `POST /run` 以 HTTP 调用，与业务代码不构成链接关系 |

`docker/Dockerfile.gojudge` 中安装的 **GCC**（GPL-3.0-or-later，含 GCC Runtime Library Exception）与 **Debian/Alpine 基础镜像**中的系统组件，均仅作为容器内独立可执行程序调用，未与本项目的 Covered Software 合并为单一作品，不影响本项目的许可证选择。

### 后端依赖

| 项目 | 仓库 | 许可证 |
|---|---|---|
| FastAPI | [tiangolo/fastapi](https://github.com/fastapi/fastapi) | MIT |
| SQLAlchemy | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | MIT |
| Alembic | [sqlalchemy/alembic](https://github.com/sqlalchemy/alembic) | MIT |
| Pydantic | [pydantic/pydantic](https://github.com/pydantic/pydantic) | MIT |
| Uvicorn | [encode/uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause |
| httpx | [encode/httpx](https://github.com/encode/httpx) | BSD-3-Clause |
| python-multipart | [Kludex/python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 |
| PyJWT | [jpadilla/pyjwt](https://github.com/jpadilla/pyjwt) | MIT |
| bcrypt | [pyca/bcrypt](https://github.com/pyca/bcrypt) | Apache-2.0 |
| pytest | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) | MIT |
| Python 标准库 `sqlite3` | [python/cpython](https://github.com/python/cpython) | PSF-2.0 |

### 前端依赖

| 项目 | 仓库 | 许可证 | 用途 |
|---|---|---|---|
| React / React DOM | [facebook/react](https://github.com/facebook/react) | MIT | UI 框架 |
| Fluent UI React v9 | [microsoft/fluentui](https://github.com/microsoft/fluentui) | MIT | 组件库、主题与设计令牌（`@fluentui/react-components`、`@fluentui/react-icons`） |
| CodeMirror 6 | [codemirror](https://github.com/codemirror/view) 等 | MIT | 代码编辑器内核（`@uiw/react-codemirror` 同为 MIT） |
| `@codemirror/lang-cpp` | [codemirror/lang-cpp](https://github.com/codemirror/lang-cpp) | MIT | C 语法高亮 |
| recharts | [recharts/recharts](https://github.com/recharts/recharts) | MIT | 分数分布直方图 |
| react-markdown | [remarkjs/react-markdown](https://github.com/remarkjs/react-markdown) | MIT | 题面渲染（默认不渲染原始 HTML） |
| dayjs | [iamkun/dayjs](https://github.com/iamkun/dayjs) | MIT | 时间格式化 |
| chroma-js | [gka/chroma.js](https://github.com/gka/chroma.js) | BSD-3-Clause | 由主题色插值生成 Fluent brandRamp；从背景图提取主题色 |
| browser-image-compression | [Donaldcwl/browser-image-compression](https://github.com/Donaldcwl/browser-image-compression) | MIT | 超 5MB 背景图在浏览器本地压缩（Canvas + Web Worker） |
| Vite | [vitejs/vite](https://github.com/vitejs/vite) | MIT | 构建与开发服务器 |
| TypeScript | [microsoft/TypeScript](https://github.com/microsoft/TypeScript) | Apache-2.0 | 类型系统 |
| react-router-dom | [remix-run/react-router](https://github.com/remix-run/react-router) | MIT | 前端路由 |

> 上表许可证信息按各上游仓库当前的 `LICENSE` 文件填写。依赖会随版本演进，如与上游不符，**以上游仓库的 `LICENSE` 为准**。

### 产品与交互参考（未使用其任何代码）

- **希冀 Educg**（course.educg.net）— 作业发布与在线评测部分的交互流程作为需求讨论时的参照对象。本项目**未复制其界面、文案或代码**，全部功能为按《开发文档.md》独立实现。
- **Judge0 CE** — 判题服务的备选方案，仅在《开发文档.md》§7.5 作为评估记录出现，**默认不安装、未使用其任何代码**。
- **Hydro / QDUOJ / SDUOJ / HUSTOJ** — 整套开源 OJ，经评估后未采用（结论见《开发文档.md》§2.1），**未参考或复制其代码**。

## 许可

本项目（本仓库中由青蓝作者编写的全部源代码）采用 **[Mozilla Public License 2.0](LICENSE)** 授权。

```
Copyright (c) 2026 Makitoid Wang
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
```


