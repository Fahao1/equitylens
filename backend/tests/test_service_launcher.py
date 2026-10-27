"""LaunchAgent lifecycle tests use temporary homes and mocked launchctl/HTTP only."""
import importlib.util
from pathlib import Path
import plistlib
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("equitylens_service", ROOT / "scripts/service.py")
service_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service_module)


class Launchctl:
    def __init__(self):
        self.loaded = False
        self.calls = []

    def __call__(self, args, **kwargs):
        assert args[0] == "/bin/launchctl"
        self.calls.append(args)
        command = args[1]
        if command == "print":
            return SimpleNamespace(returncode=0 if self.loaded else 113, stdout="state = running\n" if self.loaded else "", stderr="")
        if command == "bootstrap":
            assert Path(args[-1]).is_file()
            self.loaded = True
        if command == "bootout":
            self.loaded = False
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def service(tmp_path, monkeypatch):
    project = tmp_path / "Project with spaces & punctuation"
    for name in (".venv/bin/python", "frontend/node_modules/.bin/vite", "scripts/dev.sh", "backend/app/main.py"):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    node = tmp_path / "Node Tools/bin/node"
    node.parent.mkdir(parents=True)
    node.write_text("fixture")
    monkeypatch.setattr(service_module.shutil, "which", lambda name: str(node) if name == "node" else None)
    launchctl = Launchctl()
    controller = service_module.EquityLensService(project, tmp_path / "fixture-user", launchctl)
    monkeypatch.setattr(controller, "_macos", lambda: None)
    monkeypatch.setattr(controller, "_database_url", lambda: "sqlite:///./data/equitylens.db")
    monkeypatch.setattr(controller, "_ports_available", lambda: None)
    monkeypatch.setattr(controller, "_http_ready", lambda *args, **kwargs: True)
    return controller, launchctl


def test_prepare_is_project_only_private_and_preserves_exact_paths(service):
    controller, runner = service
    prepared = controller.prepare()
    assert prepared.is_relative_to(controller.root)
    assert not controller.installed.exists()
    config = plistlib.loads(prepared.read_bytes())
    assert config["ProgramArguments"] == ["/bin/bash", str(controller.runtime / "scripts/dev.sh")]
    assert config["WorkingDirectory"] == str(controller.runtime)
    assert not controller.runtime.exists()
    assert config["KeepAlive"] is True and config["RunAtLoad"] is True
    assert config["ThrottleInterval"] >= 10
    assert config["ExitTimeOut"] == 30
    assert set(config["EnvironmentVariables"]) == {"PATH", "PYTHONUNBUFFERED", "EQUITYLENS_SOURCE_ROOT"}
    assert config["EnvironmentVariables"]["EQUITYLENS_SOURCE_ROOT"] == str(controller.root)
    assert config["EnvironmentVariables"]["PATH"].split(":")[0].endswith("Node Tools/bin")
    assert prepared.stat().st_mode & 0o777 == 0o600
    assert not runner.calls


def test_install_start_is_single_supervised_job_and_stop_disables_autostart(service):
    controller, runner = service
    assert controller.install()["ready"] is True
    assert controller.installed.stat().st_mode & 0o777 == 0o600
    assert controller.start()["ready"] is True
    commands = [args[1] for args in runner.calls]
    assert commands.count("bootstrap") == 1
    assert commands.count("kickstart") == 1
    assert "bootout" not in commands
    controller.stop()
    commands = [args[1] for args in runner.calls]
    assert commands[-3:] == ["disable", "print", "bootout"]
    assert runner.loaded is False
    assert controller.status()["ready"] is False


def test_uninstall_preserves_project_data_and_only_removes_owned_plist(service):
    controller, runner = service
    controller.install()
    watchlist = controller.root / "data/fixture-watchlist.db"
    watchlist.write_text("keep personal data")
    result = controller.uninstall()
    assert result["status"] == "uninstalled"
    assert watchlist.read_text() == "keep personal data"
    assert not controller.installed.exists()
    assert controller.prepared.exists()


