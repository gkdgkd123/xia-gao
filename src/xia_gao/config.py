"""配置管理模块."""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """虾搞配置."""

    # 工作目录
    workspace: Path = Path.home() / ".xia-gao"

    # 端口范围
    port_start: int = 3000
    port_end: int = 9999

    # Docker 配置
    docker_cpu_limit: str = "1.0"
    docker_memory_limit: str = "2g"
    docker_timeout: int = 300

    # 健康检查配置
    health_check_initial_delay: int = 5
    health_check_interval: int = 3
    health_check_max_wait: int = 30

    # 修复配置
    repair_max_attempts: int = 3

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量加载配置."""
        workspace = os.getenv("XIA_GAO_WORKSPACE")
        return cls(
            workspace=Path(workspace) if workspace else Path.home() / ".xia-gao",
            port_start=int(os.getenv("XIA_GAO_PORT_START", "3000")),
            port_end=int(os.getenv("XIA_GAO_PORT_END", "9999")),
            docker_cpu_limit=os.getenv("XIA_GAO_DOCKER_CPU", "1.0"),
            docker_memory_limit=os.getenv("XIA_GAO_DOCKER_MEMORY", "2g"),
            log_level=os.getenv("XIA_GAO_LOG_LEVEL", "INFO"),
        )

    def ensure_workspace(self) -> None:
        """确保工作目录存在."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "deployments").mkdir(exist_ok=True)
        (self.workspace / "logs").mkdir(exist_ok=True)
        (self.workspace / "cache").mkdir(exist_ok=True)


# 全局配置实例
config = Config.from_env()
