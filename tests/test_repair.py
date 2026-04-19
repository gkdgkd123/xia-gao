"""Tests for the Repairer module."""

from unittest.mock import patch, MagicMock

from xia_gao.repair import Repairer, RepairResult, REPAIR_STRATEGIES
from xia_gao.executor import DeployResult
from xia_gao.health import HealthResult
from xia_gao.isolator import IsolationResult
from xia_gao.analyzer import ProjectProfile


class TestRepairResult:
    """Test RepairResult dataclass."""

    def test_default_values(self):
        result = RepairResult(id="xg-abc123")
        assert result.attempts == 0
        assert result.success is False
        assert result.actions_taken == []

    def test_successful_repair(self):
        result = RepairResult(
            id="xg-abc123",
            attempts=1,
            success=True,
            actions_taken=["changed port 3000→3001"],
        )
        assert result.success is True
        assert len(result.actions_taken) == 1


class TestRepairer:
    """Test Repairer class."""

    def setup_method(self):
        self.repairer = Repairer()

    def test_diagnose_port_conflict(self):
        logs = "Error: bind: Address already in use for port 3000"
        diagnoses = self.repairer.diagnose(logs, [])
        assert "change_port" in diagnoses

    def test_diagnose_missing_module(self):
        logs = "ModuleNotFoundError: No module named 'fastapi'"
        diagnoses = self.repairer.diagnose(logs, [])
        assert "install_missing_module" in diagnoses

    def test_diagnose_permission_error(self):
        logs = "Permission denied: /workspace/data"
        diagnoses = self.repairer.diagnose(logs, [])
        assert "fix_permissions" in diagnoses

    def test_diagnose_connection_refused(self):
        logs = "Connection refused on port 5000"
        diagnoses = self.repairer.diagnose(logs, [])
        assert "add_host_binding" in diagnoses

    def test_diagnose_multiple_errors(self):
        logs = "Port already in use\nModuleNotFoundError: flask"
        diagnoses = self.repairer.diagnose(logs, [])
        assert len(diagnoses) >= 2

    def test_diagnose_unknown_error(self):
        logs = "Some random error message"
        diagnoses = self.repairer.diagnose(logs, [])
        assert len(diagnoses) == 0

    def test_apply_fix_change_port(self):
        isolation = IsolationResult(id="xg-abc", method="docker", ports={3000: 3000})
        profile = ProjectProfile(url="")

        fix_applied = self.repairer.apply_fix("change_port", isolation, profile)
        assert fix_applied is not None
        assert "切换端口" in fix_applied

    def test_search_solutions_returns_empty(self):
        # v0.1.0: 不联网搜索
        results = self.repairer.search_solutions(["port conflict"])
        assert results == []

    def test_repair_max_attempts(self):
        deploy_result = DeployResult(
            id="xg-abc",
            success=False,
            logs="Unknown error",
            errors=["Unknown error"],
        )
        health = HealthResult(id="xg-abc", alive=False, port_open=False)
        isolation = IsolationResult(id="xg-abc", method="docker")
        profile = ProjectProfile(url="")

        result = self.repairer.repair(deploy_result, health, isolation, profile)
        assert result.attempts >= 1