---

# 虾搞 (Xia-Gao)
### —— 基于 OpenClaw 的项目自动化部署"防炸"神器

> **项目初衷：** 看到有趣的项目想在本地跑跑，却总被繁琐的环境搭建、依赖冲突和"环境弄乱了怎么办"的恐惧劝退？"虾搞"旨在通过 AI Agent 自动化处理一切，让你实现"一键试玩，环境无损"。

---

## 痛点分析

* **时间精力贵**：手动读 README、安装脚手架、配环境变量太耗时。
* **环境洁癖**：担心项目 A 的依赖把项目 B 的环境搞坏，甚至污染宿主机全局变量。
* **部署恐惧症**：报错搜不到解决方法，折腾半天最后只能默默关掉网页。

## 产品形态

**一个 OpenClaw Skill**，用户通过 `/xia-gao deploy <url>` 一句话部署任意 GitHub 项目。

* 开发语言：Python
* 隔离方案：Docker 优先 → Conda → venv 逐步支持
* 分发方式：GitHub
* 开源协议：MIT
* 包含自我修复能力
* 不包含 Web UI

## 核心准则

1. **环境零污染**：优先使用隔离容器（Docker），其次 Conda/venv。严禁直接修改宿主机全局环境。
2. **备份优先**：若必须修改系统配置，必须先执行备份，并在 `Auto_deploy.log` 中详细记录。
3. **事事有回应**：遇到关键决策点（如：是否长期后台运行、是否开启端口映射）必须询问用户。
4. **过程透明化**：所有操作逻辑、搜索结果、执行命令均实时记录在本地日志 `Auto_deploy.log`。

---

## 命令格式

* `/xia-gao deploy <url>` — 部署指定 GitHub 项目
* `/xia-gao status <id>` — 查看部署状态
* `/xia-gao logs <id>` — 查看部署日志
* `/xia-gao repair <id>` — 手动触发修复
* `/xia-gao cleanup <id>` — 清理指定部署环境
* `/xia-gao list` — 列出所有活跃部署

---

## Workflow

我们将整个部署过程拆解为四个阶段，由 OpenClaw Agent 自动执行：

### 第一阶段：分析与规划 (Brainstorming)

* **1. 需求分析与澄清**：接收项目链接，AI 与用户确认核心需求（如：是否需要 GPU、是否需公网访问、是否需要数据库）。
* **2. 项目分析**：克隆/扫描项目，识别技术栈、依赖、配置需求。输出 `project-profile.json`。
* **3. 知识检索 (Research)**：联网搜索该项目的最佳实践、已知问题、最新版本依赖。
* **4. 方案生成**：形成 `Auto_deploy_plan.md`，明确隔离方案、端口映射、环境变量。

### 第二阶段：基建与隔离 (Sandboxing)

* **5. 环境探针 (Probe)**：探测宿主机 OS、可用端口、Docker/Python/Conda 安装状态。
* **6. 隔离环境创建**：根据项目特征自动选择最合适的隔离方案。

| 项目类型 | 优先方案 | 备选方案 |
|----------|----------|----------|
| 含 Dockerfile | 直接构建镜像 | — |
| 含 docker-compose.yml | compose up | — |
| Python 项目 | Docker + venv | Conda（v0.2） |
| Node.js 项目 | Docker + nvm | — |
| Go 项目 | Docker + go build | — |
| 混合/复杂项目 | Docker compose | — |
| 用户无 Docker | venv / Conda | — |

* **7. 依赖注入**：在隔离环境中安装必要脚手架。

### 第三阶段：部署与自检 (Execution Loop)

* **8. 代码部署**：在隔离环境中拉取代码、安装依赖、配置环境变量。
* **9. 健康检查**：自动探测端口存活、HTTP 响应、进程状态。
  * 启动后等待 5s，逐步检查（进程 → 端口 → HTTP），每步间隔 3s，最多等待 30s。
* **10. 自我修复循环**（最多 3 次）：
  * 收集错误日志，提取关键错误信息
  * 联网搜索解决方案
  * 选择最匹配方案，在隔离环境中尝试修复
  * 重新健康检查
  * 3 次失败后停止，向用户汇报完整错误信息和手动修复建议

**常见修复策略库**：

| 错误模式 | 修复策略 |
|----------|----------|
| `Port already in use` | 自动换端口 |
| `ModuleNotFoundError` | pip install 缺失模块 |
| `Permission denied` | 检查文件权限，调整挂载 |
| `Connection refused` | 添加 --host 0.0.0.0 |
| `Node version mismatch` | nvm 切换版本 |

### 第四阶段：交付与清理 (Delivery)

* **11. 成果交付**：提供访问地址、账号密码（如有）、一键停用/清理指令。
* **12. 生成 Cleanup.sh**：一键卸载脚本，执行后恢复环境如初。

---

## 安全边界

以下操作**必须询问用户**，不得自动执行：
* 绑定到 0.0.0.0（公网暴露）
* 修改宿主机 iptables/防火墙
* sudo/root 操作
* 长期后台 daemon 运行
* 安装宿主机级包（apt/brew）
* 数据持久化到宿主机

自动允许的操作（均在隔离环境内）：
* 容器内 pip install / npm install
* 容器内 apt-get（不影响宿主机）
* 端口映射到 localhost
* 临时文件创建

---

## OpenClaw Skill 配置

详见 `SKILL.md`。核心要点：

1. Skill 名称: `xia-gao`
2. 依赖: Docker + Git（必须），Python（可选）
3. 安装方式: `openclaw skills install xia-gao`（通过 ClawHub）或手动克隆到 workspace `skills/` 目录
4. 工作目录: `XIA_GAO_WORKSPACE` 环境变量指定

---

## 记录文件说明

| 文件名 | 用途 |
| :--- | :--- |
| `Auto_deploy.log` | 运行日志，记录 AI 执行过的每一条命令和系统反馈。 |
| `Auto_deploy_plan.md` | 部署方案，记录 AI 对该项目的理解和详细操作逻辑。 |
| `project-profile.json` | 项目技术栈分析结果。 |
| `Cleanup.sh` | (自动生成) 一键卸载脚本，执行后恢复环境如初。 |

---

## 开发里程碑

### v0.1.0 — MVP（最小可用版本）

- Docker 部署 + 基础修复
* 支持 Python 和 Node.js 项目
* Analyzer 文件名启发式识别
* Health 端口 + HTTP 检查
* Repair 错误诊断 + 端口冲突修复
* Cleaner docker stop + rm
* SKILL.md OpenClaw 入口

### v0.2.0 — 隔离增强

- Conda 环境支持
* venv 降级策略
* Docker Compose 多服务
* 端口冲突自动规避
* README 解析、环境变量推断

### v0.3.0 — 修复增强

- 联网搜索解决方案
* 修复策略库扩展（20+ 常见错误）
* 部署历史管理 `/xia-gao list`
* 日志持久化 `/xia-gao logs`

### v1.0.0 — ClawHub 正式发布

- 测试覆盖 80%+
* 文档完善
* CI/CD（GitHub Actions）
