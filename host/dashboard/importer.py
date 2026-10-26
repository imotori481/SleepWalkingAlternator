"""既存リポジトリのブランチを、箱の新しいプロジェクトとして取り込む。

ダッシュボードの「取り込み」タブと `host\\swa-import.cmd` の両方がこれを使う。手順の
実装を1つにしておけば、片方だけ直してずれることが無い。

    1. <url> を WORKROOT\\<project> にクローンする。もうあれば使い回す
    2. <branch> に切り替える。どこにも無ければ <base> から作る
    3. 箱で swa project init <project> --branch <branch>
    4. swa-runner で <branch> を箱の bare に push する
    5. 箱で swa project use <project>。切り替えが終わるまで待つ

Issue の番号を渡すと、1 の前にその Issue が開いていることを確かめ、2 で番号を
`branch.<branch>.swaIssue` に記録する。PR の本文の Closes に使う。

GitHub とやり取りするのはホストだけだ。箱は push でブランチを受け取り、GitHub の
資格情報を持たない。3 と 5 は `swa dash` を通すので、パスワードを訊かれない。

HTTP から来た値は git の引数になる。だから形をここで確かめ、`shell=False` の
引数配列で渡し、URL の前には `--` を置く。オプションとしては読ませない。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from .issue import ISSUE_KEY, Issues, issue_number
    from .job import BackgroundJob
    from .live import Live
except ImportError:  # 直接実行したとき: python host/dashboard/importer.py
    from issue import ISSUE_KEY, Issues, issue_number
    from job import BackgroundJob
    from live import Live

WORKROOT = Path(r"C:\dev\roop-engin\projects")
PUSH_HOST = "swa-runner"
TAIL_LINES = 60
# 切り替えの待ち。初めてのプロジェクトはプロビジョニングで数分かかる。
SWITCH_POLL_SECONDS = 3.0
SWITCH_LIMIT_SECONDS = 30 * 60

# 箱の swa_dash.py と同じ規則。箱でも確かめるが、クローンする前に断る。unity.py も使う。
PROJECT = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
FENCE = re.compile(r"[A-Za-z0-9._/-]{0,200}")
# https:// と ssh:// と scp 形式（user@host:path）だけ。file:// や ext:: のように
# ホストのファイルやコマンドに届く形は通さない。
URL = re.compile(r"(?:https|ssh)://[A-Za-z0-9][A-Za-z0-9._~:/@+-]*"
                 r"|[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*:[A-Za-z0-9._~/+-]+")


class ImportFailed(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    project: str
    url: str
    branch: str
    base: str = ""
    src: str = ""
    tests: str = ""
    issue: str = ""


def check(value: dict[str, Any]) -> Request:
    """取り込みの要求を確かめる。形が合わなければ ValueError。"""
    def text(key: str) -> str:
        item = value.get(key, "")
        if not isinstance(item, str):
            raise ValueError(f"{key} must be a string")
        return item.strip()

    request = Request(text("project"), text("url"), text("branch"), text("base"),
                      text("src"), text("tests"), text("issue"))
    if not PROJECT.fullmatch(request.project) or request.project == "CURRENT":
        raise ValueError(f"not a project name: {request.project!r} "
                         "(lower-case letters, digits, '.', '_', '-')")
    if not URL.fullmatch(request.url):
        raise ValueError(f"not a repository URL: {request.url!r} "
                         "(https://, ssh:// or user@host:path)")
    for key in ("branch", "base"):
        name = getattr(request, key)
        if (name or key == "branch") and (not BRANCH.fullmatch(name) or ".." in name):
            raise ValueError(f"not a branch name: {name!r}")
    for key in ("src", "tests"):
        if not FENCE.fullmatch(getattr(request, key)):
            raise ValueError(f"{key} may use only letters, digits, '.', '_', '-' and '/'")
    if request.issue:
        issue_number(request.issue)
    return request


def unity_fence_check(dest: Path, request: Request) -> None:
    """Unity のプロジェクトなら、柵が Assets/ の下にあるか確かめる。無ければ ImportFailed。

    柵を省くと既定の src と tests になり、Unity のコードはすべて柵の外に出る。
    走行は詳細設計まで進んでから、既存のファイルを1つも触れずに止まる。
    """
    if not (dest / "ProjectSettings" / "ProjectVersion.txt").is_file():
        return
    outside = [f"--{key} {getattr(request, key) or '(default)'}" for key in ("src", "tests")
               if not getattr(request, key).startswith("Assets/")]
    if outside:
        raise ImportFailed(
            f"{request.project} is a Unity project, and its write fences must be under "
            f"Assets/ ({', '.join(outside)}). Pass them, e.g. --src Assets/Source --tests "
            f"Assets/Tests/Editor/Swa. Nothing was created on the sandbox.")


class Importer:
    def __init__(self, live: Live, workroot: Path = WORKROOT, push_host: str = PUSH_HOST,
                 sleep: Callable[[float], None] = time.sleep, issues: Issues | None = None):
        self.live = live
        self.workroot = workroot
        self.push_host = push_host
        self.sleep = sleep
        self.issues = issues or Issues()

    def run(self, request: Request, say: Callable[[str], None]) -> None:
        """5つの手順を順に流す。失敗した手順で ImportFailed を投げ、次に打つものを添える。"""
        dest = self.workroot / request.project
        target = self.push_target(request.project)

        # 閉じた Issue なら、クローンも箱のプロジェクトも作らずに断る。
        if request.issue:
            say(f"[0/5] Reading issue #{request.issue} ...")
            try:
                issue = self.issues.read(request.url, request.issue)
            except ValueError as error:
                raise ImportFailed(f"{error}. Nothing was imported.")
            say(f"      #{issue['number']} {issue['title']}")

        if (dest / ".git").exists():
            self._reuse(dest, request.url, say)
        elif dest.exists():
            raise ImportFailed(f"{dest} exists but is not a git clone.")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            say(f"[1/5] Cloning {request.url} into {dest} ...")
            self._git(None, "clone", "--quiet", "--", request.url, str(dest))

        self._pick_branch(dest, request, say)
        if request.issue:
            self._git(dest, "config", ISSUE_KEY.format(request.branch), request.issue)
        unity_fence_check(dest, request)

        say(f"[3/5] Creating project {request.project} on the sandbox ...")
        try:
            message = self.live.init_project(request.project, request.branch,
                                             request.src, request.tests)
        except ValueError as error:
            raise ImportFailed(f"swa project init failed. Nothing was pushed. {error}")
        for line in message.splitlines():
            say("      " + line)

        say(f"[4/5] Pushing {request.branch} to {target} ...")
        try:
            self._git(dest, "push", "--quiet", target, request.branch)
        except ImportFailed as error:
            raise ImportFailed(
                f"{error}\nThe empty project is left on the sandbox. After fixing the cause:\n"
                f"  git -C \"{dest}\" push {target} {request.branch}\n"
                f"  then switch to {request.project} on the dashboard (or: swa project use "
                f"{request.project})")

        say(f"[5/5] Switching the sandbox to {request.project} ...")
        try:
            say("      " + self.live.use_project(request.project))
        except ValueError as error:
            raise ImportFailed(f"swa project use failed. The branch is already on the "
                               f"sandbox. {error}")
        self._wait_for_switch(request.project, say)
        say(f"OK. {request.project} is the current project. Host clone: {dest}")

    def push_target(self, project: str) -> str:
        """箱のプロジェクトの bare。ホストは runner として swa-runner で push する。"""
        return f"{self.push_host}:/srv/swa/projects/{project}/repo.git"

    def _reuse(self, dest: Path, url: str, say: Callable[[str], None]) -> None:
        # 同じ名前の別リポジトリのクローンなら、違う履歴を push してしまう。
        have = self._git(dest, "remote", "get-url", "origin", check=False).strip()
        if have.casefold() != url.casefold():
            raise ImportFailed(f"{dest} is a clone of \"{have}\", not \"{url}\".")
        # ブランチを切り替えると、未コミットの変更は付いてくるか、切り替えを断る。
        # どちらも箱へ送るものに入れてはならない。
        if self._git(dest, "status", "--porcelain").strip():
            raise ImportFailed(f"{dest} has uncommitted changes. Commit or discard them first.")
        say(f"[1/5] Reusing {dest}, fetching origin ...")
        self._git(dest, "fetch", "--quiet", "origin")

    def _pick_branch(self, dest: Path, request: Request, say: Callable[[str], None]) -> None:
        branch, base = request.branch, request.base
        exists = any(self._git(dest, "rev-parse", "-q", "--verify", ref, check=False).strip()
                     for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"))
        if exists:
            say(f"[2/5] Switching to the existing branch {branch} ...")
            if base:
                say(f"      {branch} already exists; {base} is recorded as its parent only.")
            self._git(dest, "switch", "--quiet", branch)
            if not base:
                say("      No base branch given. For pull requests from the dashboard, record it:")
                say(f"        git -C \"{dest}\" config branch.{branch}.swaBase <base-branch>")
                return
        else:
            # 親を省くと origin の既定のブランチから作る。名前は下で記録するので、
            # origin/HEAD から読む。
            if not base:
                base = self._git(dest, "symbolic-ref", "--short", "refs/remotes/origin/HEAD",
                                 check=False).strip().removeprefix("origin/")
            if not base:
                raise ImportFailed("cannot tell the default branch of origin. Pass a base branch.")
            say(f"[2/5] Creating branch {branch} from origin/{base} ...")
            # --no-track: 新しいブランチが親ブランチへ push しないように。
            self._git(dest, "switch", "--quiet", "--no-track", "-c", branch, f"origin/{base}")
        # ダッシュボードは、承認した作業をこのブランチへの PR にして送る。
        self._git(dest, "config", f"branch.{branch}.swaBase", base)

    def _wait_for_switch(self, project: str, say: Callable[[str], None]) -> None:
        """箱の切り替えは一時ユニットで裏に回る。終わるまで `swa now` を見る。"""
        waited = 0.0
        value: dict[str, Any] = {}
        while waited < SWITCH_LIMIT_SECONDS:
            self.sleep(SWITCH_POLL_SECONDS)
            waited += SWITCH_POLL_SECONDS
            value = self.live.fetch()
            if "error" not in value and not (value.get("switch") or {}).get("running"):
                break
        else:
            raise ImportFailed("the switch is still running after "
                               f"{SWITCH_LIMIT_SECONDS // 60} minutes. Watch it on the "
                               "dashboard's project tab.")
        for line in (value.get("switch") or {}).get("log", []):
            say("      " + line)
        if value.get("project") != project:
            raise ImportFailed(f"the switch ended but the current project is "
                               f"{value.get('project')!r}. Read the log above.")

    def _git(self, cwd: Path | None, *args: str, check: bool = True) -> str:
        argv = ["git", *(["-C", str(cwd)] if cwd is not None else []), *args]
        try:
            proc = subprocess.run(argv, shell=False, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  stdin=subprocess.DEVNULL)
        except OSError as error:
            raise ImportFailed(f"could not run git: {error}")
        if check and proc.returncode != 0:
            reason = (proc.stderr or proc.stdout).strip().splitlines()
            raise ImportFailed(f"git {args[0]} failed" + (f": {reason[-1]}" if reason else "."))
        return proc.stdout


class ImportJob(BackgroundJob):
    """ダッシュボードから取り込みを1つだけ裏のスレッドで流し、進みを返す。"""

    def __init__(self, importer: Importer):
        super().__init__(TAIL_LINES)
        self.importer = importer
        self._project: str | None = None
        self._ok: bool | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state(), "project": self._project, "ok": self._ok}

    def start(self, value: dict[str, Any]) -> dict[str, Any]:
        request = check(value)
        self._launch("an import is already running", self._run, request,
                     project=request.project, ok=None)
        return self.status()

    def _run(self, request: Request) -> None:
        ok = False
        try:
            self.importer.run(request, self._say)
            ok = True
        except ValueError as error:
            self._say(f"ERROR: {error}")
        except Exception as error:  # スレッドの外へは何も届かない。画面に残す
            self._say(f"ERROR: {type(error).__name__}: {error}")
        finally:
            self._end(ok=ok)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="swa-import",
        description="put a branch of an existing repository on the sandbox as a new project")
    parser.add_argument("project")
    parser.add_argument("url")
    parser.add_argument("branch")
    parser.add_argument("base", nargs="?", default="")
    parser.add_argument("--src", default="", help="write fence for code (default: src)")
    parser.add_argument("--tests", default="", help="write fence for tests (default: tests)")
    parser.add_argument("--issue", default="",
                        help="number of the open GitHub issue the branch resolves")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    args = parser.parse_args(argv)
    try:
        request = check({key: getattr(args, key)
                         for key in ("project", "url", "branch", "base", "src", "tests", "issue")})
        Importer(Live(args.config)).run(request, lambda line: print(line, flush=True))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Next:  swa go <requirements>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
