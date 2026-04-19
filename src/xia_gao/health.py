"""健康检查 — 部署后自动验证服务是否正常运行."""

import socket
import subprocess
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

import requests

from xia_gao.analyzer import ProjectProfile
from xia_gao.config import config
from xia_gao.isolator import IsolationResult
from xia_gao.logger import DeploymentLogger


@dataclass
class HealthResult:
    """健康检查结果."""

    id: str
    alive: bool = False             # 进程存活
    port_open: bool = False         # 端口可访问
    http_ok: Optional[bool] = None  # HTTP 200（仅 HTTP 服务）
    response_time_ms: Optional[float] = None
    error_details: Optional[str] = None


class HealthChecker:
    """健康检查器."""

    def __init__(self, logger: Optional[DeploymentLogger] = None):
        self.logger = logger

    def check(self, isolation: IsolationResult, profile: ProjectProfile) -> HealthResult:
        """执行健康检查: 进程 → 端口 → HTTP.

        启动后等待 5s，逐步检查（进程→端口→HTTP），每步间隔 3s，最多等待 30s。
        """
        result = HealthResult(id=isolation.id)

        if self.logger:
            self.logger.step("健康检查...")

        # 初始等待
        if self.logger:
            self.logger.step(f"等待服务启动 ({config.health_check_initial_delay}s)...")
        time.sleep(config.health_check_initial_delay)

        elapsed = 0
        max_wait = config.health_check_max_wait

        while elapsed < max_wait:
            # 1. 进程检查
            result.alive = self.check_process(isolation)
            if result.alive:
                if self.logger:
                    self.logger.step("进程存活 ✅")
            else:
                if self.logger:
                    self.logger.step("进程未启动 ❌")
                time.sleep(config.health_check_interval)
                elapsed += config.health_check_interval
                continue

            # 2. 端口检查
            result.port_open = self.check_ports(isolation)
            if result.port_open:
                if self.logger:
                    self.logger.step("端口可访问 ✅")
            else:
                if self.logger:
                    self.logger.step("端口未开放 ❌")
                time.sleep(config.health_check_interval)
                elapsed += config.health_check_interval
                continue

            # 3. HTTP 检查（仅 HTTP 服务）
            if isolation.ports:
                result.http_ok, result.response_time_ms = self.check_http(isolation)
                if result.http_ok:
                    if self.logger:
                        self.logger.step(f"HTTP 响应正常 ✅ ({result.response_time_ms:.1f}ms)")
                else:
                    if self.logger:
                        self.logger.step("HTTP 响应异常 ❌")
                    # HTTP 检查失败但端口开放，可能不是 HTTP 服务
                    # 不继续循环，视为端口服务已启动

            # 任意一项成功就返回
            if result.alive or result.port_open:
                return result

            time.sleep(config.health_check_interval)
            elapsed += config.health_check_interval

        # 超时
        result.error_details = f"健康检查超时 ({max_wait}s)"
        if self.logger:
            self.logger.error(result.error_details)

        return result

    def check_port(self, port: int) -> bool:
        """检查单个端口是否可访问."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            try:
                s.connect(("127.0.0.1", port))
                return True
            except (socket.timeout, ConnectionRefusedError, OSError):
                return False

    def check_http(self, isolation: IsolationResult) -> tuple[bool, float]:
        """检查 HTTP 服务响应.

        Returns:
            (是否 HTTP 200, 响应时间 ms)
        """
        if not isolation.ports:
            return (False, 0.0)

        # 取第一个端口作为主服务端口
        mapped_port = list(isolation.ports.values())[0]
        url = f"http://127.0.0.1:{mapped_port}"

        try:
            start = time.time()
            response = requests.get(url, timeout=5, allow_redirects=True)
            elapsed_ms = (time.time() - start) * 1000

            if response.status_code < 400:
                return (True, elapsed_ms)
            return (False, elapsed_ms)
        except (requests.ConnectionError, requests.Timeout, requests.RequestException):
            return (False, 0.0)

    def check_process(self, isolation: IsolationResult) -> bool:
        """检查进程是否存活."""
        if isolation.method == "docker" and isolation.container_id:
            return self._check_docker_process(isolation)
        elif isolation.method == "conda" or isolation.method == "venv":
            # 非 Docker 方式，通过端口间接检查进程
            return self.check_ports(isolation)
        return False

    def check_ports(self, isolation: IsolationResult) -> bool:
        """检查所有映射端口是否可访问."""
        if not isolation.ports:
            return False

        for mapped_port in isolation.ports.values():
            if self.check_port(mapped_port):
                return True
        return False

    # --- 内部方法 ---

    def _check_docker_process(self, isolation: IsolationResult) -> bool:
        """检查 Docker 容器进程是否存活."""
        import subprocess

        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", isolation.container_id or ""],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() == "true"
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False