"""実装の試行の時間切れは、試行1回分の失敗で、モジュールを止める理由ではない。

run 8 の S10 では、2回目の実装でソルバーが制限時間内に終わらず、それがそのまま
停止になった。残り1回の試行は使われなかった。

    python3 -m unittest discover -s runner/tests
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import swa  # noqa: E402

STEP = {"id": "S10", "files_write": ["src/main.ts"], "files_test": ["tests/main.test.ts"]}


class TheTimeoutIsNamed(unittest.TestCase):
    def test_it_is_still_a_halt_where_nobody_catches_it(self):
        # TEST_WRITE と STUB の時間切れは、今までどおりステップを止める。
        self.assertTrue(issubclass(swa.SolverTimeout, swa.Halt))

    def test_exit_124_from_solver_run_raises_it(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(swa, "BRIEF_DIR", Path(temp)), \
             mock.patch.object(swa.shutil, "chown"), \
             mock.patch.object(swa, "run_agent", return_value=subprocess.CompletedProcess(
                 ["solver-run"], 124, "", "")):
            with self.assertRaises(swa.SolverTimeout) as raised:
                swa.call_solver("IMPL", "brief")
        self.assertEqual(raised.exception.phase, "IMPL")

    def test_other_failures_are_not_timeouts(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(swa, "BRIEF_DIR", Path(temp)), \
             mock.patch.object(swa.shutil, "chown"), \
             mock.patch.object(swa, "run_agent", return_value=subprocess.CompletedProcess(
                 ["solver-run"], 3, "", "no credentials")):
            with self.assertRaises(swa.Halt) as raised:
                swa.call_solver("IMPL", "brief")
        self.assertNotIsInstance(raised.exception, swa.SolverTimeout)


class AbsorbingTheTimeout(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.events: list[tuple[str, dict]] = []
        self.discard = mock.Mock(return_value=["src/main.ts"])
        for p in (mock.patch.object(swa, "PROJECT", self.project),
                  mock.patch.object(swa, "adopt"),
                  mock.patch.object(swa, "assert_touched"),
                  mock.patch.object(swa, "discard_attempt", self.discard),
                  mock.patch.object(swa, "ledger",
                                    lambda event, **f: self.events.append((event, f)))):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.temp.cleanup)

    def test_the_attempt_is_recorded_and_its_work_discarded(self):
        swa.absorb_timeout(STEP, 2, "claude", {}, "expected 0 to be 1")
        self.discard.assert_called_once_with(["src/main.ts"])
        self.assertEqual([e for e, _ in self.events], ["SOLVER_TIMEOUT"])
        fields = self.events[0][1]
        self.assertEqual((fields["step"], fields["attempt"], fields["backend"]),
                         ("S10", 2, "claude"))
        self.assertEqual(fields["seconds"], swa.TIMEOUTS["solver"])

    def test_the_next_brief_says_so_and_keeps_the_failures(self):
        text = swa.absorb_timeout(STEP, 2, "claude", {}, "expected 0 to be 1")
        self.assertIn("ran out of time", text)
        self.assertIn("Nothing it wrote was kept", text)
        self.assertIn("expected 0 to be 1", text)

    def test_a_modified_frozen_test_still_halts(self):
        # 時間切れの前に柵を破っていれば、それは試行の失敗ではない。
        test_file = self.project / "tests" / "main.test.ts"
        test_file.parent.mkdir()
        test_file.write_text("changed", encoding="utf-8")
        with self.assertRaises(swa.Halt) as raised:
            swa.absorb_timeout(STEP, 2, "claude",
                                {"tests/main.test.ts": "not the same digest"}, "")
        self.assertNotIsInstance(raised.exception, swa.SolverTimeout)
        self.discard.assert_not_called()

    def test_a_write_outside_the_allowlist_still_halts(self):
        swa.assert_touched.side_effect = swa.Halt("IMPL", "solver wrote outside its allowlist")
        with self.assertRaises(swa.Halt):
            swa.absorb_timeout(STEP, 2, "claude", {}, "")
        self.discard.assert_not_called()


class TheLoopMovesOn(unittest.TestCase):
    """run_step の IMPL のループが、時間切れの後に次の試行へ進むこと。

    ソルバー、テストの実行、git に触る部分はすべて差し替える。確かめたいのは
    ループの流れだけだ。
    """

    FULL_STEP = {**STEP, "goal": "g", "depends_on": [], "expected_tests": 1,
                 "max_attempts": 3, "review_gate": False, "kind": "integration",
                 "acceptance": [{"case": "normal", "given": "g", "then": "1"}],
                 "contracts": {"provides": ["src/main.ts: function start(): void"]}}

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / ".runner").mkdir()
        (root / ".runner" / "tasks.json").write_text('{"steps": []}', encoding="utf-8")
        self.failed: list[swa.Halt] = []
        self.greens: list[int] = []
        red = swa.TestRun(1, 1, 0, 0, ["AssertionError"], [], "")
        self.green = swa.TestRun(1, 0, 0, 0, [], ["t"], "")
        self.fail = swa.TestRun(1, 1, 0, 0, ["AssertionError"], [], "",
                                 failure_details=["t\n    expected 0 to be 1"])
        self.runs = [red]
        patches = {
            "STATE": root / ".runner", "TASKS": root / ".runner" / "tasks.json",
            "load_settings": lambda tasks: None,
            "load_plan": lambda sid: (self.FULL_STEP, "context"),
            "ledger": lambda event, **f: None,
            "touched_paths": lambda: set(),
            "set_writable": lambda **kw: None,
            "assert_touched": lambda *a: None,
            "assert_written": lambda *a: None,
            "check_baseline": lambda: None,
            "head_sources": lambda paths: {},
            "generate_stub": lambda step, lines, originals: {},
            "freeze_tests": lambda: {},
            "frozen_tests_text": lambda step: "",
            "pytest_run": lambda tag, files: self.runs.pop(0),
            "absorb_timeout": lambda *a: "ran out of time",
            "complete_green": lambda sid, goal, n, design="": self.greens.append(n),
            "fail_module": lambda step, halt, n, run: self.failed.append(halt),
        }
        for name, value in patches.items():
            p = mock.patch.object(swa, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.temp.cleanup)

    def solver(self, impl_results):
        """TEST_WRITE は通し、IMPL は impl_results の順に振る舞う。"""
        results = iter(impl_results)

        def call(phase, brief, backend=None):
            if phase != "IMPL":
                return ""
            outcome = next(results)
            if outcome == "timeout":
                raise swa.SolverTimeout("IMPL", "solver hit its own timeout in solver-run")
            return ""
        return mock.patch.object(swa, "call_solver", call)

    def test_a_timeout_spends_one_attempt_and_the_next_one_runs(self):
        self.runs.append(self.green)
        with self.solver(["timeout", "ok"]):
            self.assertEqual(swa.run_step("S10"), 0)
        self.assertEqual(self.greens, [2])
        self.assertEqual(self.failed, [])

    def test_running_out_of_attempts_still_fails_and_says_why(self):
        self.runs.append(self.fail)
        with self.solver(["timeout", "ok", "timeout"]):
            self.assertEqual(swa.run_step("S10"), 2)
        self.assertEqual(len(self.failed), 1)
        self.assertIn("still failing after 3 attempts", self.failed[0].reason)
        self.assertIn("2 of them ran out of time", self.failed[0].reason)


if __name__ == "__main__":
    unittest.main()
