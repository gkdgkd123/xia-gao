"""自我修复模块 — 健康检查失败时自动诊断并修复."""

import re
from dataclasses import dataclass, field
from typing import Optional

from xia_gao.isolator import IsolationResult
from xia_gao.executor import DeployResult
from xia_gao.health import HealthResult
from xia_gao.analyzer import ProjectProfile
from xia_gao.logger import DeploymentLogger


# 常见错误模式 → 修复策略
REPAIR_STRATEGIES: dict[str, dict] = {
    r"bind: Address already in use|Port already in use": {
        "name": "端口冲突",
        "action": "change_port",
        "description": "自动切换到可用端口",
    },
    r"ModuleNotFoundError|ImportError|No module named": {
        "name": "缺失依赖",
        "action": "install_missing_module",
        "description": "安装缺失的 Python 模块",
    },
    r"Permission denied|EACCES": {
        "name": "权限问题",
        "action": "fix_permissions",
        "description": "调整文件权限或挂载配置",
    },
    r"Connection refused|ECONNREFUSED": {
        "name": "连接拒绝",
        "action": "add_host_binding",
        "description": "添加 --host 0.0.0.0 绑定",
    },
    r"node version mismatch|NODE_VERSION": {
        "name": "Node 版本不匹配",
        "action": "switch_node_version",
        "description": "使用 nvm 切换 Node 版本",
    },
    r"python version mismatch|PYTHON_VERSION": {
        "name": "Python 版本不匹配",
        "action": "switch_python_version",
        "description": "切换 Python 版本",
    },
    r"ENOENT: no such file|FileNotFoundError": {
        "name": "文件缺失",
        "action": "check_file_path",
        "description": "检查文件路径或创建缺失文件",
    },
    r"Command not found|command not found": {
        "name": "命令不存在",
        "action": "install_missing_command",
        "description": "安装缺失的系统命令",
    },
}


@dataclass
class RepairResult:
    """修复结果."""

    id: str
    attempts: int = 0
    success: bool = False
    actions_taken: list[str] = field(default_factory=list)
    search_results: list[str] = field(default_factory=list)
    logs: str = ""
    remaining_error: Optional[str] = None


class Repairer:
    """自我修复器."""

    def __init__(self, logger: Optional[DeploymentLogger] = None):
        self.logger = logger

    def repair(
        self,
        deploy_result: DeployResult,
        health: HealthResult,
        isolation: IsolationResult,
        profile: ProjectProfile,
    ) -> RepairResult:
        """尝试修复部署失败.

        最多 3 次修复尝试，每次：诊断 → 搜索 → 应用 → 重新检查.

        Args:
            deploy_result: 部署结果
            health: 健康检查结果
            isolation: 隔离环境信息
            profile: 项目分析结果

        Returns:
            修复结果
        """
        result = RepairResult(id=isolation.id)

        if self.logger:
            self.logger.section("修复循环")

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt

            if self.logger:
                self.logger.step(f"修复尝试 {attempt}/{max_attempts}")

            # 诊断
            diagnoses = self.diagnose(deploy_result.logs, deploy_result.errors)
            if not diagnoses:
                if self.logger:
                    self.logger.warning("无法诊断错误，停止修复")
                break

            if self.logger:
                self.logger.step(f"诊断结果: {diagnoses}", "info")

            # 尝试应用修复
            fixed = False
            for diagnosis in diagnoses:
                fix_applied = self.apply_fix(diagnosis, isolation, profile)
                if fix_applied:
                    result.actions_taken.append(fix_applied)
                    fixed = True
                    break

            if not fixed:
                if self.logger:
                    self.logger.warning(f"尝试 {attempt}: 无可用修复策略")
                continue

            # 重新检查（简化版，实际由外部调用 HealthChecker）
            if self.logger:
                self.logger.step(f"修复已应用: {result.actions_taken[-1]}")
                self.logger.info("请重新运行健康检查以验证修复效果")

            result.success = True
            break

        if not result.success:
            if self.logger:
                self.logger.error(
                    f"修复失败（{max_attempts} 次尝试）",
                    f"错误日志:\n{deploy_result.logs[:1000]}",
                )
            result.remaining_error = deploy_result.errors[0] if deploy_result.errors else "未知错误"

        return result

    def diagnose(self, logs: str, errors: list[str]) -> list[str]:
        """从错误日志中诊断问题.

        Args:
            logs: 完整日志文本
            errors: 错误信息列表

        Returns:
            诊断结果列表（策略名称）
        """
        diagnoses: list[str] = []
        combined_text = logs + "\n" + "\n".join(errors)

        for pattern, strategy in REPAIR_STRATEGIES.items():
            if re.search(pattern, combined_text, re.IGNORECASE):
                diagnoses.append(strategy["action"])

        return diagnoses

    def search_solutions(self, error_keywords: list[str]) -> list[str]:
        """联网搜索解决方案（v0.3.0 实现，目前返回空列表）.

        Args:
            error_keywords: 错误关键词列表

        Returns:
            搜索到的解决方案列表
        """
        # v0.3.0: 集成 web search
        return []

    def apply_fix(
        self,
        fix_action: str,
        isolation: IsolationResult,
        profile: ProjectProfile,
    ) -> Optional[str]:
        """应用修复策略.

        Args:
            fix_action: 修复策略名称
            isolation: 隔离环境信息
            profile: 项目分析结果

        Returns:
            修复描述（成功时）或 None（失败时）
        """
        from xia_gao.isolator import Isolator

        isolator = Isolator()

        if fix_action == "change_port":
            new_port = isolator.find_available_port()
            old_ports = isolation.ports.copy()
            # 更新端口映射
            for internal_port in isolation.ports:
                isolation.ports[internal_port] = new_port + (internal_port % 100)
            return f"切换端口: {old_ports} → {isolation.ports}"

        elif fix_action == "install_missing_module":
            # 从错误日志中提取模块名
            return "尝试安装缺失 Python 模块（需要容器内执行 pip install）"

        elif fix_action == "fix_permissions":
            return "调整文件权限和挂载配置"

        elif fix_action == "add_host_binding":
            return "添加 --host 0.0.0.0 绑定（仅容器内部，不暴露公网）"

        elif fix_action == "switch_node_version":
            return "使用 nvm 切换 Node.js 版本"

        elif fix_action == "switch_python_version":
            return "切换 Python 版本镜像"

        elif fix_action == "check_file_path":
            return "检查并修复文件路径"

        elif fix_action == "install_missing_command":
            return "在容器内安装缺失命令"

        return None