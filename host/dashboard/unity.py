"""Unity の参照アセンブリを、ダッシュボードから `swa-unity-refs.ps1` で箱へ送る。

端末で流すものと同じスクリプトを、このサーバのスレッドで流し、進みは status で返す。
送り先の箱は `swa dash` で参照を置くので、パスワードを訊かれない。

Unity のプロジェクトのフォルダは、プロジェクトごとに `<data>/unity-projects.json` に覚える。
フォルダは HTTP から来る値で、スクリプトの引数になる。だから覚える前に、絶対パスで、
`ProjectSettings/ProjectVersion.txt` を持つディレクトリであることを確かめる。`shell=False`
で引数配列のまま渡すので、シェルの文にはならない。
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "swa-unity-refs.ps1"
TAIL_LINES = 60
# swa-project.sh の valid_name と同じ規則。
PROJECT = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
# swa-unity-refs.ps1 が指紋に入れるファイル。csproj がこれより古ければ、スクリプトが断る。
FINGERPRINTED = ("ProjectSettings/ProjectVersion.txt", "Packages/manifest.json",
                 "Packages/packages-lock.json")


def check_project(value: object) -> str:
    if not isinstance(value, str) or not PROJECT.fullmatch(value) or value == "CURRENT":
        raise ValueError(f"not a project name: {value!r}")
    return value


def check_folder(value: object) -> Path:
    """Unity のプロジェクトのフォルダ。絶対パスで、ProjectVersion.txt があるものだけ。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("enter the folder of the Unity project")
    folder = Path(value.strip())
    if not folder.is_absolute() or value.strip().startswith("-"):
        raise ValueError(f"not an absolute path: {value}")
    if not (folder / "ProjectSettings" / "ProjectVersion.txt").is_file():
        raise ValueError(f"not a Unity project (no ProjectSettings/ProjectVersion.txt): {folder}")
    return folder.resolve()


def host_state(folder: Path) -> dict[str, Any]:
    """フォルダの csproj が、送れる状態か。無ければ csproj は False。

    `older_than` は csproj より新しいファイル。空でなければスクリプトが断るので、
    押す前に Unity で Regenerate project files を押すよう画面で言える。
    """
    csproj = folder / "Assembly-CSharp.csproj"
    if not csproj.is_file():
        return {"csproj": False, "older_than": []}
    written = csproj.stat().st_mtime
    return {"csproj": True,
            "older_than": [rel for rel in FINGERPRINTED
                           if (folder / rel).is_file() and (folder / rel).stat().st_mtime > written]}


class UnityRefs:
    def __init__(self, data: Path, script: Path = SCRIPT):
        self.folders_path = data / "unity-projects.json"
        self.script = script
        self._lock = threading.Lock()
        self._running = False
        self._project: str | None = None
        self._dry_run = False
        self._started: str | None = None
        self._finished: str | None = None
        self._returncode: int | None = None
        self._output: deque[str] = deque(maxlen=TAIL_LINES)

    def _folders(self) -> dict[str, str]:
        try:
            value = json.loads(self.folders_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    def remember(self, project: object, folder: object) -> dict[str, Any]:
        name, path = check_project(project), check_folder(folder)
        with self._lock:
            folders = self._folders()
            folders[name] = str(path)
            self.folders_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.folders_path.with_suffix(".tmp")
            temp.write_text(json.dumps(folders, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.folders_path)
        return self.status(name)

    def status(self, project: object) -> dict[str, Any]:
        """覚えたフォルダとその csproj の状態、最後に流したスクリプトの出力。"""
        name = check_project(project)
        folder = self._folders().get(name)
        host = None
        if folder:
            try:
                host = host_state(check_folder(folder))
            except ValueError as error:
                host = {"error": str(error)}
        with self._lock:
            return {"project": name, "folder": folder, "host": host,
                    "running": self._running, "job_project": self._project,
                    "dry_run": self._dry_run, "started": self._started,
                    "finished": self._finished, "returncode": self._returncode,
                    "output": list(self._output)}

    def start(self, project: object, dry_run: bool) -> dict[str, Any]:
        name = check_project(project)
        folder = self._folders().get(name)
        if not folder:
            raise ValueError(f"no Unity project folder is remembered for '{name}'")
        path = check_folder(folder)
        with self._lock:
            if self._running:
                raise ValueError("swa-unity-refs is already running")
            self._running, self._project, self._dry_run = True, name, bool(dry_run)
            self._started, self._finished, self._returncode = _now(), None, None
            self._output.clear()
        argv = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(self.script), name, str(path)] + (["-DryRun"] if dry_run else [])
        self.thread = threading.Thread(target=self._run, args=(argv,), daemon=True)
        self.thread.start()
        return self.status(name)

    def _run(self, argv: list[str]) -> None:
        returncode = -1
        try:
            process = subprocess.Popen(
                argv, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace")
            for line in process.stdout:
                with self._lock:
                    self._output.append(line.rstrip())
            returncode = process.wait()
        except OSError as error:
            with self._lock:
                self._output.append(f"could not start swa-unity-refs: {error}")
        finally:
            with self._lock:
                self._running, self._finished, self._returncode = False, _now(), returncode


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