def test_busy_unmanaged_port_never_kills_or_registers_any_process(service, monkeypatch):
    controller, runner = service
    def busy():
        raise service_module.ServiceError("Port 5173 is already in use; no process was killed")
    monkeypatch.setattr(controller, "_ports_available", busy)
    with pytest.raises(service_module.ServiceError, match="5173"):
        controller.install()
    assert not controller.installed.exists()
    assert [args[1] for args in runner.calls] == ["print"]
    assert not runner.loaded


def test_foreign_installation_cannot_be_overwritten_or_stopped(service):
    controller, runner = service
    controller.installed.parent.mkdir(parents=True)
    original = plistlib.dumps({"Label": service_module.LABEL, "ProgramArguments": ["/bin/bash", "/different/project/scripts/dev.sh"]})
    controller.installed.write_bytes(original)
    for action in (controller.install, controller.stop, controller.uninstall, controller.start):
        with pytest.raises(service_module.ServiceError, match="another installation"):
            action()
    assert controller.installed.read_bytes() == original
    assert not runner.calls


def test_missing_dependencies_never_install_global_packages(service, monkeypatch):
    controller, runner = service
    (controller.root / ".venv/bin/python").unlink()
    with pytest.raises(service_module.ServiceError, match="No global packages"):
        controller.prepare()
    assert not controller.installed.exists()
    assert not runner.calls


def test_launchctl_failure_is_reported_without_fake_readiness(service):
    controller, _ = service
    controller.runner = lambda *args, **kwargs: SimpleNamespace(returncode=5, stdout="", stderr="Synthetic permission denied")
    with pytest.raises(service_module.ServiceError, match="Synthetic permission denied"):
        controller._launchctl("bootstrap", controller.domain, str(controller.installed))


def test_installed_symlink_cannot_redirect_service_writes_or_stop_operations(service):
    controller, runner = service
    original = controller.root / "data/another.plist"
    original.parent.mkdir(parents=True)
    original.write_bytes(plistlib.dumps(controller.configuration()))
    controller.installed.parent.mkdir(parents=True)
    controller.installed.symlink_to(original)
    with pytest.raises(service_module.ServiceError, match="symlink"):
        controller.install()
    assert not runner.calls
    assert controller.installed.is_symlink()


def test_port_probe_ignores_time_wait_but_still_rejects_active_listener(monkeypatch):
    operations = []
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def setsockopt(self, *args): operations.append(("reuse", args))
        def bind(self, address):
            assert operations[-1][0] == "reuse"
            operations.append(("bind", address))
            if address[1] == 5173:
                raise OSError("Synthetic active listener")
    monkeypatch.setattr(service_module.socket, "socket", Probe)
    with pytest.raises(service_module.ServiceError, match="5173"):
        service_module.EquityLensService._ports_available()
    assert [item[1][1] for item in operations if item[0] == "bind"] == [8000, 5173]


