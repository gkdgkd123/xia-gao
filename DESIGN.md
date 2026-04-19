# 虾搞 (Xia-Gao) — 产品设计文档

> 基于 OpenClaw 的项目自动化部署 Skill
> 协议: MIT | 语言: Python | 分发: GitHub

---

## 1. 产品定义

**一句话**: 虾搞是一个 OpenClaw Skill，让用户一句话部署任意 GitHub 项目到本地隔离沙箱，环境零污染，失败自动修复。

**目标用户**: 想试跑开源项目但怕搞坏环境的开发者。

**核心价值**: 从 "看到项目 → 折腾半天 → 环境搞乱 → 放弃" 到 "一句话部署 → 直接用 → 一键清理 → 环境无损"。

---

## 2. 仓库结构

```
xia-gao/
├── SKILL.md                  # OpenClaw Skill 主入口
├── README.md                 # GitHub 展示页（安装、使用、示例）
├── LICENSE                   # MIT
├── pyproject.toml            # Python 项目配置
├── src/
│   └── xia_gao/
│       ├── __init__.py
│       ├── cli.py            # 命令行入口
│       ├── analyzer.py       # 项目分析器（技术栈识别）
│       ├── isolator.py       # 隔离环境管理（Docker/Conda/venv）
│       ├── executor.py       # 部署执行器（拉代码、装依赖、启动）
│       ├── health.py         # 健康检查（端口、HTTP、进程）
│       ├── repair.py         # 自我修复（日志诊断、方案搜索、重试）
│       ├── cleaner.py        # 清理恢复（停止、删除、备份）
│       ├── planner.py        # 方案生成（Auto_deploy_plan.md）
│       ├── logger.py         # 日志管理（Auto_deploy.log）
│       └── config.py         # 配置管理（端口范围、镜像策略等）
├── docker/
│   ├── base.Dockerfile       # 基础沙箱镜像（Ubuntu + Python + Node + Go）
│   ├── python.Dockerfile     # Python 项目沙箱
│   ├── node.Dockerfile       # Node.js 项目沙箱
│   └── compose.template.yaml # compose 模板
├── templates/
│   ├── deploy_plan.md.tpl    # Auto_deploy_plan.md 模板
│   ├── cleanup.sh.tpl        # Cleanup.sh 模板
│   └── profile.json.tpl      # project-profile.json 模板
├── tests/
│   ├── test_analyzer.py      # 分析器测试
│   ├── test_isolator.py      # 隔离器测试
│   ├── test_executor.py      # 执行器测试
│   ├── test_health.py        # 健康检查测试
│   ├── test_repair.py        # 修复器测试
│   └── test_cleaner.py       # 清理器测试
│   └── fixtures/             # 测试用项目样本
│       ├── simple-python/
│       ├── simple-node/
│       └── with-dockerfile/
└── docs/
    └── ARCHITECTURE.md       # 架构说明
```

---

## 3. 核心模块设计

### 3.1 Analyzer — 项目分析器

**职责**: 克隆/扫描项目，输出 `project-profile.json`。

```python
class ProjectProfile:
    url: str                    # 项目 URL
    tech_stack: list[str]       # ["python", "node", "docker", "go"]
    has_dockerfile: bool
    has_compose: bool
    has_makefile: bool
    language_versions: dict     # {"python": "3.10+", "node": "18"}
    dependencies: list[str]     # 识别到的核心依赖
    entry_point: str            # 启动命令或入口文件
    ports: list[int]            # 需要暴露的端口
    env_vars: dict              # 需要的环境变量
    database_needed: bool       # 是否需要数据库
    gpu_needed: bool            # 是否需要 GPU

class Analyzer:
    def analyze(self, url: str) -> ProjectProfile
    def detect_dockerfile(self, repo_path: str) -> bool
    def detect_compose(self, repo_path: str) -> bool
    def detect_language(self, repo_path: str) -> list[str]
    def extract_ports(self, repo_path: str) -> list[int]
    def extract_env_vars(self, repo_path: str) -> dict
    def guess_entry_point(self, repo_path: str, profile: ProjectProfile) -> str
```

