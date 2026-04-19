"""Tests for the HealthChecker module."""

import time
from unittest.mock import patch, MagicMock

import requests

from xia_gao.health import HealthChecker, HealthResult
from xia_gao.isolator import IsolationResult
from xia_gao.analyzer import ProjectProfile


class TestHealthResult:
    """Test HealthResult dataclass."""

    def test_default_values(self):
        result = HealthResult(id="xg-abc123")
        assert result.id == "xg-abc123"
        assert result.alive is False
        assert result.port_open is False
        assert result.http_ok is None

    def test_successful_check(self):
        result = HealthResult(
            id="xg-abc123",
            alive=True,
            port_open=True,
            http_ok=True,
            response_time_ms=42.5,
        )
        assert result.alive is True
        assert result.port_open is True
        assert result.http_ok is True


class TestHealthChecker:
    """Test HealthChecker class."""

    def setup_method(self):
        self.checker = HealthChecker()

    def test_check_port_available(self):
        # 高端口通常空闲
        result = self.checker.check_port(9999)
        assert isinstance(result, bool)

    @patch("xia_gao.health.requests.get")
    @patch("xia_gao.health.time.time")
    def test_check_http_success(self, mock_time, mock_get):
        mock_time.side_effect = [0.0, 0.1]  # start, end
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        isolation = IsolationResult(id="xg-abc", method="docker", ports={80: 3456})
        success, time_ms = self.checker.check_http(isolation)
        assert success is True
        assert time_ms > 0

    @patch("xia_gao.health.requests.get")
    def test_check_http_failure(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Connection error")

        isolation = IsolationResult(id="xg-abc", method="docker", ports={80: 3456})
        success, time_ms = self.checker.check_http(isolation)
        assert success is False

    @patch("xia_gao.health.subprocess.run")
    def test_check_docker_process_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
        isolation = IsolationResult(id="xg-abc", method="docker", container_id="abc")
        assert self.checker._check_docker_process(isolation) is True

    @patch("xia_gao.health.subprocess.run")
    def test_check_docker_process_stopped(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="false\n")
        isolation = IsolationResult(id="xg-abc", method="docker", container_id="abc")
        assert self.checker._check_docker_process(isolation) is False