def test_runtime_migrates_sqlite_and_env_once_then_preserves_user_state(service):
    import sqlite3
    controller, runner = service
    source_db = controller.root / "data/equitylens.db"
    source_db.parent.mkdir(parents=True)
    with sqlite3.connect(source_db) as database:
        database.execute("CREATE TABLE personal_research (label TEXT)")
        database.execute("INSERT INTO personal_research VALUES ('original watchlist')")
    (controller.root / ".env").write_text('EQUITYLENS_LLM_API_KEY="fixture-key-only"\nEQUITYLENS_DATABASE_URL="sqlite:///./data/equitylens.db"\n')
    cookie = controller.root / "data/yfinance/cookies.db"
    cookie.parent.mkdir(parents=True)
    cookie.write_text("fixture credential cache: exclude")
    controller.install()
    runtime_db = controller.runtime / "data/equitylens.db"
    with sqlite3.connect(runtime_db) as database:
        assert database.execute("SELECT label FROM personal_research").fetchall() == [("original watchlist",)]
        database.execute("INSERT INTO personal_research VALUES ('runtime report')")
    runtime_env = controller.runtime / ".env"
    assert "fixture-key-only" in runtime_env.read_text()
    assert str(runtime_db) in runtime_env.read_text()
    assert not (controller.runtime / "data/yfinance/cookies.db").exists()
    assert runtime_env.stat().st_mode & 0o777 == 0o600
    assert controller.runtime.stat().st_mode & 0o777 == 0o700
    saved_settings = runtime_env.read_text()
    (controller.root / ".env").write_text('EQUITYLENS_LLM_API_KEY="replacement-source-key"\n')
    (controller.root / "backend/app/main.py").write_text("updated application code\n")
    controller.install()
    assert runtime_env.read_text() == saved_settings
    assert (controller.runtime / "backend/app/main.py").read_text() == "updated application code\n"
    with sqlite3.connect(runtime_db) as database:
        assert database.execute("SELECT label FROM personal_research").fetchall() == [("original watchlist",), ("runtime report",)]
    with sqlite3.connect(source_db) as database:
        assert database.execute("SELECT label FROM personal_research").fetchall() == [("original watchlist",)]


def test_runtime_preserves_relative_node_bin_links_and_rebases_absolute_project_links(service):
    controller, _ = service
    vite = controller.root / "frontend/node_modules/.bin/vite"
    vite.unlink()
    target = controller.root / "frontend/node_modules/vite/bin/vite.js"
    target.parent.mkdir(parents=True)
    target.write_text("fixture vite entry")
    target.chmod(0o755)
    dependency_dist = target.parent.parent / "dist/node/cli.js"
    dependency_dist.parent.mkdir(parents=True)
    dependency_dist.write_text("required Vite runtime implementation")
    frontend_dist = controller.root / "frontend/dist/index.html"
    frontend_dist.parent.mkdir(parents=True)
    frontend_dist.write_text("obsolete app build output")
    vite.symlink_to("../vite/bin/vite.js")
    absolute = controller.root / ".venv/bin/project-helper"
    absolute.symlink_to(controller.root / ".venv/bin/python")
    controller.install()
    copied = controller.runtime / "frontend/node_modules/.bin/vite"
    assert copied.is_symlink()
    assert copied.readlink() == Path("../vite/bin/vite.js")
    assert copied.resolve() == controller.runtime / "frontend/node_modules/vite/bin/vite.js"
    assert (controller.runtime / "frontend/node_modules/vite/dist/node/cli.js").read_text() == "required Vite runtime implementation"
    assert not (controller.runtime / "frontend/dist").exists()
    assert (controller.runtime / ".venv/bin/project-helper").resolve() == controller.runtime / ".venv/bin/python"


def test_existing_legacy_source_plist_can_upgrade_without_losing_ownership(service):
    controller, _ = service
    controller.installed.parent.mkdir(parents=True)
    controller.installed.write_bytes(plistlib.dumps({"Label": service_module.LABEL, "ProgramArguments": ["/bin/bash", str(controller.root / "scripts/dev.sh")]}))
    assert controller.install()["ready"] is True
    current = plistlib.loads(controller.installed.read_bytes())
    assert current["WorkingDirectory"] == str(controller.runtime)
    assert current["EnvironmentVariables"]["EQUITYLENS_SOURCE_ROOT"] == str(controller.root)


def test_unrecognized_runtime_folder_is_not_overwritten(service):
    controller, _ = service
    controller.runtime.mkdir(parents=True)
    unrelated = controller.runtime / "unrelated.txt"
    unrelated.write_text("preserve")
    with pytest.raises(service_module.ServiceError, match="unrecognized"):
        controller.install()
    assert unrelated.read_text() == "preserve"
