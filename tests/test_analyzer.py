"""Tests for the Analyzer module."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from xia_gao.analyzer import Analyzer, ProjectProfile, STACK_DETECTORS


class TestProjectProfile:
    """Test ProjectProfile dataclass."""

    def test_default_values(self):
        profile = ProjectProfile(url="https://github.com/user/project")
        assert profile.url == "https://github.com/user/project"
        assert profile.tech_stack == []
        assert profile.has_dockerfile is False
        assert profile.has_compose is False
        assert profile.project_name == ""

    def test_custom_values(self):
        profile = ProjectProfile(
            url="https://github.com/user/project",
            tech_stack=["python", "docker"],
            has_dockerfile=True,
            ports=[5000],
            project_name="project",
        )
        assert profile.tech_stack == ["python", "docker"]
        assert profile.has_dockerfile is True
        assert profile.ports == [5000]


class TestAnalyzer:
    """Test Analyzer class."""

    def setup_method(self):
        self.analyzer = Analyzer()

    def test_extract_project_name_from_https_url(self):
        name = self.analyzer._extract_project_name("https://github.com/user/my-project")
        assert name == "my-project"

    def test_extract_project_name_from_git_url(self):
        name = self.analyzer._extract_project_name("git@github.com:user/my-project.git")
        assert name == "my-project"

    def test_extract_project_name_with_trailing_slash(self):
        name = self.analyzer._extract_project_name("https://github.com/user/my-project/")
        assert name == "my-project"

    def test_detect_language_with_python_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Python project files
            Path(tmpdir, "requirements.txt").write_text("flask==2.0")
            Path(tmpdir, "app.py").write_text("from flask import Flask")

            stacks = self.analyzer.detect_language(tmpdir)
            assert "python" in stacks

    def test_detect_language_with_node_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "package.json").write_text(json.dumps({"name": "test"}))

            stacks = self.analyzer.detect_language(tmpdir)
            assert "node" in stacks

    def test_detect_language_with_docker_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "Dockerfile").write_text("FROM python:3.10")

            stacks = self.analyzer.detect_language(tmpdir)
            assert "docker" in stacks

    def test_detect_language_with_go_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "go.mod").write_text("module test")

            stacks = self.analyzer.detect_language(tmpdir)
            assert "go" in stacks

    def test_detect_dockerfile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "Dockerfile").write_text("FROM ubuntu")
            assert self.analyzer.detect_dockerfile(tmpdir) is True

    def test_detect_dockerfile_not_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert self.analyzer.detect_dockerfile(tmpdir) is False

    def test_detect_compose(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "docker-compose.yml").write_text("version: '3'")
            assert self.analyzer.detect_compose(tmpdir) is True

    def test_extract_env_vars_from_env_example(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, ".env.example").write_text("PORT=3000\nDB_HOST=localhost\n")
            env_vars = self.analyzer.extract_env_vars(tmpdir)
            assert "PORT" in env_vars
            assert env_vars["PORT"] == "3000"

    def test_guess_entry_point_python(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "app.py").write_text("from flask import Flask")
            profile = ProjectProfile(url="", tech_stack=["python"], repo_path=tmpdir)
            entry = self.analyzer.guess_entry_point(tmpdir, profile)
            assert "app.py" in entry

    def test_guess_entry_point_node(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = {"name": "test", "scripts": {"start": "node server.js"}}
            Path(tmpdir, "package.json").write_text(json.dumps(pkg))
            profile = ProjectProfile(url="", tech_stack=["node"], repo_path=tmpdir)
            entry = self.analyzer.guess_entry_point(tmpdir, profile)
            assert "npm start" in entry

    def test_detect_gpu_needs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "train.py").write_text("import torch.cuda")
            assert self.analyzer._detect_gpu_needs(tmpdir) is True

    def test_detect_gpu_needs_negative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "app.py").write_text("from flask import Flask")
            assert self.analyzer._detect_gpu_needs(tmpdir) is False

    @patch("xia_gao.analyzer.subprocess.run")
    def test_clone_repo_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = self.analyzer._clone_repo("https://github.com/user/test", "test")
        assert result is not None

    @patch("xia_gao.analyzer.subprocess.run")
    def test_clone_repo_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = self.analyzer._clone_repo("https://github.com/user/test", "test")
        assert result is None