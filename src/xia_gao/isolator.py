"""隔离环境管理 — Docker/Conda/venv 环境创建与管理."""

import hashlib
import json
import random
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xia_gao.analyzer import ProjectProfile
from xia_gao.config import config
from xia_gao.logger import DeploymentLogger


@dataclass
class IsolationResult:
    """隔离环境创建结果."""

    id: str
    method: str  # "docker" / "conda" / "venv"
    container_id: Optional[str] = None
    env_name: Optional[str] = None
    ports: dict = field(default_factory=dict)  # {内部端口: 映射端口}
    workspace: str = ""
    status: str = "created"  # "created" / "running" / "failed" / "stopped"
    image_name: Optional[str] = None


class Isolator:
    """隔离环境管理器."""

    def __init__(self, logger: Optional[DeploymentLogger] = None):
        self.logger = logger

    def generate_id(self, project_name: str) -> str:
        """生成部署 ID (xg-<hash6>)."""
        hash_input = f"{project_name}-{time.time()}-{random.randint(0, 9999)}"
        hash_str = hashlib.sha256(hash_input.encode()).hexdigest()[:6]
        return f"xg-{hash_str}"

    def select_method(self, profile: ProjectProfile) -> str:
        """根据项目 profile 选择隔离方案.

        优先级: Dockerfile → compose → Docker容器 → conda → venv
        """
        # 有 Dockerfile，直接用
        if profile.has_dockerfile:
            return "docker"

        # 有 compose，直接用
        if profile.has_compose:
            return "docker-compose"

        # 检查宿主机是否有 Docker
        if self._docker_available():
            return "docker"

        # 无 Docker，降级到 conda/venv
        if "python" in profile.tech_stack:
            if self._conda_available():
                return "conda"
            if self._python_available():
                return "venv"

        # 都没有，报错
        return "none"

    def create(self, profile: ProjectProfile) -> IsolationResult:
        """根据项目 profile 创建隔离环境."""
        deploy_id = self.generate_id(profile.project_name)
        method = self.select_method(profile)

        if self.logger:
            self.logger.section("第二阶段: 基建与隔离")
            self.logger.step(f"创建隔离沙箱 (方案: {method})")

        if method == "none":
            result = IsolationResult(id=deploy_id, method=method, status="failed")
            if self.logger:
                self.logger.error("无法创建隔离环境: 需要 Docker、Conda 或 Python")
            return result

        # 分配端口
        ports = self._allocate_ports(profile.ports)

        # 创建工作目录
        workspace = str(config.workspace / "deployments" / deploy_id)
        Path(workspace).mkdir(parents=True, exist_ok=True)

        result = IsolationResult(
            id=deploy_id, method=method, ports=ports, workspace=workspace, status="created"
        )

        if method in ("docker", "docker-compose"):
            result = self._create_docker_isolation(profile, result)
        elif method == "conda":
            result = self._create_conda_isolation(profile, result)
        elif method == "venv":
            result = self._create_venv_isolation(profile, result)

        if self.logger and result.status == "created":
            self.logger.success(f"隔离环境已创建: {result.id} ({result.method})")

        return result

    def start(self, isolation: IsolationResult) -> bool:
        """启动隔离环境."""
        if isolation.method == "docker":
            return self._start_docker_container(isolation)
        elif isolation.method == "conda":
            return self._start_conda_env(isolation)
        elif isolation.method == "venv":
            return self._start_venv_env(isolation)
        return False

    def stop(self, isolation: IsolationResult) -> bool:
        """停止隔离环境."""
        if isolation.container_id:
            try:
                subprocess.run(
                    ["docker", "stop", isolation.container_id],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                isolation.status = "stopped"
                return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return False
        return True

    def destroy(self, isolation: IsolationResult) -> bool:
        """销毁隔离环境."""
        if isolation.method in ("docker", "docker-compose") and isolation.container_id:
            try:
                subprocess.run(["docker", "rm", "-f", isolation.container_id], capture_output=True, timeout=30)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # 清理工作目录
        workspace = Path(isolation.workspace)
        if workspace.exists():
            try:
                import shutil
                shutil.rmtree(workspace)
            except OSError:
                pass

        isolation.status = "destroyed"
        return True

    def find_available_port(self, start: int = 3000) -> int:
        """查找可用端口."""
        for port in range(start, config.port_end):
            if self._port_available(port):
                return port
        return start  # fallback

    # --- Docker 隔离 ---

    def _create_docker_isolation(self, profile: ProjectProfile, result: IsolationResult) -> IsolationResult:
        """创建 Docker 隔离环境."""
        if profile.has_dockerfile:
            return self._create_from_dockerfile(profile, result)
        elif profile.has_compose:
            return self._create_from_compose(profile, result)
        else:
            return self._create_from_template(profile, result)

    def _create_from_dockerfile(self, profile: ProjectProfile, result: IsolationResult) -> IsolationResult:
        """从项目 Dockerfile 构建."""
        image_name = f"xia-gao/{profile.project_name}:{result.id}"
        result.image_name = image_name

        if self.logger:
            self.logger.step(f"构建 Docker 镜像: {image_name}")

        try:
            build_result = subprocess.run(
                [
                    "docker", "build",
                    "-t", image_name,
                    "-f", "Dockerfile",
                    str(profile.repo_path),
                ],
                capture_output=True,
                text=True,
                timeout=config.docker_timeout,
                cwd=str(profile.repo_path),
            )
            if build_result.returncode != 0:
                if self.logger:
                    self.logger.error(f"Docker build 失败: {build_result.stderr[:200]}")
                result.status = "failed"
                return result
        except subprocess.TimeoutExpired:
            if self.logger:
                self.logger.error(f"Docker build 超时 ({config.docker_timeout}s)")
            result.status = "failed"
            return result

        # 创建容器但不启动
        run_args = self._build_docker_run_args(profile, result)
        try:
            create_result = subprocess.run(
                ["docker", "create"] + run_args + [image_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if create_result.returncode == 0:
                result.container_id = create_result.stdout.strip()[:12]
                if self.logger:
                    self.logger.success(f"容器 {result.container_id} 已创建")
            else:
                if self.logger:
                    self.logger.error(f"docker create 失败: {create_result.stderr[:200]}")
                result.status = "failed"
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            if self.logger:
                self.logger.error(f"创建容器异常: {e}")
            result.status = "failed"

        return result

    def _create_from_compose(self, profile: ProjectProfile, result: IsolationResult) -> IsolationResult:
        """使用 docker-compose 创建."""
        result.image_name = f"xia-gao-compose/{profile.project_name}:{result.id}"

        if self.logger:
            self.logger.step("使用 docker-compose 创建多服务环境")

        # compose 会在 executor 中启动，这里只标记
        result.status = "created"
        return result

    def _create_from_template(self, profile: ProjectProfile, result: IsolationResult) -> IsolationResult:
        """使用预置 Docker 模板创建."""
        template = self._select_template(profile)
        image_name = f"xia-gao/{profile.project_name}:{result.id}"
        result.image_name = image_name

        if self.logger:
            self.logger.step(f"使用模板 {template} 创建沙箱")

        # 在工作目录生成定制 Dockerfile
        dockerfile_path = Path(result.workspace) / "Dockerfile"
        template_path = Path(__file__).parent.parent.parent / "docker" / template

        if template_path.exists():
            dockerfile_content = template_path.read_text(encoding="utf-8")
            # 添加项目代码挂载
            dockerfile_content += f"\nCOPY {profile.repo_path} /workspace\nWORKDIR /workspace\n"
            dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
        else:
            # 生成基础 Dockerfile
            dockerfile_content = self._generate_base_dockerfile(profile)
            dockerfile_path.write_text(dockerfile_content, encoding="utf-8")

        # 构建镜像
        try:
            build_result = subprocess.run(
                ["docker", "build", "-t", image_name, "-f", str(dockerfile_path), str(result.workspace)],
                capture_output=True,
                text=True,
                timeout=config.docker_timeout,
            )
            if build_result.returncode != 0:
                if self.logger:
                    self.logger.error(f"Docker build 失败: {build_result.stderr[:200]}")
                result.status = "failed"
                return result
        except subprocess.TimeoutExpired:
            if self.logger:
                self.logger.error(f"Docker build 超时")
            result.status = "failed"
            return result

        # 创建容器
        run_args = self._build_docker_run_args(profile, result)
        try:
            create_result = subprocess.run(
                ["docker", "create"] + run_args + [image_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if create_result.returncode == 0:
                result.container_id = create_result.stdout.strip()[:12]
                if self.logger:
                    self.logger.success(f"容器 {result.container_id} 已创建")
            else:
                result.status = "failed"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            result.status = "failed"

        return result

    def _build_docker_run_args(self, profile: ProjectProfile, result: IsolationResult) -> list[str]:
        """构建 docker run/create 参数."""
        args: list[str] = [
            "--name", result.id,
            "--cpus", config.docker_cpu_limit,
            "--memory", config.docker_memory_limit,
            "--label", "xia-gao=true",
            "--label", f"xia-gao-project={profile.project_name}",
        ]

        # 端口映射
        for internal_port, mapped_port in result.ports.items():
            args.extend(["-p", f"127.0.0.1:{mapped_port}:{internal_port}"])

        # GPU 支持（如果需要且可用）
        if profile.gpu_needed and self._nvidia_docker_available():
            args.extend(["--gpus", "all"])

        # 环境变量
        for key, value in profile.env_vars.items():
            args.extend(["-e", f"{key}={value}"])

        # 交互式
        args.extend(["-it"])

        # 自动删除（停止后自动清理容器，但保留镜像）
        # 不加 --rm，因为需要 container_id 用于后续操作

        return args

    def _start_docker_container(self, isolation: IsolationResult) -> bool:
        """启动 Docker 容器."""
        try:
            result = subprocess.run(
                ["docker", "start", isolation.container_id or isolation.id],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                isolation.status = "running"
                return True
            if self.logger:
                self.logger.error(f"启动容器失败: {result.stderr}")
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            if self.logger:
                self.logger.error(f"启动容器异常: {e}")
            return False

    # --- Conda 隔离 ---

    def _create_conda_isolation(self, profile: ProjectProfile, result: IsolationResult) -> IsolationResult:
        """创建 Conda 隔离环境."""
        env_name = f"xg_{profile.project_name}_{result.id.replace('-', '_')}"
        result.env_name = env_name

        if self.logger:
            self.logger.step(f"创建 Conda 环境: {env_name}")

        python_version = profile.language_versions.get("python", "3.10")

        try:
            create_result = subprocess.run(
                ["conda", "create", "-n", env_name, f"python={python_version}", "-y"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if create_result.returncode != 0:
                if self.logger:
                    self.logger.error(f"Conda 环境创建失败: {create_result.stderr[:200]}")
                result.status = "failed"
                return result

            if self.logger:
                self.logger.success(f"Conda 环境 {env_name} 已创建")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            if self.logger:
                self.logger.error(f"Conda 创建异常: {e}")
            result.status = "failed"

        return result

    def _start_conda_env(self, isolation: IsolationResult) -> bool:
        """激活 Conda 环境（标记为 running)."""
        isolation.status = "running"
        return True

    # --- venv 隔离 ---

    def _create_venv_isolation(self, profile: ProjectProfile, result: IsolationResult) -> IsolationResult:
        """创建 Python venv 隔离环境."""
        venv_path = str(Path(result.workspace) / "venv")
        result.env_name = venv_path

        if self.logger:
            self.logger.step(f"创建 venv 环境: {venv_path}")

        try:
            create_result = subprocess.run(
                ["python3", "-m", "venv", venv_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if create_result.returncode != 0:
                if self.logger:
                    self.logger.error(f"venv 创建失败: {create_result.stderr[:200]}")
                result.status = "failed"
                return result

            if self.logger:
                self.logger.success(f"venv 已创建: {venv_path}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            if self.logger:
                self.logger.error(f"venv 创建异常: {e}")
            result.status = "failed"

        return result

    def _start_venv_env(self, isolation: IsolationResult) -> bool:
        """激活 venv 环境（标记为 running)."""
        isolation.status = "running"
        return True

    # --- 辅助方法 ---

    def _docker_available(self) -> bool:
        """检查 Docker 是否可用."""
        try:
            result = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _conda_available(self) -> bool:
        """检查 Conda 是否可用."""
        try:
            result = subprocess.run(["conda", "--version"], capture_output=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _python_available(self) -> bool:
        """检查 Python3 是否可用."""
        try:
            result = subprocess.run(["python3", "--version"], capture_output=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Windows 用 python
            try:
                result = subprocess.run(["python", "--version"], capture_output=True, timeout=5)
                return result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return False

    def _nvidia_docker_available(self) -> bool:
        """检查 NVIDIA Docker 是否可用."""
        try:
            result = subprocess.run(["docker", "run", "--rm", "--gpus", "all", "nvidia/cuda:11.0-base", "nvidia-smi"], capture_output=True, timeout=30)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _port_available(self, port: int) -> bool:
        """检查端口是否可用."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _allocate_ports(self, needed_ports: list[int]) -> dict:
        """分配端口映射 {内部端口: 映射端口}."""
        allocated: dict = {}
        for internal_port in needed_ports:
            mapped_port = self.find_available_port(internal_port)
            allocated[internal_port] = mapped_port
            if self.logger and mapped_port != internal_port:
                self.logger.step(f"端口映射: {internal_port} → {mapped_port}")
        return allocated

    def _select_template(self, profile: ProjectProfile) -> str:
        """选择 Docker 模板."""
        if "python" in profile.tech_stack:
            return "python.Dockerfile"
        elif "node" in profile.tech_stack:
            return "node.Dockerfile"
        elif "go" in profile.tech_stack:
            return "base.Dockerfile"
        else:
            return "base.Dockerfile"

    def _generate_base_dockerfile(self, profile: ProjectProfile) -> str:
        """根据 profile 生成基础 Dockerfile."""
        lines = ["FROM ubuntu:22.04", "RUN apt-get update && apt-get install -y --no-install-recommends \\"]

        apt_packages = ["git", "curl", "ca-certificates"]
        if "python" in profile.tech_stack:
            apt_packages.extend(["python3", "python3-pip", "python3-venv"])
        if "node" in profile.tech_stack:
            apt_packages.extend(["nodejs", "npm"])

        lines.append("  " + " \\ \n  ".join(apt_packages) + " && rm -rf /var/lib/apt/lists/*")

        if "python" in profile.tech_stack:
            lines.append("RUN python3 -m pip install --no-cache-dir --upgrade pip")

        lines.extend([
            f"COPY {profile.repo_path} /workspace",
            "WORKDIR /workspace",
        ])

        return "\n".join(lines)