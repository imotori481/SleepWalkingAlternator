"""ホストの写しを `swa-pull.cmd` で箱の先まで進める。

クローンが初めてなら数分かかるので、要求の中では待たずに裏のスレッドで流し、
進みは status で返す。コマンドは固定で、HTTP の値は1つも入らない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .job import BackgroundJob
except ImportError:  # 直接実行したとき
    from job import BackgroundJob

SCRIPT = Path(__file__).resolve().parents[1] / "swa-pull.cmd"
TAIL_LINES = 40


class MirrorSync(BackgroundJob):
    def __init__(self, script: Path = SCRIPT):
        super().__init__(TAIL_LINES)
        self.script = script
        self._returncode: int | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state(), "returncode": self._returncode}

    def start(self) -> dict[str, Any]:
        self._launch("swa-pull is already running", self._run_command,
                     ["cmd.exe", "/d", "/c", str(self.script)], "swa-pull", returncode=None)
        return self.status()
