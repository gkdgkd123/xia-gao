# 虾搞 (Xia-Gao) Skill

一键安全部署 GitHub 项目到隔离沙箱，环境零污染，失败自动修复。

## 快速开始

在 Claude Code 中使用：

```
/xia-gao deploy https://github.com/user/repo
```

## 功能特性

- 🐳 **环境隔离**：优先使用 Docker 容器，确保宿主机零污染
- 🔍 **智能分析**：自动识别技术栈、依赖、配置需求
- 🌐 **联网搜索**：自动搜索最佳实践和解决方案
- 🔧 **自动修复**：失败时自动诊断并重试（最多3次）
- 📊 **状态管理**：持久化部署状态，随时查看和管理
- 🧹 **一键清理**：自动生成清理脚本，恢复环境如初

## 命令列表

| 命令 | 说明 |
|------|------|
| `/xia-gao deploy <url>` | 部署指定 GitHub 项目 |
| `/xia-gao status <id>` | 查看部署状态 |
| `/xia-gao logs <id>` | 查看部署日志 |
| `/xia-gao repair <id>` | 手动触发修复 |
| `/xia-gao cleanup <id>` | 清理指定部署环境 |
| `/xia-gao list` | 列出所有活跃部署 |

## 支持的项目类型

- ✅ Python (Flask, Django, FastAPI, etc.)
- ✅ Node.js (Express, Next.js, etc.)
- ✅ Go
- ✅ 含 Dockerfile 的项目
- ✅ 含 docker-compose.yml 的项目

## 工作流程

1. **分析与规划**：克隆项目 → 识别技术栈 → 搜索最佳实践 → 生成部署方案
2. **基建与隔离**：探测环境 → 创建容器 → 安装依赖
3. **部署与自检**：启动服务 → 健康检查 → 自动修复（如需要）
4. **交付**：提供访问地址 → 生成清理脚本

## 目录结构

```
~/.claude/skills/xia-gao/
├── SKILL.md                    # Skill 定义
├── config.json                 # 配置文件
├── README.md                   # 本文件
└── runtime/
    ├── deployments.json        # 所有部署状态
    └── <deploy-id>/            # 每个部署的工作目录
        ├── project-profile.json
        ├── deploy-plan.md
        ├── deploy.log
        ├── cleanup.sh
        └── repo/               # 克隆的项目代码
```

## 配置说明

编辑 `config.json` 可自定义：

- `workspace_root`: 工作目录根路径
- `default_isolation`: 默认隔离方式 (docker/conda/venv)
- `default_port_range`: 默认端口范围
- `max_repair_attempts`: 最大修复尝试次数
- `docker.default_base_image`: Docker 基础镜像

## 安全特性

- ✅ 默认使用 127.0.0.1 绑定，不暴露到公网
- ✅ 所有危险操作（sudo、系统包安装）需用户确认
- ✅ 自动生成清理脚本，确保可完全卸载
- ✅ 日志记录所有操作，便于审计

## 依赖要求

- Docker (推荐)
- Git
- Python 3 或 Conda (如果不使用 Docker)
- jq (用于 JSON 操作)

## 示例

### 部署 Flask 应用

```
/xia-gao deploy https://github.com/pallets/flask
```

### 查看部署状态

```
/xia-gao list
/xia-gao status xg-flask-123456
```

### 清理部署

```
/xia-gao cleanup xg-flask-123456
```

## 故障排查

### Docker 未运行

```bash
# 检查 Docker 状态
docker ps

# 启动 Docker (macOS/Windows)
# 打开 Docker Desktop 应用
```

### 端口被占用

Skill 会自动检测并分配可用端口，如果仍有问题：

```bash
# 查看端口占用
netstat -an | grep <port>
lsof -i :<port>
```

### 部署失败

查看详细日志：

```
/xia-gao logs <deploy-id>
```

或直接查看日志文件：

```bash
cat ~/.claude/skills/xia-gao/runtime/<deploy-id>/deploy.log
```

## 开发

本 Skill 基于纯 prompt + bash 实现，无需额外 Python 包。

如需修改行为，编辑 `SKILL.md` 中的逻辑即可。

## 致谢

本项目的联网搜索能力由以下公益服务提供支持：

- **web-search-fast MCP 服务** — 由 [linux.do](https://linux.do) 论坛的 [@NeoJ](https://linux.do/u/NeoJ) 用户提供的公益搜索 MCP 服务

感谢社区的无私贡献！

## License

MIT License - 详见项目根目录 LICENSE 文件
