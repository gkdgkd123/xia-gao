"""部署执行器 — 在隔离环境中拉代码、装依赖、启动服务."""

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xia_gao.analyzer import ProjectProfile
from xia_gao.config import config
from xia_gao.isolator import IsolationResult
from xia_gao.logger import DeploymentLogger


@dataclass
class DeployResult:
    """部署执行结果."""

    id: str
    success: bool = False
    access_url: Optional[str] = None  # "http://localhost:3456"
    logs: str = ""
    errors: list[str] = field(default_factory=list)
    cleanup_cmd: str = ""
    started_at: str = ""
    elapsed_seconds: float = 0.0


class Executor:
    """部署执行器."""

    def __init__(self, logger: Optional[DeploymentLogger] = None):
        self.logger = logger

    def deploy(
        self, profile: ProjectProfile, isolation: IsolationResult
    ) -> DeployResult:
        """在隔离环境中执行部署."""
        result = DeployResult(id=isolation.id)

        if self.logger:
            self.logger.section("第三阶段: 部署与自检")

        start_time = time.time()

        # 1. 安装依赖
        if not self.install_deps(isolation, profile):
            result.success = False
            result.errors.append("依赖安装失败")
            if self.logger:
                self.logger.error("依赖安装失败")
            result.logs = self._collect_logs(isolation)
            return result

        # 2. 配置环境
        if not self.configure_env(isolation, profile):
            result.errors.append("环境配置失败")
            # 继续执行，环境配置失败不终止

        # 3. 启动服务
        if not self.start_service(isolation, profile):
            result.success = False
            result.errors.append("服务启动失败")
            if self.logger:
                self.logger.error("服务启动失败")
            result.logs = self._collect_logs(isolation)
            return result

        # 4. 生成清理命令
        result.cleanup_cmd = self.generate_cleanup(isolation, profile)

        # 5. 构造访问地址
        if isolation.ports:
            # 取第一个端口作为主访问地址
            internal_port = list(isolation.ports.keys())[0]
            mapped_port = isolation.ports[internal_port]
            result.access_url = f"http://localhost:{mapped_port}"

        result.success = True
        result.elapsed_seconds = time.time() - start_time
        result.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        if self.logger:
            self.logger.success(f"部署完成! 访问地址: {result.access_url}")
            self.logger.step(f"清理命令: {result.cleanup_cmd}")

        return result

    def install_deps(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """在隔离环境中安装依赖."""
        if self.logger:
            self.logger.step("安装依赖...")

        if isolation.method in ("docker", "docker-compose"):
            return self._install_deps_docker(isolation, profile)
        elif isolation.method == "conda":
            return self._install_deps_conda(isolation, profile)
        elif isolation.method == "venv":
            return self._install_deps_venv(isolation, profile)
        return False

    def configure_env(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """配置环境变量."""
        if not profile.env_vars:
            return True

        if self.logger:
            self.logger.step("配置环境变量...")

        if isolation.method == "docker" and isolation.container_id:
            # Docker 容器已在创建时注入环境变量
            if self.logger:
                self.logger.step("环境变量已在容器创建时注入")
            return True

        # 非 Docker 方式：写入 .env 文件
        env_file = Path(isolation.workspace) / ".env"
        env_content = "\n".join(f"{k}={v}" for k, v in profile.env_vars.items())
        env_file.write_text(env_content, encoding="utf-8")

        if self.logger:
            self.logger.step(f".env 文件已生成 ({len(profile.env_vars)} 个变量)")

        return True

    def start_service(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """启动服务."""
        if self.logger:
            self.logger.step("启动服务...")

        if isolation.method in ("docker", "docker-compose"):
            return self._start_docker_service(isolation, profile)
        elif isolation.method == "conda":
            return self._start_conda_service(isolation, profile)
        elif isolation.method == "venv":
            return self._start_venv_service(isolation, profile)
        return False

    def generate_cleanup(self, isolation: IsolationResult, profile: ProjectProfile) -> str:
        """生成清理命令."""
        return f"xia-gao cleanup {isolation.id}"

    # --- Docker 方式 ---

    def _install_deps_docker(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """Docker 方式安装依赖（已在构建时完成）."""
        # 如果项目有 Dockerfile，依赖在构建镜像时已安装
        if profile.has_dockerfile or profile.has_compose:
            if self.logger:
                self.logger.step("依赖已在 Docker 镜像构建时安装")
            return True

        # 否则需要在容器内安装
        if isolation.container_id:
            return self._exec_in_container(isolation, self._build_install_cmd(profile))

        return True  # 模板构建时已包含基础依赖

    def _start_docker_service(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """启动 Docker 服务."""
        if profile.has_compose:
            return self._start_compose_service(isolation, profile)

        # 启动已有容器
        if isolation.container_id:
            result = subprocess.run(
                ["docker", "start", isolation.container_id],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                isolation.status = "running"
                if self.logger:
                    self.logger.success(f"容器 {isolation.container_id} 已启动")
                return True

            if self.logger:
                self.logger.error(f"容器启动失败: {result.stderr[:200]}")
            return False

        # 没有容器 ID，直接 docker run
        entry_point = profile.entry_point
        if not entry_point:
            if self.logger:
                self.logger.error("无法确定启动命令")
            return False

        return self._run_docker_container(isolation, profile, entry_point)

    def _start_compose_service(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """启动 docker-compose 服务."""
        if not profile.repo_path:
            return False

        try:
            result = subprocess.run(
                ["docker", "compose", "up", "-d"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(profile.repo_path),
            )
            if result.returncode == 0:
                isolation.status = "running"
                if self.logger:
                    self.logger.success("docker compose 服务已启动")
                return True

            if self.logger:
                self.logger.error(f"compose 启动失败: {result.stderr[:200]}")
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            if self.logger:
                self.logger.error(f"compose 启动异常: {e}")
            return False

    def _run_docker_container(self, isolation: IsolationResult, profile: ProjectProfile, cmd: str) -> bool:
        """docker run 启动容器."""
        run_args = [
            "--name", isolation.id,
            "--cpus", config.docker_cpu_limit,
            "--memory", config.docker_memory_limit,
            "--label", "xia-gao=true",
        ]

        # 端口映射（仅 localhost）
        for internal_port, mapped_port in isolation.ports.items():
            run_args.extend(["-p", f"127.0.0.1:{mapped_port}:{internal_port}"])

        # 环境变量
        for key, value in profile.env_vars.items():
            run_args.extend(["-e", f"{key}={value}"])

        # GPU
        if profile.gpu_needed:
            run_args.extend(["--gpus", "all"])

        # 工作目录挂载
        if profile.repo_path:
            run_args.extend(["-v", f"{profile.repo_path}:/workspace", "-w", "/workspace"])

        try:
            result = subprocess.run(
                ["docker", "run", "-d"] + run_args + [isolation.image_name or "ubuntu:22.04", cmd],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                isolation.container_id = result.stdout.strip()[:12]
                isolation.status = "running"
                if self.logger:
                    self.logger.success(f"容器 {isolation.container_id} 已启动")
                return True

            if self.logger:
                self.logger.error(f"docker run 失败: {result.stderr[:200]}")
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            if self.logger:
                self.logger.error(f"启动容器异常: {e}")
            return False

    def _exec_in_container(self, isolation: IsolationResult, cmd: str) -> bool:
        """在容器内执行命令."""
        if not isolation.container_id:
            return False

        try:
            result = subprocess.run(
                ["docker", "exec", isolation.container_id, "bash", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if self.logger:
                self.logger.command(cmd, result.stdout[:200] if result.returncode == 0 else result.stderr[:200])
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            if self.logger:
                self.logger.error("容器内命令执行超时")
            return False

    def _build_install_cmd(self, profile: ProjectProfile) -> str:
        """构建依赖安装命令."""
        cmds: list[str] = []

        if "python" in profile.tech_stack:
            # 检查 requirements.txt
            repo_path = Path(profile.repo_path) if profile.repo_path else Path()
            if (repo_path / "requirements.txt").exists():
                cmds.append("pip install -r requirements.txt")
            elif (repo_path / "pyproject.toml").exists():
                cmds.append("pip install .")

        if "node" in profile.tech_stack:
            cmds.append("npm install")

        if "go" in profile.tech_stack:
            cmds.append("go mod download")

        return " && ".join(cmds) if cmds else "echo 'No dependencies to install'"

    # --- Conda 方式 ---

    def _install_deps_conda(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """Conda 方式安装依赖."""
        if not isolation.env_name:
            return False

        repo_path = profile.repo_path or ""
        cmds: list[str] = []

        if "python" in profile.tech_stack:
            req_file = Path(repo_path) / "requirements.txt"
            if req_file.exists():
                cmds.append(f"conda run -n {isolation.env_name} pip install -r {req_file}")

        cmd = " && ".join(cmds) if cmds else ""
        if not cmd:
            return True

        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            if self.logger:
                self.logger.command(cmd)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            if self.logger:
                self.logger.error("Conda 安装依赖超时")
            return False

    def _start_conda_service(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """Conda 方式启动服务."""
        if not isolation.env_name or not profile.entry_point:
            return False

        cmd = f"conda run -n {isolation.env_name} {profile.entry_point}"
        try:
            subprocess.Popen(cmd, shell=True, cwd=profile.repo_path)
            isolation.status = "running"
            if self.logger:
                self.logger.success(f"Conda 服务已启动: {profile.entry_point}")
            return True
        except (OSError, subprocess.SubprocessError) as e:
            if self.logger:
                self.logger.error(f"启动服务异常: {e}")
            return False

    # --- venv 方式 ---

    def _install_deps_venv(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """venv 方式安装依赖."""
        venv_path = Path(isolation.workspace) / "venv"
        pip_path = venv_path / "bin" / "pip"
        # Windows: venv_path / "Scripts" / "pip.exe"
        if not pip_path.exists():
            pip_path = venv_path / "Scripts" / "pip.exe"

        if "python" in profile.tech_stack:
            req_file = Path(profile.repo_path) / "requirements.txt"
            if req_file.exists():
                try:
                    result = subprocess.run(
                        [str(pip_path), "install", "-r", str(req_file)],
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    if self.logger:
                        self.logger.command(f"pip install -r requirements.txt")
                    return result.returncode == 0
                except subprocess.TimeoutExpired:
                    return False

        return True

    def _start_venv_service(self, isolation: IsolationResult, profile: ProjectProfile) -> bool:
        """venv 方式启动服务."""
        if not profile.entry_point:
            return False

        venv_path = Path(isolation.workspace) / "venv"
        python_path = venv_path / "bin" / "python"
        if not python_path.exists():
            python_path = venv_path / "Scripts" / "python.exe"

        cmd = f"{python_path} {profile.entry_point}"
        try:
            subprocess.Popen(cmd, shell=True, cwd=profile.repo_path)
            isolation.status = "running"
            if self.logger:
                self.logger.success(f"venv 服务已启动: {profile.entry_point}")
            return True
        except (OSError, subprocess.SubprocessError) as e:
            if self.logger:
                self.logger.error(f"启动服务异常: {e}")
            return False

    # --- 辅助方法 ---

    def _collect_logs(self, isolation: IsolationResult) -> str:
        """收集部署日志."""
        if isolation.method == "docker" and isolation.container_id:
            try:
                result = subprocess.run(
                    ["docker", "logs", isolation.container_id],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.stdout + result.stderr
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return ""

        # 读取本地日志文件
        log_file = Path(isolation.workspace) / "deploy.log"
        if log_file.exists():
            return log_file.read_text(encoding="utf-8", errors="ignore")

        return ""