"""清理恢复模块 — 停止服务、删除容器/环境、恢复宿主机."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xia_gao.config import config
from xia_gao.logger import DeploymentLogger
from xia_gao.isolator import IsolationResult


@dataclass
class CleanResult:
    """清理结果."""

    id: str
    success: bool
    resources_removed: list[str] = field(default_factory=list)
    backup_location: Optional[str] = None
    logs: str = ""


class Cleaner:
    """清理恢复器."""

    def __init__(self, logger: Optional[DeploymentLogger] = None):
        self.logger = logger

    def cleanup(self, isolation: IsolationResult) -> CleanResult:
        """一键清理部署环境."""
        result = CleanResult(id=isolation.id, success=True)

        if self.logger:
            self.logger.section("清理环境")

        # 停止服务
        if not self.stop_service(isolation):
            result.success = False
            if self.logger:
                self.logger.warning(f"停止服务失败，继续清理其他资源")

        # 删除容器/环境
        if not self.remove_environment(isolation):
            result.success = False

        # 清理工作目录
        workspace = Path(isolation.workspace)
        if workspace.exists():
            removed = f"workspace: {workspace}"
            try:
                # 保留日志，删除其他
                log_dir = config.workspace / "logs" / isolation.id
                if log_dir.exists():
                    result.backup_location = str(log_dir)

                import shutil
                shutil.rmtree(workspace, ignore_errors=True)
                result.resources_removed.append(removed)
                if self.logger:
                    self.logger.success(f"已清理 {removed}")
            except OSError as e:
                result.success = False
                if self.logger:
                    self.logger.error(f"清理工作目录失败: {e}")

        # 清理缓存（如果不再需要）
        cache_dir = config.workspace / "cache"
        if cache_dir.exists():
            # 不自动删除缓存，用户可能还需要
            pass

        if self.logger:
            if result.success:
                self.logger.success("环境清理完成，宿主机已恢复")
            else:
                self.logger.warning("部分清理失败，请手动检查残留资源")

        return result

    def stop_service(self, isolation: IsolationResult) -> bool:
        """停止运行中的服务."""
        if isolation.method in ("docker", "docker-compose") and isolation.container_id:
            if self.logger:
                self.logger.step(f"停止容器 {isolation.container_id}")
            try:
                result = subprocess.run(
                    ["docker", "stop", isolation.id],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    if self.logger:
                        self.logger.success(f"容器 {isolation.id} 已停止")
                    return True
                if self.logger:
                    self.logger.error(f"停止容器失败: {result.stderr}")
                return False
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                if self.logger:
                    self.logger.error(f"停止容器异常: {e}")
                return False

        elif isolation.method == "conda" and isolation.env_name:
            if self.logger:
                self.logger.step(f"停用 Conda 环境 {isolation.env_name}")
            # Conda 环境不需要显式停止，只需标记
            isolation.status = "stopped"
            return True

        elif isolation.method == "venv":
            isolation.status = "stopped"
            return True

        return True

    def remove_environment(self, isolation: IsolationResult) -> bool:
        """删除容器或虚拟环境."""
        if isolation.method in ("docker", "docker-compose") and isolation.container_id:
            if self.logger:
                self.logger.step(f"删除容器 {isolation.container_id}")
            try:
                # 删除容器
                rm_result = subprocess.run(
                    ["docker", "rm", "-f", isolation.id],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if rm_result.returncode == 0:
                    if self.logger:
                        self.logger.success(f"容器 {isolation.id} 已删除")
                    return True
                if self.logger:
                    self.logger.error(f"删除容器失败: {rm_result.stderr}")
                return False
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                if self.logger:
                    self.logger.error(f"删除容器异常: {e}")
                return False

        elif isolation.method == "conda" and isolation.env_name:
            if self.logger:
                self.logger.step(f"删除 Conda 环境 {isolation.env_name}")
            try:
                result = subprocess.run(
                    ["conda", "env", "remove", "-n", isolation.env_name, "-y"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    if self.logger:
                        self.logger.success(f"Conda 环境 {isolation.env_name} 已删除")
                    return True
                if self.logger:
                    self.logger.error(f"删除 Conda 环境失败: {result.stderr}")
                return False
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                if self.logger:
                    self.logger.error(f"删除 Conda 环境异常: {e}")
                return False

        elif isolation.method == "venv" and isolation.env_name:
            venv_path = Path(isolation.env_name)
            if venv_path.exists():
                import shutil
                try:
                    shutil.rmtree(venv_path)
                    if self.logger:
                        self.logger.success(f"venv {venv_path} 已删除")
                    return True
                except OSError as e:
                    if self.logger:
                        self.logger.error(f"删除 venv 失败: {e}")
                    return False

        return True

    def backup_data(self, isolation: IsolationResult) -> Optional[str]:
        """备份数据（如容器内的重要文件）."""
        if isolation.method == "docker" and isolation.container_id:
            backup_dir = config.workspace / "logs" / isolation.id / "backup"
            backup_dir.mkdir(parents=True, exist_ok=True)

            try:
                # 从容器中拷贝关键文件
                result = subprocess.run(
                    [
                        "docker",
                        "cp",
                        f"{isolation.id}:/workspace/.",
                        str(backup_dir),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    if self.logger:
                        self.logger.success(f"数据已备份到 {backup_dir}")
                    return str(backup_dir)
                if self.logger:
                    self.logger.warning(f"备份失败（容器可能已停止）: {result.stderr}")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                if self.logger:
                    self.logger.warning("备份异常")

        return None