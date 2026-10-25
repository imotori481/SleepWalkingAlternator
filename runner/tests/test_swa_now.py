"""`swa now` が、ログから今の回のトークン数とクリティックの指摘を読むこと。

台帳は runner だけが読め、写しに届くのはコミットのときだけだ。計画づくりの途中や
refine で止まったときの消費と指摘は、保守ユーザーが読めるログにしか無い。

    python3 -m unittest discover -s runner/tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "provision"))

import swa_now  # noqa: E402


class CurrentLoop(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.logs = Path(temp.name)

    def log(self, name: str, *lines: str) -> None:
        (self.logs / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def loop(self, project: str = "game"):
        return swa_now.current_loop(swa_now.project_logs(str(self.logs), project))

    def test_usage_lines_are_summed_per_role_from_the_last_go(self):
        self.log("game-20260101-000000.log",
                 "=== swa go 開始 (2026-01-01 00:00:00) プロジェクト=game",
                 "[USAGE] who=planner phase=PLAN_PROPOSE model=m in=100 out=1 sec=1")
        self.log("game-20260102-000000.log",
                 "=== swa go 開始 (2026-01-02 00:00:00) プロジェクト=game",
                 "[USAGE] who=planner phase=PLAN_PROPOSE model=m in=10 out=2 sec=1 usd=0.10",
                 "[USAGE] who=critic phase=CRITIQUE model=m in=5 out=1 sec=1")
        self.log("game-20260102-010000.log",
                 "=== swa continue 開始 (2026-01-02 01:00:00) プロジェクト=game",
                 "[USAGE] who=solver phase=IMPL model=m in=7 out=3 sec=1 ERROR")
        loop = self.loop()
        self.assertTrue(loop["started"].startswith("2026-01-02T00:00:00"))
        self.assertEqual(loop["tokens"], {"planner": 12, "critic": 6, "solver": 10})
        self.assertEqual(loop["calls"], 3)
        self.assertEqual(loop["usd"], {"planner": 0.10, "critic": 0.0, "solver": 0.0})
        # read と write の無い行では、入力のうちキャッシュの分が分からない。
        self.assertIsNone(loop["kinds"])

    def test_cache_reads_and_writes_are_split_out_of_the_input(self):
        self.log("game-20260102-000000.log",
                 "=== swa go 開始 (2026-01-02 00:00:00) プロジェクト=game",
                 "[USAGE] who=critic phase=CRITIQUE model=m in=110 out=20 read=100 write=6 "
                 "sec=4 usd=0.01",
                 "[USAGE] who=critic phase=CRITIQUE model=m in=50 out=5 read=40 write=8 "
                 "sec=2 usd=0.02")
        loop = self.loop()
        self.assertEqual(loop["kinds"]["critic"],
                         {"input": 6, "cache_write": 14, "cache_read": 140, "output": 25})
        self.assertEqual(loop["kinds"]["solver"],
                         {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0})
        self.assertEqual(loop["tokens"]["critic"], 185)
        self.assertAlmostEqual(loop["usd"]["critic"], 0.03)

    def test_the_last_critique_is_kept_with_the_time_of_its_command(self):
        self.log("game-20260102-000000.log",
                 "=== swa go 開始 (2026-01-02 00:00:00) プロジェクト=game",
                 "--- swa.py modules draft (2026-01-02 00:05:00)",
                 "=== critique of the module design ===",
                 "## modules",
                 "1. first",
                 "",
                 "=== swa 終了 (2026-01-02 00:10:00): 詳細設計を書き、クリティックが読んだ")
        self.log("game-20260102-001500.log",
                 "=== swa redraft-modules 開始 (2026-01-02 00:15:00) プロジェクト=game",
                 "--- swa.py modules draft (2026-01-02 00:15:00)",
                 "=== critique of the module design ===",
                 "## modules",
                 "1. second",
                 "   NO GATE WOULD CATCH THIS",
                 "",
                 "next: modules approve, or write a comment and run modules draft again",
                 "=== swa 終了 (2026-01-02 00:30:00): 詳細設計を書き、クリティックが読んだ")
        critique = self.loop()["critique"]
        self.assertTrue(critique["at"].startswith("2026-01-02T00:15:00"))
        self.assertEqual(critique["text"], "=== critique of the module design ===\n"
                                           "## modules\n1. second\n   NO GATE WOULD CATCH THIS")

    def test_other_projects_and_the_latest_link_are_not_read(self):
        self.log("game-latest.log", "=== swa go 開始 (2026-01-03 00:00:00) プロジェクト=game")
        self.log("game-2-20260104-000000.log",
                 "=== swa go 開始 (2026-01-04 00:00:00) プロジェクト=game-2")
        self.assertIsNone(self.loop())

    def test_the_outcome_follows_the_run_and_the_last_result(self):
        self.assertEqual(swa_now.outcome(True, None), "running")
        self.assertEqual(swa_now.outcome(False, "swa 終了 (x): 全モジュールが緑になった"),
                         "green")
        self.assertEqual(swa_now.outcome(False, "swa 終了 (x): 利用枠が尽きた"), "stopped")


class Projects(unittest.TestCase):
    """プロジェクトの一覧と切り替えの状態。保守ユーザーが sudo なしで読める所だけを読む。"""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()

    def project(self, name: str, branch: str | None = "main", parked: bool = False) -> None:
        repo = self.root / "projects" / name / "repo.git"
        repo.mkdir(parents=True)
        if branch:
            (repo / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        if parked:
            (self.root / "projects" / name / "parked").mkdir()

    def test_each_project_has_a_state_and_the_branch_of_its_bare(self):
        self.project("game", "swa/feature")
        self.project("old", parked=True)
        self.project("next", branch=None)
        (self.root / "projects" / "CURRENT").write_text("game\n", encoding="utf-8")
        self.assertEqual(swa_now.projects(str(self.logs), "game"), [
            {"name": "game", "state": "current", "branch": "swa/feature", "head": None},
            {"name": "next", "state": "new", "branch": None, "head": None},
            {"name": "old", "state": "parked", "branch": "main", "head": None},
        ])

    def test_each_project_has_the_commit_its_branch_points_at(self):
        self.project("game", "swa/feature")
        self.project("old")
        loose = self.root / "projects" / "game" / "repo.git" / "refs" / "heads" / "swa"
        loose.mkdir(parents=True)
        (loose / "feature").write_text("a" * 40 + "\n", encoding="utf-8")
        (self.root / "projects" / "old" / "repo.git" / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted\n"
            + "b" * 40 + " refs/heads/main\n" + "c" * 40 + " refs/heads/other\n",
            encoding="utf-8")
        heads = {p["name"]: p["head"] for p in swa_now.projects(str(self.logs), "game")}
        self.assertEqual(heads, {"game": "a" * 40, "old": "b" * 40})

    def test_a_box_without_projects_has_an_empty_list(self):
        self.assertEqual(swa_now.projects(str(self.logs), "default"), [])

    def test_the_switch_carries_the_tail_of_its_log(self):
        self.assertIsNone(swa_now.switch(str(self.logs), False))
        self.assertEqual(swa_now.switch(str(self.logs), True), {"running": True, "log": []})
        lines = [f"line {n}" for n in range(30)]
        (self.logs / "switch.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(swa_now.switch(str(self.logs), False),
                         {"running": False, "log": lines[-20:]})


if __name__ == "__main__":
    unittest.main()
