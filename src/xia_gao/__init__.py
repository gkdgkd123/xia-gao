"""虾搞 (Xia-Gao) — 一键安全部署 GitHub 项目到隔离沙箱."""

__version__ = "0.1.0"

from xia_gao.analyzer import Analyzer, ProjectProfile
from xia_gao.isolator import Isolator, IsolationResult
from xia_gao.executor import Executor, DeployResult
from xia_gao.health import HealthChecker, HealthResult
from xia_gao.repair import Repairer, RepairResult
from xia_gao.cleaner import Cleaner, CleanResult

__all__ = [
    "Analyzer",
    "ProjectProfile",
    "Isolator",
    "IsolationResult",
    "Executor",
    "DeployResult",
    "HealthChecker",
    "HealthResult",
    "Repairer",
    "RepairResult",
    "Cleaner",
    "CleanResult",
]