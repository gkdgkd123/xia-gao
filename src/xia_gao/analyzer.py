"""项目分析器 — 克隆/扫描项目，输出 project-profile.json."""

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from xia_gao.config import config
from xia_gao.logger import DeploymentLogger


@dataclass
class ProjectProfile:
    """项目技术栈分析结果."""

    url: str
    tech_stack: list[str] = field(default_factory=list)
    has_dockerfile: bool = False
    has_compose: bool = False
    has_makefile: bool = False
    language_versions: dict = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    entry_point: str = ""
    ports: list[int] = field(default_factory=list)
    env_vars: dict = field(default_factory=dict)
    database_needed: bool = False
    gpu_needed: bool = False
    repo_path: str = ""
    project_name: str = ""


# 文件名 → 技术栈映射
STACK_DETECTORS: dict[str, list[str]] = {
    "Dockerfile": ["docker"],
    "docker-compose.yml": ["docker", "compose"],
    "docker-compose.yaml": ["docker", "compose"],
    "requirements.txt": ["python"],
    "setup.py": ["python"],
    "pyproject.toml": ["python"],
    "Pipfile": ["python"],
    "package.json": ["node"],
    "go.mod": ["go"],
    "Cargo.toml": ["rust"],
    "Makefile": ["make"],
    "Gemfile": ["ruby"],
    "pom.xml": ["java"],
    "build.gradle": ["java"],
}

# 内容关键词 → 端口/特征
PORT_PATTERNS: dict[str, list[int]] = {
    r"flask": [5000],
    r"uvicorn": [8000],
    r"fastapi": [8000],
    r"django": [8000],
    r"express": [3000],
    r"next": [3000],
    r"react": [3000],
    r"vue": [8080],
    r"nginx": [80],
    r"redis": [6379],
    r"postgres|postgresql": [5432],
    r"mysql|mariadb": [3306],
    r"mongo|mongodb": [27017],
}

GPU_INDICATORS: list[str] = ["cuda", "nvidia", "gpu", "torch.cuda", "tensorflow.gpu"]