**技术栈识别策略**: 文件名启发式 + 内容关键词扫描。

| 文件/目录 | 识别为 |
|-----------|--------|
| `Dockerfile` | docker |
| `docker-compose.yml` | docker + compose |
| `requirements.txt` / `setup.py` / `pyproject.toml` | python |
| `package.json` | node |
| `go.mod` | go |
| `Cargo.toml` | rust |
| `Makefile` | make |

### 3.2 Isolator — 隔离环境管理

**职责**: 根据项目 profile 创建隔离环境。

```python
class IsolationResult:
    id: str                     # 部署 ID（xg-abc123）
    method: str                 # "docker" / "conda" / "venv"
    container_id: str | None    # Docker 容器 ID
    env_name: str | None        # Conda/venv 环境名
    ports: dict                 # {内部端口: 映射端口}
    workspace: str              # 隔离环境工作目录
    status: str                 # "created" / "running" / "failed"

class Isolator:
    def create(self, profile: ProjectProfile) -> IsolationResult
    def start(self, isolation: IsolationResult) -> bool
    def stop(self, isolation: IsolationResult) -> bool
    def destroy(self, isolation: IsolationResult) -> bool
    def select_method(self, profile: ProjectProfile) -> str
    def find_available_port(self, start: int = 3000) -> int
```

**隔离策略优先级**:

```
profile.has_dockerfile → 直接构建镜像
profile.has_compose   → compose up
profile.tech_stack 包含任何语言 → Docker 容器 + 语言环境
宿主机无 Docker       → venv / conda（降级策略）
```

**Docker 隔离流程**:

1. 从 `docker/` 目录选择匹配模板，或基于项目 Dockerfile 构建
2. 自动分配可用端口（3000-9999 范围）
3. 设置资源限制（CPU 1核，内存 2GB，防止项目吃满资源）
4. 挂载项目代码到容器 `/workspace`
5. 返回 `IsolationResult`

### 3.3 Executor — 部署执行器

**职责**: 在隔离环境中执行部署步骤。

```python
class DeployResult:
    id: str
    success: bool
    access_url: str | None      # "http://localhost:3456"
    logs: str                   # 执行日志
    errors: list[str]           # 错误列表
    cleanup_cmd: str            # 清理命令

class Executor:
    def deploy(self, profile: ProjectProfile, isolation: IsolationResult) -> DeployResult
    def install_deps(self, isolation: IsolationResult, profile: ProjectProfile) -> bool
    def configure_env(self, isolation: IsolationResult, profile: ProjectProfile) -> bool
    def start_service(self, isolation: IsolationResult, profile: ProjectProfile) -> bool
    def generate_cleanup(self, isolation: IsolationResult, profile: ProjectProfile) -> str
```

**部署策略（按技术栈）**:

| 技术栈 | 安装命令 | 启动命令 |
|--------|----------|----------|
| Python + requirements.txt | `pip install -r requirements.txt` | `python app.py` / `flask run` / `uvicorn` |
| Python + pyproject.toml | `pip install .` | 同上 |
| Node + package.json | `npm install` | `npm start` / `npm run dev` |
| Go + go.mod | `go build` | 运行编译产物 |
| Docker | 构建镜像 | `docker run` / `compose up` |

### 3.4 Health — 健康检查

**职责**: 部署后自动验证服务是否正常运行。

```python
class HealthResult:
    id: str
    alive: bool                 # 进程存活
    port_open: bool             # 端口可访问
    http_ok: bool | None        # HTTP 200（仅 HTTP 服务）
    response_time_ms: float | None
    error_details: str | None

class HealthChecker:
    def check(self, isolation: IsolationResult, profile: ProjectProfile) -> HealthResult
    def check_port(self, port: int) -> bool
    def check_http(self, url: str) -> tuple[bool, float]
    def check_process(self, isolation: IsolationResult, cmd: str) -> bool
```

