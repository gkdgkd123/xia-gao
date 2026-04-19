"""命令行入口 — xia-gao CLI."""

import json
import sys
import click
from rich.console import Console
from rich.table import Table

from xia_gao.analyzer import Analyzer
from xia_gao.isolator import Isolator
from xia_gao.executor import Executor
from xia_gao.health import HealthChecker
from xia_gao.repair import Repairer
from xia_gao.cleaner import Cleaner
from xia_gao.config import config
from xia_gao.logger import DeploymentLogger

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="xia-gao")
def main():
    """虾搞 (Xia-Gao) — 一键安全部署 GitHub 项目到隔离沙箱."""
    config.ensure_workspace()


@main.command()
@click.argument("url")
@click.option("--method", "-m", default=None, help="隔离方式: docker/conda/venv")
@click.option("--port", "-p", default=None, type=int, help="指定端口映射")
@click.option("--no-repair", default=False, is_flag=True, help="跳过自动修复")
@click.option("--gpu", default=False, is_flag=True, help="启用 GPU 支持")
def deploy(url, method, port, no_repair, gpu):
    """部署指定 GitHub 项目.

    Usage: xia-gao deploy https://github.com/user/project
    """
    console.print(f"\n🦐 虾搞 — 一键部署 {url}\n")

    # 创建部署日志
    analyzer = Analyzer()
    profile = analyzer.analyze(url)

    if not profile.repo_path:
        console.print("[red]项目分析失败[/red]")
        sys.exit(1)

    # 生成部署 ID
    deploy_id = Isolator().generate_id(profile.project_name)
    dep_logger = DeploymentLogger(deploy_id)

    # 用户确认关键决策
    if profile.database_needed:
        console.print(f"[yellow]⚠ 检测到项目需要数据库 ({profile.tech_stack})[/yellow]")
        if not click.confirm("是否在沙箱中一起部署数据库?"):
            console.print("[red]缺少数据库，项目可能无法正常运行[/red]")

    if profile.gpu_needed and not gpu:
        console.print("[yellow]⚠ 检测到项目可能需要 GPU[/yellow]")
        if click.confirm("是否启用 GPU 支持?"):
            gpu = True

    # 强制指定隔离方式
    if method:
        console.print(f"[blue]使用指定隔离方式: {method}[/blue]")

    # 保存部署信息
    dep_info_path = config.workspace / "deployments" / deploy_id / "deployment_info.json"
    dep_info_path.parent.mkdir(parents=True, exist_ok=True)

    # 创建隔离环境
    isolator = Isolator(dep_logger)
    if method:
        # 强制使用指定方式
        original_method = isolator.select_method(profile)
        console.print(f"[blue]指定方式: {method} (自动推荐: {original_method})[/blue]")

    isolation = isolator.create(profile)

    if isolation.status == "failed":
        console.print("[red]隔离环境创建失败[/red]")
        sys.exit(1)

    # 执行部署
    executor = Executor(dep_logger)
    deploy_result = executor.deploy(profile, isolation)

    # 健康检查
    checker = HealthChecker(dep_logger)
    health = checker.check(isolation, profile)

    if not (health.alive or health.port_open or (health.http_ok or False)):
        # 自动修复
        if not no_repair:
            console.print("\n[yellow]⚠ 健康检查失败，开始自动修复[/yellow]\n")
            repairer = Repairer(dep_logger)
            repair_result = repairer.repair(deploy_result, health, isolation, profile)

            if repair_result.success:
                # 重新健康检查
                health = checker.check(isolation, profile)
            else:
                console.print("[red]自动修复失败[/red]")
                console.print(f"[red]建议手动检查: {dep_logger.log_file}[/red]")
                sys.exit(1)
        else:
            console.print("[red]健康检查失败（已跳过修复）[/red]")
            sys.exit(1)

    # 保存部署信息
    dep_info = {
        "id": deploy_id,
        "url": url,
        "project_name": profile.project_name,
        "method": isolation.method,
        "container_id": isolation.container_id,
        "ports": isolation.ports,
        "access_url": deploy_result.access_url,
        "status": "running",
        "created_at": deploy_result.started_at,
    }
    dep_info_path.write_text(json.dumps(dep_info, indent=2, ensure_ascii=False), encoding="utf-8")

    # 生成清理脚本
    cleanup_cmds = []
    if isolation.method == "docker" and isolation.container_id:
        cleanup_cmds.extend([
            f"docker stop {isolation.container_id}",
            f"docker rm {isolation.container_id}",
        ])
        if isolation.image_name:
            cleanup_cmds.append(f"docker rmi {isolation.image_name}")

    cleanup_script = dep_logger.generate_cleanup_script(cleanup_cmds)

    # 交付成果
    console.print("\n" + "=" * 50)
    console.print("🦐 部署完成!")
    console.print(f"🌐 访问地址: [green]{deploy_result.access_url}[/green]")
    console.print(f"🧹 清理命令: [yellow]xia-gao cleanup {deploy_id}[/yellow]")
    console.print(f"📋 部署日志: {dep_logger.log_file}")
    console.print(f"📝 部署方案: {dep_logger.plan_file}")
    console.print(f"🗑 一键清理: {cleanup_script}")
    console.print("=" * 50 + "\n")