class Analyzer:
    """项目分析器."""

    def __init__(self, logger: Optional[DeploymentLogger] = None):
        self.logger = logger

    def analyze(self, url: str) -> ProjectProfile:
        """分析 GitHub 项目，输出 ProjectProfile.

        Args:
            url: GitHub 项目 URL

        Returns:
            项目技术栈分析结果
        """
        profile = ProjectProfile(url=url)
        project_name = self._extract_project_name(url)
        profile.project_name = project_name

        if self.logger:
            self.logger.section("第一阶段: 分析与规划")
            self.logger.step(f"分析项目 {url}")

        # 克隆项目到临时目录
        repo_path = self._clone_repo(url, project_name)
        if not repo_path:
            if self.logger:
                self.logger.error(f"克隆项目失败: {url}")
            return profile
        profile.repo_path = str(repo_path)

        if self.logger:
            self.logger.step(f"项目已克隆到 {repo_path}")

        # 检测技术栈
        profile.tech_stack = self.detect_language(repo_path)
        profile.has_dockerfile = self.detect_dockerfile(repo_path)
        profile.has_compose = self.detect_compose(repo_path)
        profile.has_makefile = self.detect_makefile(repo_path)

        if self.logger:
            self.logger.step(f"检测到技术栈: {profile.tech_stack}", "info")

        # 提取端口
        profile.ports = self.extract_ports(repo_path)
        if profile.ports:
            if self.logger:
                self.logger.step(f"需要端口: {profile.ports}")

        # 提取环境变量
        profile.env_vars = self.extract_env_vars(repo_path)

        # 推断入口点
        profile.entry_point = self.guess_entry_point(repo_path, profile)

        # 检测 GPU 需求
        profile.gpu_needed = self._detect_gpu_needs(repo_path)

        # 检测数据库需求
        profile.database_needed = self._detect_database_needs(repo_path, profile)

        # 提取语言版本
        profile.language_versions = self._detect_language_versions(repo_path, profile)

        # 提取核心依赖
        profile.dependencies = self._extract_dependencies(repo_path, profile)

        # 保存 profile JSON
        self._save_profile(profile)

        if self.logger:
            self.logger.success(f"项目分析完成: {profile.tech_stack}")

        return profile

    def detect_dockerfile(self, repo_path: str) -> bool:
        """检测项目是否有 Dockerfile."""
        return any(Path(repo_path).glob("Dockerfile*"))

    def detect_compose(self, repo_path: str) -> bool:
        """检测项目是否有 docker-compose 文件."""
        return (Path(repo_path) / "docker-compose.yml").exists() or (
            Path(repo_path) / "docker-compose.yaml"
        ).exists()

    def detect_makefile(self, repo_path: str) -> bool:
        """检测项目是否有 Makefile."""
        return bool(Path(repo_path / "Makefile").exists())

    def detect_language(self, repo_path: str) -> list[str]:
        """文件名启发式识别技术栈."""
        stacks: list[str] = []
        path = Path(repo_path)

        for filename, stack_names in STACK_DETECTORS.items():
            if path.glob(filename) or (path / filename).exists():
                stacks.extend(stack_names)

        # 去重保序
        seen: set[str] = set()
        result: list[str] = []
        for s in stacks:
            if s not in seen:
                seen.add(s)
                result.append(s)

        return result

    def extract_ports(self, repo_path: str) -> list[int]:
        """从项目文件中提取端口信息."""
        ports: list[int] = []

        # 从 Dockerfile 和 compose 文件提取 EXPOSE 和 ports
        for dockerfile in Path(repo_path).glob("Dockerfile*"):
            content = dockerfile.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"EXPOSE\s+(\d+)", content):
                ports.append(int(match.group(1)))

        for compose_file in ["docker-compose.yml", "docker-compose.yaml"]:
            compose_path = Path(repo_path) / compose_file
            if compose_path.exists():
                content = compose_path.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r"['\"]?(\d{4,5})['\"]?:\s*\d+", content):
                    ports.append(int(match.group(1)))

        # 从项目代码关键词推断端口
        for pattern_file in Path(repo_path).rglob("*"):
            if pattern_file.suffix in {".py", ".js", ".ts", ".go", ".yaml", ".yml", ".env"}:
                try:
                    content = pattern_file.read_text(encoding="utf-8", errors="ignore")
                    for pattern, default_ports in PORT_PATTERNS.items():
                        if re.search(pattern, content, re.IGNORECASE):
                            for p in default_ports:
                                if p not in ports:
                                    ports.append(p)
                except (OSError, UnicodeDecodeError):
                    continue

        return ports

    def extract_env_vars(self, repo_path: str) -> dict:
        """从项目文件中提取环境变量需求."""
        env_vars: dict = {}

        # .env.example / .env.template
        for env_file in Path(repo_path).glob(".env*"):
            if env_file.name == ".env":
                continue  # 不读取实际 .env（安全）
            try:
                content = env_file.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip()
            except (OSError, UnicodeDecodeError):
                continue

        # docker-compose 中的 environment 字段
        for compose_file in ["docker-compose.yml", "docker-compose.yaml"]:
            compose_path = Path(repo_path) / compose_file
            if compose_path.exists():
                try:
                    content = compose_path.read_text(encoding="utf-8", errors="ignore")
                    for match in re.finditer(r"(\w+):\s*[\"']?.+[\"']?", content):
                        key = match.group(1)
                        if key.isupper() or key.replace("_", "").isupper():
                            env_vars[key] = ""
                except (OSError, UnicodeDecodeError):
                    continue

        return env_vars

    def guess_entry_point(self, repo_path: str, profile: ProjectProfile) -> str:
        """推断项目入口点/启动命令."""
        path = Path(repo_path)

        # Python 项目
        if "python" in profile.tech_stack:
            for candidate in ["app.py", "main.py", "run.py", "server.py", "wsgi.py", "manage.py"]:
                if (path / candidate).exists():
                    return f"python {candidate}"

            # pyproject.toml 中的 scripts
            pyproject = path / "pyproject.toml"
            if pyproject.exists():
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                scripts_match = re.search(r"\[project\.scripts\]\s*\n(.+?)(?=\n\[|\Z)", content, re.DOTALL)
                if scripts_match:
                    return scripts_match.group(1).strip().split("=")[0].strip()

        # Node 项目
        if "node" in profile.tech_stack:
            package_json = path / "package.json"
            if package_json.exists():
                try:
                    pkg = json.loads(package_json.read_text(encoding="utf-8"))
                    if "scripts" in pkg:
                        if "start" in pkg["scripts"]:
                            return f"npm start"
                        if "dev" in pkg["scripts"]:
                            return f"npm run dev"
                except (json.JSONDecodeError, OSError):
                    pass

        # Go 项目
        if "go" in profile.tech_stack:
            return "go run ."

        # Docker 项目
        if "docker" in profile.tech_stack:
            if profile.has_compose:
                return "docker compose up"
            return "docker build -t {name} . && docker run {name}"

        return ""

    def _clone_repo(self, url: str, project_name: str) -> Optional[Path]:
        """克隆 GitHub 项目到本地."""
        clone_dir = config.workspace / "cache" / project_name
        clone_dir.mkdir(parents=True, exist_ok=True)

        if clone_dir.exists() and any(clone_dir.iterdir()):
            if self.logger:
                self.logger.step(f"项目已缓存，跳过克隆")
            return clone_dir

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", url, str(clone_dir)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                if self.logger:
                    self.logger.error(f"git clone 失败: {result.stderr}")
                return None
            return clone_dir
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            if self.logger:
                self.logger.error(f"克隆异常: {e}")
            return None

    def _extract_project_name(self, url: str) -> str:
        """从 GitHub URL 提取项目名称."""
        # https://github.com/user/project → project
        # git@github.com:user/project.git → project
        patterns = [
            r"github\.com/[^/]+/([^/]+)(?:\.git)?$",
            r"github\.com/[^/]+/([^/]+)/?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return url.rstrip("/").split("/")[-1].replace(".git", "")

    def _detect_gpu_needs(self, repo_path: str) -> bool:
        """检测项目是否需要 GPU."""
        for py_file in Path(repo_path).rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                for indicator in GPU_INDICATORS:
                    if indicator.lower() in content.lower():
                        return True
            except (OSError, UnicodeDecodeError):
                continue

        # Dockerfile 中 CUDA/nvidia 相关
        for dockerfile in Path(repo_path).glob("Dockerfile*"):
            content = dockerfile.read_text(encoding="utf-8", errors="ignore")
            if "nvidia" in content.lower() or "cuda" in content.lower():
                return True

        return False

    def _detect_database_needs(self, repo_path: str, profile: ProjectProfile) -> bool:
        """检测项目是否需要数据库."""
        db_indicators = ["postgres", "mysql", "mongodb", "redis", "sqlite", "database"]
        db_ports = {5432, 3306, 27017, 6379}

        # 端口检测
        for port in profile.ports:
            if port in db_ports:
                return True

        # compose 文件检测
        if profile.has_compose:
            for compose_file in ["docker-compose.yml", "docker-compose.yaml"]:
                compose_path = Path(repo_path) / compose_file
                if compose_path.exists():
                    content = compose_path.read_text(encoding="utf-8", errors="ignore")
                    for indicator in db_indicators:
                        if indicator in content.lower():
                            return True

        return False

    def _detect_language_versions(self, repo_path: str, profile: ProjectProfile) -> dict:
        """检测语言版本需求."""
        versions: dict = {}
        path = Path(repo_path)

        if "python" in profile.tech_stack:
            # runtime.txt / .python-version
            for vfile in ["runtime.txt", ".python-version"]:
                vpath = path / vfile
                if vpath.exists():
                    content = vpath.read_text(encoding="utf-8", errors="ignore").strip()
                    versions["python"] = content.replace("python-", "")

            # pyproject.toml requires-python
            pyproject = path / "pyproject.toml"
            if pyproject.exists() and "python" not in versions:
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                match = re.search(r"requires-python\s*=\s*[\"'](.+?)[\"']", content)
                if match:
                    versions["python"] = match.group(1)

        if "node" in profile.tech_stack:
            package_json = path / "package.json"
            if package_json.exists():
                try:
                    pkg = json.loads(package_json.read_text(encoding="utf-8"))
                    if "engines" in pkg and "node" in pkg["engines"]:
                        versions["node"] = pkg["engines"]["node"]
                except (json.JSONDecodeError, OSError):
                    pass

            # .nvmrc / .node-version
            for vfile in [".nvmrc", ".node-version"]:
                vpath = path / vfile
                if vpath.exists() and "node" not in versions:
                    versions["node"] = vpath.read_text(encoding="utf-8", errors="ignore").strip()

        return versions

    def _extract_dependencies(self, repo_path: str, profile: ProjectProfile) -> list[str]:
        """提取核心依赖列表."""
        deps: list[str] = []
        path = Path(repo_path)

        if "python" in profile.tech_stack:
            req_file = path / "requirements.txt"
            if req_file.exists():
                content = req_file.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        deps.append(line)

        if "node" in profile.tech_stack:
            package_json = path / "package.json"
            if package_json.exists():
                try:
                    pkg = json.loads(package_json.read_text(encoding="utf-8"))
                    for dep_list in ["dependencies", "devDependencies"]:
                        if dep_list in pkg:
                            deps.extend(list(pkg[dep_list].keys()))
                except (json.JSONDecodeError, OSError):
                    pass

        return deps[:50]  # 限制数量，避免过长

    def _save_profile(self, profile: ProjectProfile) -> Path:
        """保存 profile 到 JSON 文件."""
        if profile.repo_path:
            profile_path = Path(profile.repo_path) / "project-profile.json"
        else:
            profile_path = config.workspace / "cache" / profile.project_name / "project-profile.json"

        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(asdict(profile), indent=2, ensure_ascii=False), encoding="utf-8")
        return profile_path