**检查策略**: 启动后等待 5s，然后逐步检查（进程 → 端口 → HTTP），每步间隔 3s，最多等待 30s。

### 3.5 Repair — 自我修复

**职责**: 健康检查失败时，自动诊断并修复。

```python
class RepairResult:
    id: str
    attempts: int               # 修复尝试次数
    success: bool
    actions_taken: list[str]    # ["changed port 3000→3001", "added --host flag"]
    search_results: list[str]   # 搜索到的解决方案
    logs: str

class Repairer:
    def repair(self, deploy_result: DeployResult, health: HealthResult, 
               isolation: IsolationResult, profile: ProjectProfile) -> RepairResult
    def diagnose(self, logs: str, errors: list[str]) -> list[str]
    def search_solutions(self, error_keywords: list[str]) -> list[str]
    def apply_fix(self, fix: str, isolation: IsolationResult) -> bool
```

**修复循环**:

```
健康检查失败
→ 收集错误日志
→ 提取关键错误信息
→ 联网搜索解决方案（top 3）
→ 选择最匹配方案
→ 在隔离环境中尝试修复
→ 重新健康检查
→ 最多 3 次，失败后停止汇报
```

**常见修复策略库**:

| 错误模式 | 修复策略 |
|----------|----------|
| `Port already in use` | 自动换端口 |
| `ModuleNotFoundError` | pip install 缺失模块 |
| `Permission denied` | 检查文件权限，调整挂载 |
| `Connection refused` | 检查服务是否启动，添加 --host 0.0.0.0 |
| `Node version mismatch` | nvm 切换版本 |
| `Python version mismatch` | 切换 Python 版本镜像 |

### 3.6 Cleaner — 清理恢复

**职责**: 一键停止服务、删除容器/环境、恢复宿主机。

```python
class CleanResult:
    id: str
    success: bool
    resources_removed: list[str] # ["container xg-abc123", "volume xg-data"]
    backup_location: str | None  # 备份路径（如有）
    logs: str

class Cleaner:
    def cleanup(self, isolation: IsolationResult) -> CleanResult
    def stop_service(self, isolation: IsolationResult) -> bool
    def remove_container(self, isolation: IsolationResult) -> bool
    def remove_env(self, isolation: IsolationResult) -> bool
    def backup_data(self, isolation: IsolationResult) -> str | None
```

---

## 4. 用户交互流程

### 标准部署流程

```
用户: /xia-gao deploy https://github.com/user/project

虾搞:
┌─ 第一阶段：分析 ──────────────────────────
│ 🦐 分析项目 https://github.com/user/project
│ 检测到技术栈: Python + Flask + Redis
│ 需要: Python 3.10+, Redis, 端口 5000
│ 
│ ❓ 这个项目需要 Redis 数据库，我会在 Docker 中一起部署。
│    是否需要公网访问？(目前仅本地)
│    → 用户: 不需要，本地就行
│
│ 📋 部署方案已生成 → Auto_deploy_plan.md
└───────────────────────────────────────────

┌─ 第二阶段：基建 ──────────────────────────
│ 🦐 创建隔离沙箱...
│ 容器 xg-proj-a1b2 已创建
│ Python 3.10 venv 已初始化
│ Redis 容器 xg-redis-a1b2 已启动
│ 端口映射: 5000 → localhost:3456
└───────────────────────────────────────────

┌─ 第三阶段：部署 ──────────────────────────
│ 🦐 安装依赖... ✅ pip install 完成
│ 配置环境... ✅ .env 已生成
│ 启动服务... ✅ Flask 运行中
│ 健康检查... ✅ http://localhost:3456 返回 200
└───────────────────────────────────────────

┌─ 第四阶段：交付 ──────────────────────────
│ 🦐 部署完成！
│ 
│ 🌐 访问地址: http://localhost:3456
│ 📁 工作目录: ~/.xia-gao/workspace/xg-proj-a1b2
│ 🧹 清理命令: /xia-gao cleanup xg-proj-a1b2
│ 📋 完整日志: Auto_deploy.log
│ 📝 部署方案: Auto_deploy_plan.md
│ 🗑️ 一键清理: Cleanup.sh
└───────────────────────────────────────────
```

