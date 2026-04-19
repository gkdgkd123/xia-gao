# 🦐 虾搞 (Xia-Gao)

一键安全部署 GitHub 项目到隔离沙箱，环境零污染，失败自动修复。

## 为什么需要虾搞？

看到有趣的开源项目想试试，结果：

- 读 README、装环境、配变量... 半天过去了
- 项目 A 的依赖搞乱了项目 B 的环境
- 报错搜不到答案，最后默默关掉

虾搞把这一切自动化：**一句话部署 → 直接用 → 一键清理 → 环境无损**。

## 安装

```bash
# 从 GitHub 克隆
git clone https://github.com/YOUR_USERNAME/xia-gao.git
cd xia-gao

# 安装依赖
pip install -e .

# 或使用 pip 直接安装（发布后可用）
pip install xia-gao
```

前置要求：
- Docker（必须）
- Git（必须）
- Python 3.10+（可选，用于 venv 降级）

## 使用

```bash
# 部署一个 GitHub 项目
xia-gao deploy https://github.com/user/project

# 查看部署状态
xia-gao status xg-abc123

# 查看部署日志
xia-gao logs xg-abc123

# 手动触发修复
xia-gao repair xg-abc123

# 一键清理（环境恢复如初）
xia-gao cleanup xg-abc123

# 列出所有活跃部署
xia-gao list
```

## 隔离策略

虾搞根据项目特征自动选择最合适的隔离方案：

| 项目类型 | 优先方案 | 备选方案 |
|----------|----------|----------|
| 含 Dockerfile | 直接构建镜像 | — |
| 含 docker-compose.yml | compose up | — |
| Python 项目 | Docker + venv | Conda |
| Node.js 项目 | Docker | — |
| Go 项目 | Docker | — |
| 用户无 Docker | venv / Conda | — |

所有 Docker 端口仅绑定到 `localhost`，不会暴露到公网。容器有资源限制（1 CPU, 2GB RAM）。

## 自我修复

部署失败时，虾搞自动进入修复循环：

```
健康检查失败
→ 收集错误日志
→ 诊断问题（端口冲突/依赖缺失/权限问题等）
→ 应用修复策略
→ 重新健康检查
→ 最多 3 次，失败后汇报手动修复建议
```

支持的修复策略：

| 错误模式 | 修复策略 |
|----------|----------|
| 端口冲突 | 自动换端口 |
| 缺失 Python 模块 | pip install |
| 权限问题 | 调整文件权限 |
| 连接拒绝 | 添加 --host 0.0.0.0 |
| Node 版本不匹配 | nvm 切换版本 |

## 安全边界

以下操作**必须询问用户**，不会自动执行：
- 绑定到 0.0.0.0（公网暴露）
- sudo/root 操作
- 安装宿主机级包（apt/brew）
- 修改防火墙/iptables

自动允许的操作（均在隔离环境内）：
- 容器内 pip install / npm install
- 容器内 apt-get（不影响宿主机）
- 端口映射到 localhost

## 作为 OpenClaw Skill 使用

虾搞也可以作为 OpenClaw Skill 使用：

```
/xia-gao deploy https://github.com/user/project
/xia-gao status xg-abc123
/xia-gao cleanup xg-abc123
```

将 `SKILL.md` 放入 OpenClaw workspace 的 `skills/` 目录即可。

## 项目结构

```
xia-gao/
├── src/xia_gao/        # 核心模块
│   ├── analyzer.py     # 项目分析器
│   ├── isolator.py     # 隔离环境管理
│   ├── executor.py     # 部署执行器
│   ├── health.py       # 健康检查
│   ├── repair.py       # 自我修复
│   ├── cleaner.py      # 清理恢复
│   ├── cli.py          # 命令行入口
│   ├── config.py       # 配置管理
│   └── logger.py       # 日志管理
├── docker/             # Docker 模板
├── templates/          # 输出模板
├── tests/              # 测试套件
└── docs/               # 文档
```

## 开发里程碑

- **v0.1.0** — MVP: Docker 部署 + 基础修复（Python/Node）
- **v0.2.0** — 隔离增强: Conda 支持 + venv 降级 + Docker Compose
- **v0.3.0** — 修复增强: 联网搜索 + 修复策略库扩展 + 部署历史管理
- **v1.0.0** — 正式发布: 测试覆盖 80%+ + 文档完善 + CI/CD

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码格式化
black src/

# 类型检查
mypy src/
```

## License

MIT