@main.command()
@click.argument("deploy_id")
def status(deploy_id):
    """查看部署状态."""
    dep_info_path = config.workspace / "deployments" / deploy_id / "deployment_info.json"
    if not dep_info_path.exists():
        console.print(f"[red]部署 {deploy_id} 不存在[/red]")
        sys.exit(1)

    info = json.loads(dep_info_path.read_text(encoding="utf-8"))
    console.print(f"\n🦐 部署状态: {deploy_id}")
    console.print(f"  项目: {info.get('project_name', 'unknown')}")
    console.print(f"  方式: {info.get('method', 'unknown')}")
    console.print(f"  状态: {info.get('status', 'unknown')}")
    console.print(f"  地址: {info.get('access_url', 'none')}")

    # 实时检查容器状态
    container_id = info.get("container_id")
    if container_id:
        import subprocess
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                console.print(f"  容器: [green]{result.stdout.strip()}[/green]")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    console.print()


@main.command()
@click.argument("deploy_id")
def logs(deploy_id):
    """查看部署日志."""
    log_path = config.workspace / "logs" / deploy_id / "deploy.log"
    if not log_path.exists():
        console.print(f"[red]日志不存在: {deploy_id}[/red]")
        sys.exit(1)

    content = log_path.read_text(encoding="utf-8", errors="ignore")
    console.print(content)


@main.command()
@click.argument("deploy_id")
def repair(deploy_id):
    """手动触发修复."""
    dep_info_path = config.workspace / "deployments" / deploy_id / "deployment_info.json"
    if not dep_info_path.exists():
        console.print(f"[red]部署 {deploy_id} 不存在[/red]")
        sys.exit(1)

    info = json.loads(dep_info_path.read_text(encoding="utf-8"))
    console.print(f"[yellow]手动修复 {deploy_id}...[/yellow]")

    # 简化修复：重新检查并尝试重启
    container_id = info.get("container_id")
    if container_id:
        import subprocess
        try:
            # 检查容器状态
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip() != "running":
                # 重启容器
                subprocess.run(["docker", "restart", container_id], capture_output=True, timeout=30)
                console.print("[green]容器已重启[/green]")
            else:
                console.print("[yellow]容器正在运行，可能需要其他修复[/yellow]")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass


@main.command()
@click.argument("deploy_id")
@click.option("--backup", default=False, is_flag=True, help="清理前备份数据")
def cleanup(deploy_id, backup):
    """清理指定部署环境."""
    dep_info_path = config.workspace / "deployments" / deploy_id / "deployment_info.json"
    if not dep_info_path.exists():
        console.print(f"[red]部署 {deploy_id} 不存在[/red]")
        sys.exit(1)

    info = json.loads(dep_info_path.read_text(encoding="utf-8"))
    console.print(f"\n🦐 清理部署: {deploy_id}")

    # 构造 IsolationResult
    from xia_gao.isolator import IsolationResult
    isolation = IsolationResult(
        id=deploy_id,
        method=info.get("method", "docker"),
        container_id=info.get("container_id"),
        ports=info.get("ports", {}),
        workspace=str(config.workspace / "deployments" / deploy_id),
        image_name=info.get("image_name"),
    )

    dep_logger = DeploymentLogger(deploy_id)
    cleaner = Cleaner(dep_logger)

    # 可选备份
    if backup:
        backup_path = cleaner.backup_data(isolation)
        if backup_path:
            console.print(f"[blue]数据备份到: {backup_path}[/blue]")

    # 确认清理
    if not click.confirm(f"确认清理 {deploy_id}?"):
        console.print("[yellow]已取消[/yellow]")
        return

    result = cleaner.cleanup(isolation)
    if result.success:
        console.print("[green]清理完成! 环境恢复如初 ✅[/green]")
    else:
        console.print("[yellow]部分资源未完全清理[/yellow]")
        for resource in result.resources_removed:
            console.print(f"  已删除: {resource}")


@main.command("list")
def list_deployments():
    """列出所有活跃部署."""
    cleaner = Cleaner()
    deployments = cleaner.list_active_deployments()

    if not deployments:
        console.print("[yellow]没有活跃部署[/yellow]")
        return

    table = Table(title="🦐 虾搞活跃部署")
    table.add_column("ID/Name", style="cyan")
    table.add_column("Method", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Access URL")

    for dep in deployments:
        name = dep.get("name") or dep.get("id") or dep.get("container_id", "unknown")
        table.add_row(
            name,
            dep.get("method", "?"),
            dep.get("status", "?"),
            dep.get("access_url", "—"),
        )

    console.print(table)


if __name__ == "__main__":
    main()