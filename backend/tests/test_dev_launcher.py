"""Exercise launcher lifecycle with local mock processes; no ports or network used."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]

MOCK_DRIVER = r'''
import json
import os
from pathlib import Path
import signal
import sys
import time

root = Path(os.environ["MOCK_ROOT"])
args = sys.argv[1:]
def event(name, **values):
    with (root / "events.jsonl").open("a") as stream:
        stream.write(json.dumps({"event": name, **values}) + "\n")

if args == ["-"]:
    sys.stdin.read()
    event("port_probe")
    if os.environ.get("MOCK_PORT_BUSY"):
        print("Port 5173 is already in use. Stop the existing app; no process was stopped.", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)
if args[:1] == ["-c"]:
    if "urlopen" in args[1]:
        event("health_probe")
        count = sum('"event": "health_probe"' in row for row in (root / "events.jsonl").read_text().splitlines())
        if count < 2:
            raise SystemExit(1)
        (root / "healthy").touch()
        raise SystemExit(0)
    print("Python executable: " + str(root / ".venv/bin/python"))
    print("Python version: fixture-version")
    print("yfinance version: fixture-yfinance")
    event("environment_trace")
    raise SystemExit(0)
if args[:2] == ["-m", "uvicorn"]:
    event("backend_started", args=args)
    print("complete mocked backend stdout", flush=True)
    print("complete mocked backend stderr", file=sys.stderr, flush=True)
    if os.environ.get("MOCK_BACKEND_EARLY_EXIT"):
        raise SystemExit(7)
    def stop(*_):
        event("backend_stopped")
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    while not (root / "frontend_started").exists():
        time.sleep(.02)
    if os.environ.get("MOCK_BACKEND_EXIT_AFTER_FRONTEND"):
        raise SystemExit(8)
    while True:
        time.sleep(.02)
if args[:1] == ["frontend"]:
    def stop(*_):
        event("frontend_stopped")
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    event("frontend_started", args=args[1:], cwd=str(Path.cwd()), ready=(root / "healthy").exists())
    (root / "frontend_started").touch()
    while True:
        time.sleep(.02)
raise SystemExit("Unexpected mock arguments: " + repr(args))
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / "frontend/node_modules/.bin").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/dev.sh", tmp_path / "scripts/dev.sh")
    (tmp_path / "mock_driver.py").write_text(MOCK_DRIVER)
    python = tmp_path / ".venv/bin/python"
    python.write_text('#!/usr/bin/env bash\nexec "$MOCK_REAL_PYTHON" "$MOCK_ROOT/mock_driver.py" "$@"\n')
    python.chmod(0o755)
    vite = tmp_path / "frontend/node_modules/.bin/vite"
    vite.write_text('#!/usr/bin/env bash\nexec "$MOCK_REAL_PYTHON" "$MOCK_ROOT/mock_driver.py" frontend "$@"\n')
    vite.chmod(0o755)
    return tmp_path


def launch(project, **extra):
    environment = {**os.environ, "MOCK_ROOT": str(project), "MOCK_REAL_PYTHON": sys.executable, **extra}
    return subprocess.run(["bash", str(project / "scripts/dev.sh")], cwd=project.parent, env=environment, capture_output=True, text=True, timeout=10)


def events(project):
    import json
    path = project / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_launcher_is_valid_bash():
    subprocess.run(["bash", "-n", str(ROOT / "scripts/dev.sh")], check=True)


def test_waits_for_health_uses_project_python_strict_port_and_cleans_frontend(project):
    result = launch(project, MOCK_BACKEND_EXIT_AFTER_FRONTEND="1")
    assert result.returncode == 8, result.stdout + result.stderr
    history = events(project)
    frontend = next(row for row in history if row["event"] == "frontend_started")
    backend = next(row for row in history if row["event"] == "backend_started")
    assert frontend["ready"] is True
    assert frontend["cwd"] == str(project / "frontend")
    assert frontend["args"] == ["--host", "127.0.0.1", "--port", "5173", "--strictPort"]
    assert backend["args"] == ["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8000"]
    assert any(row["event"] == "frontend_stopped" for row in history)
    assert f"Python executable: {project}/.venv/bin/python" in result.stdout
    assert "Python version: fixture-version" in result.stdout
    assert "yfinance version: fixture-yfinance" in result.stdout
    log = (project / "data/logs/backend.log").read_text()
    assert "complete mocked backend stdout" in log
    assert "complete mocked backend stderr" in log
    assert "shutting down the frontend" in result.stderr


def test_backend_startup_failure_never_starts_frontend_and_keeps_full_log(project):
    result = launch(project, MOCK_BACKEND_EARLY_EXIT="1")
    assert result.returncode == 7, result.stdout + result.stderr
    assert all(row["event"] != "frontend_started" for row in events(project))
    assert "before becoming ready" in result.stderr
    assert "complete mocked backend stderr" in (project / "data/logs/backend.log").read_text()


def test_busy_port_fails_before_starting_or_stopping_any_app(project):
    result = launch(project, MOCK_PORT_BUSY="1")
    assert result.returncode == 1
    assert "already in use" in result.stderr
    assert not any(row["event"] in ("backend_started", "frontend_started", "backend_stopped", "frontend_stopped") for row in events(project))


def test_missing_project_environment_has_clear_install_message(project):
    (project / ".venv/bin/python").unlink()
    result = launch(project)
    assert result.returncode == 1
    assert "Install project dependencies" in result.stderr


def test_termination_cleans_both_owned_services(project):
    import signal
    import time
    environment = {**os.environ, "MOCK_ROOT": str(project), "MOCK_REAL_PYTHON": sys.executable}
    process = subprocess.Popen(["bash", str(project / "scripts/dev.sh")], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not (project / "frontend_started").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (project / "frontend_started").exists()
        process.terminate()
        output, error = process.communicate(timeout=5)
        assert process.returncode == 143, output + error
        history = events(project)
        assert any(row["event"] == "frontend_stopped" for row in history)
        assert any(row["event"] == "backend_stopped" for row in history)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=5)
