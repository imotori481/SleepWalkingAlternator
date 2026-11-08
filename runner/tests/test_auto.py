"""Auto/Manual。Auto は人の代わりにせきを通すが、関門は人のときと同じコマンドが確かめる。

`auto advance` は走行がせきに着くたびに呼ばれ、次に流す走行の名前を最後の行に出す。
繰り返した回数は台帳から数え、人の手が入ると数え直す。

    python3 -m unittest discover -s runner/tests
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import swa  # noqa: E402
from test_design import Python, ac, doc  # noqa: E402


class Auto(Python):
    """ファイルは一時ディレクトリに置き、git には触れない。台帳は本物を書く。"""

    def setUp(self) -> None:
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.root = root
        for name, value in {
            "PROJECT": root, "PLAN": root / "plan", "STATE": root / ".runner",
            "STAGE_FILE": root / "plan" / "stage.json", "LEDGER": root / "plan" / "ledger.jsonl",
            "INTERFACE": root / "plan" / "INTERFACE.json", "FAILURE": root / "plan" / "FAILURE.md",
            "CRITIQUE": root / "plan" / "CRITIQUE.json",
            "TASKS": root / ".runner" / "tasks.json", "DOCS_BASIC": root / "docs" / "basic",
            "DOCS_MODULES": root / "docs" / "modules", "DOCS_CHANGES": root / "docs" / "changes",
            "AC": root / "ac",
            "HUMAN_AUTO": root / "human" / "in" / "AUTO.json",
            "HUMAN_COMMENT": root / "human" / "in" / "COMMENT.md",
            "commit_paths": lambda *a: None,
            "clean_tree": lambda: None,
            "basic_overview": lambda: "",
        }.items():
            p = mock.patch.object(swa, name, value)
            p.start()
            self.addCleanup(p.stop)
        (root / "plan").mkdir()

    def advance(self) -> str:
        """auto advance を流し、最後の行を返す。"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("sys.stderr"):
            self.assertEqual(swa.cmd_auto_advance(), 0)
        return out.getvalue().strip().splitlines()[-1]

    def events(self, name: str) -> list[dict]:
        return [r for r in swa.ledger_records() if r.get("event") == name]

    def record(self, event: str, **fields) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            swa.ledger(event, **fields)

    def design(self) -> str:
        swa.write_texts(swa.DOCS_MODULES, {
            "a": doc({"provides": "def a() -> int", "entry": True})}, ".md")
        swa.write_texts(swa.AC, {"a": ac()}, ".json")
        modules, _ = swa.current_design()
        return swa.design_digest(modules)

    def critique(self, digest: str, findings: int) -> None:
        swa.CRITIQUE.write_text(json.dumps({"digest": digest, "findings": [
            {"title": f"指摘 {n}", "evidence": "根拠", "machine_would_notice": False}
            for n in range(findings)]}), encoding="utf-8")

    def auto(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            swa.cmd_auto_set("auto")


class TheSwitch(Auto):
    def test_manual_unless_auto_is_written(self):
        self.assertEqual(swa.read_auto(), "manual")
        swa.HUMAN_AUTO.parent.mkdir(parents=True)
        for text in ("{", '{"mode": "always"}', "[]"):
            with self.subTest(text=text):
                swa.HUMAN_AUTO.write_text(text, encoding="utf-8")
                self.assertEqual(swa.read_auto(), "manual")

    def test_switching_is_written_and_left_in_the_ledger(self):
        self.auto()
        self.assertEqual(swa.read_auto(), "auto")
        self.assertEqual(swa.HUMAN_AUTO.stat().st_mode & 0o777, 0o644)
        with contextlib.redirect_stdout(io.StringIO()):
            swa.cmd_auto_set("manual")
        self.assertEqual([r["mode"] for r in self.events("AUTO_MODE")], ["auto", "manual"])

    def test_manual_waits_for_the_human_at_every_gate(self):
        swa.write_stage(stage="upstream", language="python")
        swa.write_texts(swa.DOCS_BASIC, {"design": "## 概要\n放置ゲーム。\n"}, ".md")
        self.assertEqual(self.advance(), "manual")


class TheGates(Auto):
    def setUp(self) -> None:
        super().setUp()
        self.auto()

    def test_the_basic_design_is_approved_once_it_is_written(self):
        swa.write_stage(stage="upstream", language="python")
        self.assertEqual(self.advance(), "stop")
        self.assertEqual(len(self.events("AUTO_STOP")), 1)
        swa.write_texts(swa.DOCS_BASIC, {"design": "## 概要\n放置ゲーム。\n"}, ".md")
        self.assertEqual(self.advance(), "approve-basic")

    def test_a_design_the_critic_has_not_read_is_critiqued_first(self):
        self.design()
        swa.write_stage(stage="midstream", language="python", critiqued="another digest")
        self.assertEqual(self.advance(), "critique")

    def test_a_design_without_findings_is_approved(self):
        digest = self.design()
        swa.write_stage(stage="midstream", language="python", critiqued=digest)
        self.critique(digest, 0)
        self.assertEqual(self.advance(), "approve-modules")
        self.assertFalse(swa.HUMAN_COMMENT.exists())

    def test_findings_are_sent_back_twice_and_then_left_in_the_ledger(self):
        digest = self.design()
        swa.write_stage(stage="midstream", language="python", critiqued=digest)
        self.critique(digest, 2)
        for _ in range(swa.AUTO_LIMITS["redrafts"]):
            self.assertEqual(self.advance(), "redraft-modules")
            self.assertIn("指摘 1", swa.HUMAN_COMMENT.read_text(encoding="utf-8"))
            self.record("MODULES_DRAFT", by="auto")
        self.assertEqual(self.advance(), "approve-modules")
        self.assertEqual(self.events("AUTO_FINDINGS_LEFT")[0]["count"], 2)

    def test_findings_about_another_design_are_not_sent_back(self):
        digest = self.design()
        swa.write_stage(stage="midstream", language="python", critiqued=digest)
        self.critique("another digest", 3)
        self.assertEqual(self.advance(), "approve-modules")

    def test_a_human_s_rejection_counts_the_redrafts_again(self):
        digest = self.design()
        swa.write_stage(stage="midstream", language="python", critiqued=digest)
        self.critique(digest, 1)
        self.record("AUTO_REDRAFT")
        self.record("AUTO_REDRAFT")
        self.record("MODULES_DRAFT", by="human")
        self.assertEqual(self.advance(), "redraft-modules")

    def test_the_downstream_goes_on_and_the_final_review_is_left_to_the_human(self):
        swa.write_stage(stage="downstream", language="python")
        self.assertEqual(self.advance(), "continue")
        swa.write_stage(stage="review", language="python")
        self.assertEqual(self.advance(), "stop")


class TheFailures(Auto):
    def setUp(self) -> None:
        super().setUp()
        self.auto()
        self.design()
        swa.FAILURE.write_text("# 下流で止まったモジュール: a\n\n- 理由: RED を取れない\n",
                               encoding="utf-8")

    def fail(self) -> None:
        swa.write_stage(stage="midstream", language="python", open=[])
        self.record("FAILED", step="a", phase="RED", reason="no red", modules=["a"])

    def test_a_failed_module_is_sent_back_with_the_reason_as_the_comment(self):
        self.fail()
        self.assertEqual(self.advance(), "redraft-modules")
        self.assertEqual((swa.read_stage()["stage"], swa.read_stage()["open"]),
                         ("midstream", ["a"]))
        self.assertIn("RED を取れない", swa.HUMAN_COMMENT.read_text(encoding="utf-8"))
        self.assertEqual(self.events("SENT_BACK")[-1]["by"], "auto")

    def test_the_third_failure_of_the_same_module_goes_to_the_human(self):
        for _ in range(swa.AUTO_LIMITS["reopens"]):
            self.fail()
            self.assertEqual(self.advance(), "redraft-modules")
        self.fail()
        self.assertEqual(self.advance(), "stop")
        self.assertEqual(swa.read_stage()["open"], [])
        self.assertEqual(self.events("AUTO_STOP")[-1]["step"], "a")

    def test_a_human_s_reopen_counts_the_failures_again(self):
        for _ in range(swa.AUTO_LIMITS["reopens"]):
            self.fail()
            self.advance()
        self.record("SENT_BACK", modules=["a"], by="human")
        self.fail()
        self.assertEqual(self.advance(), "redraft-modules")


class TheCounts(unittest.TestCase):
    def test_redrafts_restart_when_the_stage_moves_and_reopens_only_for_a_human(self):
        records = [{"event": "AUTO_REDRAFT"}, {"event": "AUTO_REOPEN", "step": "a"},
                   {"event": "SENT_BACK", "by": "auto"}, {"event": "AUTO_REDRAFT"},
                   {"event": "MODULES_APPROVE", "by": "auto"},
                   {"event": "AUTO_REOPEN", "step": "a"}, {"event": "AUTO_REOPEN", "step": "b"}]
        self.assertEqual(swa.auto_counts(records), {"redrafts": 0, "reopens": {"a": 2, "b": 1}})
        self.assertEqual(swa.auto_counts(records + [{"event": "BASIC_APPROVE", "by": "human"}]),
                         {"redrafts": 0, "reopens": {}})


if __name__ == "__main__":
    unittest.main()
