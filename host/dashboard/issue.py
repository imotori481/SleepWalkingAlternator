"""取り込んだリポジトリの GitHub の Issue を、ホストの `gh` で読む。

取り込みタブは取り込む前の確認に、走行タブは仕様書の下書きに使う。GitHub と
やり取りするのはホストだけで、箱には Issue の中身も番号も送らない。

Issue の本文とコメントは他人が書ける外部の入力だ。ここでは形を整えて返すだけで、
プランナーには渡さない。プランナーに届くのは、人が走行タブで直して送った本文だけ。

番号は `branch.<branch>.swaIssue` としてクローンの git の設定に記録する。
`swaBase` と同じ置き方で、PR の本文に `Closes #<番号>` を入れるのに使う。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

try:
    from .pullrequest import ISSUE_KEY, PullRequestError, github_repo
except ImportError:  # 直接実行したとき: python host/dashboard/server.py
    from pullrequest import ISSUE_KEY, PullRequestError, github_repo

# 番号だけ。`#` や URL は受け付けない。
NUMBER = re.compile(r"[1-9][0-9]{0,9}")
FIELDS = "number,title,body,author,state,url,comments"
TIMEOUT_SECONDS = 60

Runner = Callable[..., subprocess.CompletedProcess]


class IssueError(ValueError):
    pass


def issue_number(value: Any) -> str:
    """Issue の番号を確かめて文字列で返す。形が合わなければ IssueError。"""
    text = value.strip() if isinstance(value, str) else ""
    if not NUMBER.fullmatch(text):
        raise IssueError(f"not an issue number: {value!r} (digits only, without '#')")
    return text


def login(value: Any) -> str:
    return str(value.get("login") or "?") if isinstance(value, dict) else "?"


def shape(value: dict[str, Any]) -> dict[str, Any]:
    """gh の JSON から、画面と下書きが使う値だけを取り出す。"""
    return {"number": value.get("number"), "title": str(value.get("title") or ""),
            "body": str(value.get("body") or ""), "author": login(value.get("author")),
            "url": str(value.get("url") or ""),
            "comments": [{"author": login(comment.get("author")),
                          "at": str(comment.get("createdAt") or ""),
                          "body": str(comment.get("body") or "")}
                         for comment in value.get("comments") or []
                         if isinstance(comment, dict)]}


class Issues:
    def __init__(self, run: Runner = subprocess.run):
        self._run = run

    def read(self, url: str, number: Any) -> dict[str, Any]:
        """開いている Issue を読む。閉じていれば断る。"""
        number = issue_number(number)
        try:
            repo = github_repo(url)
        except PullRequestError:
            raise IssueError(f"issues can only be read from a GitHub repository: {url.strip()}")
        argv = ["gh", "issue", "view", number, "--repo", repo, "--json", FIELDS]
        try:
            proc = self._run(argv, shell=False, capture_output=True, text=True,
                             encoding="utf-8", timeout=TIMEOUT_SECONDS,
                             stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise IssueError(f"gh could not run: {error}") from error
        if proc.returncode != 0:
            reason = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise IssueError(f"gh issue view {number} failed"
                             + (f": {reason[-1]}" if reason else ""))
        try:
            value = json.loads(proc.stdout)
        except json.JSONDecodeError as error:
            raise IssueError(f"gh issue view {number} returned no JSON") from error
        if not isinstance(value, dict):
            raise IssueError(f"gh issue view {number} returned no JSON object")
        if str(value.get("state", "")).upper() != "OPEN":
            raise IssueError(f"issue #{number} is closed")
        return shape(value)

    def current(self, workroot: Path, live: dict[str, Any]) -> dict[str, Any]:
        """今のプロジェクトの作業ブランチに記録された Issue。記録が無ければ issue は None。

        `live` は `swa now` の値。プロジェクトの名前と作業ブランチをそこから読み、
        ホストのクローン `<workroot>\\<project>` の git の設定から番号を引く。
        """
        if "error" in live:
            raise IssueError(f"the sandbox is out of reach: {live['error']}")
        project = str(live.get("project") or "")
        branch = next((str(item.get("branch") or "") for item in live.get("projects") or []
                       if isinstance(item, dict) and item.get("name") == project), "")
        clone = workroot / project
        if not project or not branch or not (clone / ".git").exists():
            return {"project": project, "branch": branch, "issue": None}
        number = self._git(clone, "config", "--get", ISSUE_KEY.format(branch))
        if not number:
            return {"project": project, "branch": branch, "issue": None}
        url = self._git(clone, "remote", "get-url", "origin")
        return {"project": project, "branch": branch, "issue": self.read(url, number)}

    def _git(self, clone: Path, *args: str) -> str:
        try:
            proc = self._run(["git", "-C", str(clone), *args], shell=False,
                             capture_output=True, text=True, encoding="utf-8",
                             timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise IssueError(f"git could not run: {error}") from error
        return proc.stdout.strip() if proc.returncode == 0 else ""
