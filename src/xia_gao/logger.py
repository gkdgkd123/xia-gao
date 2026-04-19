"""日志管理模块."""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

from xia_gao.config import config


console = Console()


def setup_logger(name: str, log_file: Optional[Path] = None) -> logging.Logger:
    """设置日志记录器.

    Args:
        name: 日志记录器名称
        log_file: 日志文件路径，None 则只输出到控制台

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.log_level))

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    # Rich 控制台处理器
    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_path=False,
        show_time=False,
    )
    rich_handler.setLevel(logging.INFO)
    logger.addHandler(rich_handler)

    # 文件处理器
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(config.log_format)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


class DeploymentLogger:
    """部署日志管理器."""

    def __init__(self, deployment_id: str):
        self.deployment_id = deployment_id
        self.log_dir = config.workspace / "logs" / deployment_id
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.log_dir / "deploy.log"
        self.plan_file = self.log_dir / "deploy_plan.md"
        self.profile_file = self.log_dir / "project-profile.json"

        self.logger = setup_logger(f"xia-gao.{deployment_id}", self.log_file)
        self._log_sections: list[str] = []

    def section(self, title: str) -> None:
        """记录章节标题."""
        self._log_sections.append(title)
        self.logger.info(f"\n{'=' * 50}")
        self.logger.info(f"  {title}")
        self.logger.info(f"{'=' * 50}")

    def step(self, description: str, status: Optional[str] = None) -> None:
        """记录步骤."""
        if status:
            self.logger.info(f"  [{status}] {description}")
        else:
            self.logger.info(f"  → {description}")

    def command(self, cmd: str, output: Optional[str] = None) -> None:
        """记录执行的命令."""
        self.logger.debug(f"$ {cmd}")
        if output:
            self.logger.debug(f"Output: {output[:500]}")  # 限制输出长度

    def error(self, message: str, details: Optional[str] = None) -> None:
        """记录错误."""
        self.logger.error(f"❌ {message}")
        if details:
            self.logger.error(f"   Details: {details}")

    def success(self, message: str) -> None:
        """记录成功."""
        self.logger.info(f"✅ {message}")

    def warning(self, message: str) -> None:
        """记录警告."""
        self.logger.warning(f"⚠️  {message}")

    def info(self, message: str) -> None:
        """记录信息."""
        self.logger.info(message)

    def generate_plan(self, content: str) -> Path:
        """生成部署方案文档."""
        self.plan_file.write_text(content, encoding="utf-8")
        return self.plan_file

    def generate_cleanup_script(self, commands: list[str]) -> Path:
        """生成清理脚本."""
        script_path = self.log_dir / "cleanup.sh"
        script_content = "#!/bin/bash\n# 虾搞清理脚本\n# 生成时间: " + datetime.now().isoformat() + "\n\n"
        script_content += f"# 部署 ID: {self.deployment_id}\n\n"
        script_content += "set -e\n\n"
        script_content += "echo '开始清理...'\n\n"

        for cmd in commands:
            script_content += f"echo '执行: {cmd}'\n"
            script_content += f"{cmd}\n\n"

        script_content += "echo '清理完成!'\n"

        script_path.write_text(script_content, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path