### 修复流程

```
用户: /xia-gao deploy https://github.com/user/broken-project

虾搞:
│ 启动服务... ❌ 端口 5000 无响应
│ 健康检查... ❌ 失败
│
│ 🔍 诊断: "bind: Address already in use"
│ 🔎 搜索解决方案... 找到 3 个
│ 🔧 修复尝试 1: 切换端口 → 5001
│ 健康检查... ✅ http://localhost:3457 返回 200
│
│ 🦐 修复成功！访问地址: http://localhost:3457
```

---

## 5. 开发里程碑

### v0.1.0 — 最小可用版本 (MVP)

**目标**: Docker 部署 + 基础修复，支持 Python 和 Node.js 项目。

**包含**:
- Analyzer: 文件名启发式技术栈识别
- Isolator: Docker 容器创建（单容器，不含 compose）
- Executor: pip install / npm install + 启动
- Health: 端口 + HTTP 检查
- Repair: 错误日志诊断 + 端口冲突修复 + 缺失依赖安装
- Cleaner: docker stop + rm
- SKILL.md: OpenClaw Skill 入口

**不包含**: Conda 支持、compose 多服务、GPU 项目、Web UI

**交付物**: GitHub repo + 可通过 `openclaw skills install` 安装

---

### v0.2.0 — 隔离增强

**新增**:
- Conda 环境支持（数据科学项目）
- venv 降级策略（宿主机无 Docker 时）
- Docker Compose 多服务部署（项目含 compose 文件时自动识别）
- 端口冲突自动规避
- 更完善的项目分析（README 解析、环境变量推断）

---

### v0.3.0 — 修复增强

**新增**:
- 联网搜索解决方案（集成 web search）
- 修复策略库扩展（覆盖 20+ 常见错误模式）
- 部署历史管理（`/xia-gao list` 查看所有活跃部署）
- 日志持久化（`/xia-gao logs <id>` 查看历史日志）

---

### v1.0.0 — ClawHub 正式发布

**新增**:
- 完善的 ClawHub 安装体验
- 测试覆盖 80%+
- 文档完善（架构说明、贡献指南）
- CI/CD（GitHub Actions 自动测试）

---

## 6. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 开发语言 | Python | AI 生态成熟，OpenClaw Agent 用 Python 调用方便 |
| 隔离方案 | Docker 优先 | 最干净，最通用，社区习惯 |
| 包管理 | pyproject.toml + pip | 现代标准，兼容性好 |
| 测试框架 | pytest | Python 标准，简洁 |
| 容器模板 | 多 Dockerfile | 按语言预构建，加快部署速度 |
| 日志格式 | 纯文本 + JSON 结构 | 人可读，程序可解析 |
| 部署 ID | xg-<hash6> | 短可识别，避免冲突 |

---

## 7. 安全边界

**以下操作必须询问用户**:
- 绑定到 0.0.0.0（公网暴露）
- 修改宿主机 iptables/防火墙
- sudo/root 操作
- 长期后台 daemon 运行
- 安装宿主机级包（apt/brew）
- 数据持久化到宿主机

**自动允许的操作**（均在隔离环境内）:
- 容器内 pip install / npm install
- 容器内 apt-get（不影响宿主机）
- 端口映射到 localhost
- 临时文件创建

---

## 8. 成功标准

**v0.1.0 MVP 验收**:
- 能成功部署 3 个不同类型的测试项目（Python/Node/Dockerfile）
- 部署失败时能自动修复至少 2 种常见错误
- 清理后宿主机无残留（docker ps 验证）
- Auto_deploy.log 完整记录所有操作
- Cleanup.sh 可一键清理