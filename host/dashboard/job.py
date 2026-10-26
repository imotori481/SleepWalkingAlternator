"""裏のスレッドで仕事を1つだけ流し、出力の末尾を持つ。

MirrorSync、UnityRefs、ImportJob の土台。要求の中では待たず、進みは status で返す。
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable


class BackgroundJob:
    def __init__(self, tail_lines: int):
        self._lock = threading.Lock()
        self._running = False
        self._started: str | None = None
        self._finished: str | None = None
        self._output: deque[str] = deque(maxlen=tail_lines)

    def _state(self) -> dict[str, Any]:
        """走っているか、始めと終わりの時刻、出力の末尾。ロックを持って呼ぶ。"""
        return {"running": self._running, "started": self._started,
                "finished": self._finished, "output": list(self._output)}

    def _launch(self, busy: str, target: Callable[..., None], *args: Any,
                **fields: Any) -> None:
        """走っていなければ印を立て、`target` を裏で流す。`fields` は `_<名前>` に置く。"""
        with self._lock:
            if self._running:
                raise ValueError(busy)
            self._running, self._started, self._finished = True, _now(), None
            self._output.clear()
            for name, value in fields.items():
                setattr(self, f"_{name}", value)
        self.thread = threading.Thread(target=target, args=args, daemon=True)
        self.thread.start()

    def _say(self, line: str) -> None:
        with self._lock:
            self._output.extend(line.splitlines() or [""])

    def _end(self, **fields: Any) -> None:
        with self._lock:
            self._running, self._finished = False, _now()
            for name, value in fields.items():
                setattr(self, f"_{name}", value)

    def _run_command(self, argv: list[str], name: str, encoding: str | None = None) -> None:
        """コマンドを流し、出力を末尾に足す。終わりに returncode を置く。起動できなければ -1。

        `encoding` は出力の文字コード。None ならホストの既定で読む。
        """
        returncode = -1
        try:
            process = subprocess.Popen(
                argv, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding=encoding, errors="replace")
            for line in process.stdout:
                self._say(line.rstrip())
            returncode = process.wait()
        except OSError as error:
            self._say(f"could not start {name}: {error}")
        finally:
            self._end(returncode=returncode)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
