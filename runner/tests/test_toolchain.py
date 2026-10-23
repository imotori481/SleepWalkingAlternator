"""箱の側の故障を、設計の誤りとして中段に戻さない。

thm01（取り込んだ Unity のプロジェクト）では、柵が Assets/ の外にあり、参照も無く、
フィードには SDK 8 の求めるパッケージが無かった。どれも設計にもソルバーにも直せない
のに、FAILURE.md は詳細設計を直すよう案内した。

    python3 -m unittest discover -s runner/tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import swa  # noqa: E402

UNITY = {"src": "Assets/Source", "tests": "Assets/Tests/Editor/Swa"}


class AUnityProjectThatCannotRun(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "project"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: 6000.3.10f1\n", encoding="utf-8")
        self.refs = self.root / "unity-refs"
        for p in (mock.patch.object(swa, "PROJECT", self.project),
                  mock.patch.object(swa, "UNITY_REFS", self.refs),
                  mock.patch.dict(swa.LANGUAGE, {"unity_refs": True})):
            p.start()
            self.addCleanup(p.stop)

    def problem(self, layout: dict) -> str | None:
        with mock.patch.dict(swa.LAYOUT, layout):
            return swa.unity_problem()

    def test_a_fence_outside_assets_is_refused(self):
        self.assertIn("src=Source", self.problem({"src": "Source", "tests": "tests"}))

    def test_missing_references_are_refused(self):
        self.assertIn("swa-unity-refs", self.problem(UNITY))

    def test_with_references_it_runs(self):
        (self.refs / "refs").mkdir(parents=True)
        self.assertIsNone(self.problem(UNITY))

    def test_a_project_that_is_not_unity_is_left_alone(self):
        (self.project / "ProjectSettings" / "ProjectVersion.txt").unlink()
        self.assertIsNone(self.problem({"src": "src", "tests": "tests"}))


class AToolchainThatFails(unittest.TestCase):
    def test_a_failed_restore_stops_the_run_without_a_verdict(self):
        events = []
        with mock.patch.dict(swa.LANGUAGE, {"name": "csharp"}), \
             mock.patch.object(swa, "STATE", Path(tempfile.gettempdir()) / "swa-toolchain"), \
             mock.patch.object(swa, "report_now"), \
             mock.patch.object(swa, "test_argv", return_value=([], None)), \
             mock.patch.object(swa, "ledger", lambda e, **f: events.append((e, f))), \
             mock.patch.object(swa, "prepare_dotnet", return_value="error NU1101: X"):
            with self.assertRaises(swa.ToolchainBroken) as caught:
                swa.pytest_run("red-1", ["tests/BoardTests.cs"])
        self.assertEqual(caught.exception.phase, "RED")
        self.assertEqual(events[0][0], "TOOLCHAIN_FAILURE")
        self.assertFalse(issubclass(swa.ToolchainBroken, swa.Halt))

    def test_run_all_stays_downstream(self):
        events = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "stage.json").write_text(json.dumps({"stage": "downstream"}),
                                             encoding="utf-8")
            (root / "tasks.json").write_text(json.dumps({"steps": [{"id": "S1"}]}),
                                             encoding="utf-8")
            with mock.patch.object(swa, "STAGE_FILE", root / "stage.json"), \
                 mock.patch.object(swa, "TASKS", root / "tasks.json"), \
                 mock.patch.object(swa, "load_settings"), \
                 mock.patch.object(swa, "green_steps", return_value=set()), \
                 mock.patch.object(swa, "ledger", lambda e, **f: events.append((e, f))), \
                 mock.patch.object(swa, "fail_module") as fail, \
                 mock.patch.object(swa, "run_step",
                                   side_effect=swa.ToolchainBroken("RED", "NU1101")):
                self.assertEqual(swa.cmd_run_all(), 7)
                self.assertEqual(swa.read_stage()["stage"], "downstream")
        fail.assert_not_called()
        self.assertIn(swa.TOOLCHAIN_FAILED, events[-1][1]["reason"])


class AFailureInFilesTheModuleDoesNotWrite(unittest.TestCase):
    def test_failure_md_points_at_the_sandbox_first(self):
        with tempfile.TemporaryDirectory() as temp:
            failure = Path(temp) / "FAILURE.md"
            run_ = swa.TestRun(0, 0, 4, 0, [
                "<build failed: Assets/Source/UI/UIResult.cs>",
                "<build failed: Assets/Source/Core/A.cs>",
                "<build failed: Assets/Source/Core/B.cs>",
                "<build failed: Assets/Source/Core/C.cs>",
                "<build failed: Assets/Source/Core/D.cs>"], [], "")
            step = {"id": "changes/ResultTips", "files_write": ["Assets/Source/UI/UIResult.cs"]}
            with mock.patch.object(swa, "FAILURE", failure), \
                 mock.patch.object(swa, "failed_modules", return_value=[step["id"]]), \
                 mock.patch.object(swa, "attempt_schedule", return_value=[1, 2, 3]), \
                 mock.patch.object(swa, "write_stage"), \
                 mock.patch.object(swa, "ledger"), \
                 mock.patch.object(swa, "commit_paths"):
                swa.fail_module(step, swa.Halt("RED_GATE", "R2"), 0, run_)
            text = failure.read_text(encoding="utf-8")
        self.assertIn("Assets/Source/Core/A.cs, Assets/Source/Core/B.cs, "
                      "Assets/Source/Core/C.cs ほか1件", text)
        self.assertIn("`swa reopen changes/ResultTips` のあと `swa approve`", text)

    def test_a_failure_in_its_own_file_says_nothing_extra(self):
        with tempfile.TemporaryDirectory() as temp:
            failure = Path(temp) / "FAILURE.md"
            run_ = swa.TestRun(0, 0, 1, 0, ["<build failed: Assets/Source/UI/UIResult.cs>"],
                               [], "")
            step = {"id": "changes/ResultTips", "files_write": ["Assets/Source/UI/UIResult.cs"]}
            with mock.patch.object(swa, "FAILURE", failure), \
                 mock.patch.object(swa, "failed_modules", return_value=[step["id"]]), \
                 mock.patch.object(swa, "attempt_schedule", return_value=[1, 2, 3]), \
                 mock.patch.object(swa, "write_stage"), \
                 mock.patch.object(swa, "ledger"), \
                 mock.patch.object(swa, "commit_paths"):
                swa.fail_module(step, swa.Halt("RED_GATE", "R2"), 0, run_)
            self.assertNotIn("swa-unity-refs", failure.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
