"""Tests for the Cleaner module."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from xia_gao.cleaner import Cleaner, CleanResult
from xia_gao.isolator import IsolationResult


class TestCleanResult:
    """Test CleanResult dataclass."""

    def test_default_values(self):
        result = CleanResult(id="xg-abc123", success=True)
        assert result.id == "xg-abc123"
        assert result.success is True
        assert result.resources_removed == []

    def test_with_resources(self):
        result = CleanResult(
            id="xg-abc123",
            success=True,
            resources_removed=["container abc123", "image xia-gao/test"],
        )
        assert len(result.resources_removed) == 2


class TestCleaner:
    """Test Cleaner class."""

    def setup_method(self):
        self.cleaner = Cleaner()

    @patch("xia_gao.cleaner.subprocess.run")
    def test_stop_docker_service(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        isolation = IsolationResult(id="xg-abc", method="docker", container_id="abc")
        assert self.cleaner.stop_service(isolation) is True

    @patch("xia_gao.cleaner.subprocess.run")
    def test_stop_docker_service_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="container not found")
        isolation = IsolationResult(id="xg-abc", method="docker", container_id="abc")
        assert self.cleaner.stop_service(isolation) is False

    def test_stop_conda_service(self):
        isolation = IsolationResult(id="xg-abc", method="conda", env_name="xg_test")
        result = self.cleaner.stop_service(isolation)
        assert result is True  # Conda 不需要显式停止

    def test_stop_venv_service(self):
        isolation = IsolationResult(id="xg-abc", method="venv", env_name="/tmp/venv")
        result = self.cleaner.stop_service(isolation)
        assert result is True  # venv 不需要显式停止

    @patch("xia_gao.cleaner.subprocess.run")
    def test_remove_docker_container(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        isolation = IsolationResult(id="xg-abc", method="docker", container_id="abc")
        assert self.cleaner.remove_environment(isolation) is True

    @patch("xia_gao.cleaner.subprocess.run")
    def test_remove_conda_env(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        isolation = IsolationResult(id="xg-abc", method="conda", env_name="xg_test")
        assert self.cleaner.remove_environment(isolation) is True

    def test_remove_venv_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_path = Path(tmpdir) / "venv"
            venv_path.mkdir()
            (venv_path / "pyvenv.cfg").write_text("home = /usr/bin")
            isolation = IsolationResult(id="xg-abc", method="venv", env_name=str(venv_path))
            assert self.cleaner.remove_environment(isolation) is True

    @patch("xia_gao.cleaner.subprocess.run")
    def test_full_cleanup(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            isolation = IsolationResult(
                id="xg-abc",
                method="docker",
                container_id="abc",
                workspace=tmpdir,
            )
            result = self.cleaner.cleanup(isolation)
            assert isinstance(result, CleanResult)