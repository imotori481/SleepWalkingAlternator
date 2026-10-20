"""箱が新しいコミットを送るたびに、ホストの写しを `swa-pull.cmd` で引く。

ランナーは GREEN と段のコマンドのたびに箱の bare へコミットを送る。`swa now` の
projects がそれぞれの bare のブランチの先を返すので、どれかが動いたら写しを引く。
サーバが起きた最初の1回も引く。写しがどこまで進んでいるかは分からないからだ。

引いている間に先が動いたら、引き終わってから次の見回りでもう一度引く。引けなかったら
次の見回りで引き直す。箱に届かない間は何もしない。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

DEFAULT_INTERVAL = 30


def settings(config_path: Path) -> tuple[bool, int]:
    """config.json の mirror.auto_pull と mirror.interval_seconds。無ければ有効、30秒。"""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return True, DEFAULT_INTERVAL
    mirror = data.get("mirror", {}) if isinstance(data, dict) else {}
    if not isinstance(mirror, dict):
        return True, DEFAULT_INTERVAL
    interval = mirror.get("interval_seconds", DEFAULT_INTERVAL)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 5:
        raise ValueError("mirror.interval_seconds must be an integer of 5 or more")
    return mirror.get("auto_pull", True) is not False, interval


def fingerprint(now: dict[str, Any]) -> tuple | None:
    """箱の全プロジェクトのブランチの先。箱に届かなければ None。"""
    if now.get("error") or not isinstance(now.get("projects"), list):
        return None
    return tuple(sorted((p.get("name"), p.get("head")) for p in now["projects"]
                        if isinstance(p, dict)))


class AutoPull:
    def __init__(self, fetch: Callable[[], dict[str, Any]], mirror, interval: int):
        self.fetch = fetch
        self.mirror = mirror
        self.interval = interval
        self.seen: tuple | None = None
        self._pending: tuple | None = None
        self._stop = threading.Event()

    def check(self) -> bool:
        """1回見回る。写しを引き始めたら真。"""
        status = self.mirror.status()
        if status["running"]:
            return False
        if self._pending is not None:
            # 引けたときだけ、その先まで写したことにする。失敗したら次でまた引く。
            if status["returncode"] == 0:
                self.seen = self._pending
            self._pending = None
        current = fingerprint(self.fetch())
        if current is None or current == self.seen:
            return False
        try:
            self.mirror.start()
        except ValueError:
            # 画面から引き始めたのと重なった。次の見回りで確かめ直す。
            return False
        self._pending = current
        return True

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception as error:  # 見回りが落ちてもサーバは止めない
                print(f"auto pull: {error}")
            self._stop.wait(self.interval)
