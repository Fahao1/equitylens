#!/usr/bin/env python3
"""Install/manage EquityLens as the current macOS user's supervised LaunchAgent."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.equitylens.local"
URL = "http://127.0.0.1:5173"


class ServiceError(RuntimeError):
    pass


class EquityLensService:
    def __init__(self, root=ROOT, home=None, runner=subprocess.run):
        self.root = Path(root).resolve()
        self.home = Path(home) if home is not None else Path.home()
        self.runner = runner
        self.uid = os.getuid()
        self.domain = f"gui/{self.uid}"
        self.target = f"{self.domain}/{LABEL}"
        self.installed = self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        self.prepared = self.root / "data" / "service" / f"{LABEL}.plist"
        self.runtime = self.home / "Library" / "Application Support" / "EquityLens"
        self.owner_file = self.runtime / ".equitylens-runtime.json"
        self.logs = self.runtime / "data" / "logs"

    def configuration(self):
        python = self.root / ".venv/bin/python"
        vite = self.root / "frontend/node_modules/.bin/vite"
        node = shutil.which("node")
        if not python.is_file() or not os.access(python, os.X_OK) or not vite.is_file() or not os.access(vite, os.X_OK) or not node:
            raise ServiceError("Install this project's .venv and frontend dependencies using README.md, and make Node available in your terminal. No global packages were installed.")
        node_bin = str(Path(node).parent)
        path = ":".join(dict.fromkeys([node_bin, "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]))
        return {"Label": LABEL, "ProgramArguments": ["/bin/bash", str(self.runtime / "scripts/dev.sh")],
                "WorkingDirectory": str(self.runtime), "RunAtLoad": True, "KeepAlive": True,
                "ThrottleInterval": 10, "ExitTimeOut": 30,
                "EnvironmentVariables": {"PATH": path, "PYTHONUNBUFFERED": "1", "EQUITYLENS_SOURCE_ROOT": str(self.root)},
                "StandardOutPath": str(self.logs / "service.stdout.log"), "StandardErrorPath": str(self.logs / "service.stderr.log")}

    def prepare(self):
        configuration = self.configuration()
        self.prepared.parent.mkdir(parents=True, exist_ok=True)
        self.prepared.write_bytes(plistlib.dumps(configuration, sort_keys=False))
        self.prepared.chmod(0o600)
        return self.prepared

    def _macos(self):
        if platform.system() != "Darwin":
            raise ServiceError("The persistent service uses macOS launchd. On other systems use scripts/dev.sh or Docker Compose.")
        if os.geteuid() == 0:
            raise ServiceError("Run this as your normal logged-in macOS user, without sudo.")

    def _launchctl(self, *arguments, check=True):
        result = self.runner(["/bin/launchctl", *arguments], capture_output=True, text=True)
        if check and result.returncode:
            message = result.stderr.strip() or result.stdout.strip() or "launchctl did not succeed"
            raise ServiceError(f"launchctl {' '.join(arguments[:2])}: {message}")
        return result

    def _job(self):
        result = self._launchctl("print", self.target, check=False)
        match = re.search(r"^\s*state = (\S+)", result.stdout or "", re.M)
        return {"loaded": result.returncode == 0, "state": match.group(1) if match else "not_loaded"}

    def _verify_ownership(self):
        if self.installed.is_symlink():
            raise ServiceError("The installed plist is a symlink; its ownership is ambiguous. It was not modified or stopped.")
        if not self.installed.exists():
            return False
        try:
            existing = plistlib.loads(self.installed.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException) as exc:
            raise ServiceError(f"Cannot verify ownership of {self.installed}; it was not modified.") from exc
        arguments = existing.get("ProgramArguments")
        legacy = arguments == ["/bin/bash", str(self.root / "scripts/dev.sh")]
        deployed = arguments == ["/bin/bash", str(self.runtime / "scripts/dev.sh")] and existing.get("EnvironmentVariables", {}).get("EQUITYLENS_SOURCE_ROOT") == str(self.root)
        if existing.get("Label") != LABEL or not (legacy or deployed):
            raise ServiceError("This service label belongs to another installation. Stop/uninstall it from its original project before installing this checkout. Nothing was stopped or overwritten.")
        return True

    def _database_url(self):
        # Load configuration without importing main or printing any secret values.
        sys.path.insert(0, str(self.root / "backend"))
        from app.config import Settings
        return Settings(_env_file=str(self.root / ".env")).database_url

    @staticmethod
    def _set_env(text, key, value):
        line = key + "=" + json.dumps(str(value), ensure_ascii=False)
        pattern = re.compile(r"^\s*(?:export\s+)?" + re.escape(key) + r"\s*=.*$", re.M)
        return pattern.sub(lambda match: line, text) if pattern.search(text) else text.rstrip() + "\n" + line + "\n"

    def _initialize_data(self):
        source_env = self.root / ".env"
        text = source_env.read_text() if source_env.is_file() else ""
        database_url = self._database_url()
        data = self.runtime / "data"
        data.mkdir(parents=True, exist_ok=True)
        if database_url.startswith("sqlite:///"):
            source_name = database_url.removeprefix("sqlite:///")
            if source_name == ":memory:":
                raise ServiceError("A persistent service requires a file-based SQLite database or an external database; in-memory data cannot be migrated.")
            source = Path(source_name).expanduser()
            if not source.is_absolute():
                source = self.root / source
            destination = data / "equitylens.db"
            if source.is_file():
                with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as before:
                    with sqlite3.connect(destination) as after:
                        before.backup(after)
                destination.chmod(0o600)
            text = self._set_env(text, "EQUITYLENS_DATABASE_URL", "sqlite:///" + str(destination))
        text = self._set_env(text, "EQUITYLENS_DATA_DIR", str(data))
        settings = self.runtime / ".env"
        settings.write_text(text)
        settings.chmod(0o600)

    def _deploy_runtime(self):
        owner = None
        if self.owner_file.is_file():
            try:
                owner = json.loads(self.owner_file.read_text())
            except (OSError, ValueError) as exc:
                raise ServiceError("Runtime ownership metadata is invalid; no runtime files were replaced.") from exc
            if owner.get("label") != LABEL or owner.get("uid") != self.uid:
                raise ServiceError("The runtime folder is not owned by this EquityLens user installation; nothing was replaced.")
        elif self.runtime.exists() and any(self.runtime.iterdir()):
            raise ServiceError("The runtime folder already contains unrecognized files; nothing was replaced.")
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.runtime.chmod(0o700)
        if owner is None:
            owner = {"label": LABEL, "uid": self.uid, "data_initialized": False}
        owner["source_root"] = str(self.root)
        self.owner_file.write_text(json.dumps(owner, indent=2) + "\n")
        self.owner_file.chmod(0o600)
        base_ignored = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".git", ".DS_Store", ".env", ".env.*", ".npmrc", "pip.conf", ".netrc", ".cache", ".vite")
        def ignored(folder, names):
            excluded = set(base_ignored(folder, names))
            if Path(folder) == self.root / "frontend" and "dist" in names:
                excluded.add("dist")
            return excluded
        # Copy only the application and its already-installed local dependencies.
        # Preserving relative package/bin symlinks is essential for Node imports.
        for relative in ("backend", "frontend", ".venv"):
            source = self.root / relative
            destination = self.runtime / relative
            if destination.is_symlink():
                destination.unlink()
            elif destination.exists():
                shutil.rmtree(destination)
            if relative == "backend":
                (destination / "app").parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source / "app", destination / "app", symlinks=True, ignore=ignored)
            else:
                shutil.copytree(source, destination, symlinks=True, ignore=ignored)
        scripts = self.runtime / "scripts"
        scripts.mkdir(exist_ok=True)
        shutil.copy2(self.root / "scripts/dev.sh", scripts / "dev.sh")
        if not owner.get("data_initialized"):
            self._initialize_data()
            owner["data_initialized"] = True
            self.owner_file.write_text(json.dumps(owner, indent=2) + "\n")
        # No credential/cookie caches or other ignored source folders are copied.
        for relative in ("backend", "frontend", ".venv"):
            for path in (self.runtime / relative).rglob("*"):
                if not path.is_symlink():
                    continue
                resolved = path.resolve(strict=False)
                if resolved.is_relative_to(self.root):
                    target = self.runtime / resolved.relative_to(self.root)
                    if not target.exists():
                        raise ServiceError("A dependency points to source files outside the copied runtime. Reinstall project dependencies before retrying.")
                    path.unlink()
                    path.symlink_to(target)
                elif resolved.is_relative_to(self.home / "Desktop"):
                    raise ServiceError("A dependency points to another Desktop folder. It was not copied or granted broader access.")
        self.logs.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _ports_available():
        for port in (8000, 5173):
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as exc:
                    raise ServiceError(f"Port {port} is already in use by an unmanaged instance. Stop its original terminal/app first, then retry. No process was killed.") from exc

    @staticmethod
    def _http_ready(url, backend=False):
        try:
            with urlopen(url, timeout=.5) as response:
                return response.status == 200 and (not backend or json.load(response).get("status") == "ok")
        except Exception:
            return False

    def status(self):
        job = self._job()
        backend = self._http_ready("http://127.0.0.1:8000/health", backend=True)
        frontend = self._http_ready(URL)
        return {"installed": self.installed.exists(), "service": LABEL, "launchd_state": job["state"],
                "ready": job["state"] == "running" and backend and frontend, "backend_ready": backend, "frontend_ready": frontend,
                "url": URL, "plist": str(self.installed), "logs": str(self.logs), "source": str(self.root), "runtime": str(self.runtime)}

    def _wait_ready(self, seconds=35):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            state = self.status()
            if state["ready"]:
                return state
            time.sleep(.25)
        raise ServiceError(f"Service did not become ready. Check {self.logs / 'service.stderr.log'} and {self.logs / 'backend.log'} for the startup error.")

    def install(self):
        self._macos()
        self.prepare()
        owned = self._verify_ownership()
        loaded = self._job()["loaded"]
        if loaded and not owned:
            raise ServiceError("A loaded service has this label but no verified project plist. Nothing was stopped; resolve its ownership first.")
        if loaded:
            self._launchctl("bootout", self.target)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    self._ports_available()
                    break
                except ServiceError:
                    time.sleep(.25)
        self._ports_available()
        self._deploy_runtime()
        self.installed.parent.mkdir(parents=True, exist_ok=True)
        self.installed.write_bytes(self.prepared.read_bytes())
        self.installed.chmod(0o600)
        self._launchctl("enable", self.target)
        self._launchctl("bootstrap", self.domain, str(self.installed))
        return self._wait_ready()

    def start(self):
        self._macos()
        if not self._verify_ownership():
            return self.install()
        if not self.owner_file.exists():
            return self.install()
        self._launchctl("enable", self.target)
        if not self._job()["loaded"]:
            self._ports_available()
            self._launchctl("bootstrap", self.domain, str(self.installed))
        else:
            self._launchctl("kickstart", self.target)
        return self._wait_ready()

    def stop(self):
        self._macos()
        if not self._verify_ownership():
            raise ServiceError("No installed EquityLens plist was found; no running process was touched.")
        self._launchctl("disable", self.target)
        if self._job()["loaded"]:
            self._launchctl("bootout", self.target)
        return {"status": "stopped", "service": LABEL, "autostart": "disabled until start or install"}

    def uninstall(self):
        self.stop()
        self.installed.unlink()
        return {"status": "uninstalled", "service": LABEL, "data_preserved": str(self.runtime / "data"), "source_preserved": str(self.root)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "install", "start", "stop", "status", "uninstall"))
    parser.add_argument("--open", action="store_true", help="Open the browser only after both services are healthy.")
    args = parser.parse_args()
    service = EquityLensService()
    try:
        if args.command == "prepare":
            result = {"prepared_plist": str(service.prepare()), "install_target": str(service.installed), "project": str(service.root)}
        elif args.command == "status":
            service._macos()
            result = service.status()
        else:
            result = getattr(service, args.command)()
        print(json.dumps(result, indent=2))
        if args.open and result.get("ready"):
            subprocess.run(["/usr/bin/open", URL], check=True)
        return 1 if args.command == "status" and not result["ready"] else 0
    except (ServiceError, OSError, subprocess.SubprocessError) as exc:
        print(f"EquityLens: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
