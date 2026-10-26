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
from pathlib import Path
from typing import Any

try:
    from .importer import PROJECT
    from .job import BackgroundJob
except ImportError:  # 直接実行したとき
    from importer import PROJECT
    from job import BackgroundJob

SCRIPT = Path(__file__).resolve().parents[1] / "swa-unity-refs.ps1"
TAIL_LINES = 60
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


class UnityRefs(BackgroundJob):
    def __init__(self, data: Path, script: Path = SCRIPT):
        super().__init__(TAIL_LINES)
        self.folders_path = data / "unity-projects.json"
        self.script = script
        self._project: str | None = None
        self._dry_run = False
        self._returncode: int | None = None

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
            return {"project": name, "folder": folder, "host": host, **self._state(),
                    "job_project": self._project, "dry_run": self._dry_run,
                    "returncode": self._returncode}

    def start(self, project: object, dry_run: bool) -> dict[str, Any]:
        name = check_project(project)
        folder = self._folders().get(name)
        if not folder:
            raise ValueError(f"no Unity project folder is remembered for '{name}'")
        path = check_folder(folder)
        argv = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(self.script), name, str(path)] + (["-DryRun"] if dry_run else [])
        self._launch("swa-unity-refs is already running", self._run_command,
                     argv, "swa-unity-refs",
                     project=name, dry_run=bool(dry_run), returncode=None)
        return self.status(name)
