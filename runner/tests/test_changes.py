"""既存のモードの、変更という単位。

既存のモードでは、下流の単位がモジュールと変更の2種類になる。モジュールは新しい
ファイル1つで、契約のスタブに対して Red を取る。変更は変える振る舞い1つで、触る
既存のファイルをすべて持ち、署名が変わらなければスタブを作らず、今のコードに
対して Red を取る。

    python3 -m unittest discover -s runner/tests
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import swa  # noqa: E402

CRITERIA = [
    {"case": "normal", "kind": "unit", "given": "a board with a bonus cell",
     "then": "score returns 12"},
]


def doc(*lines: dict, behaviour: str = "得点に倍率を掛ける。") -> str:
    contract = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines)
    return (f"# 変更\n\n## 振る舞い\n{behaviour}\n\n"
            f"## 契約\n```ndjson contract\n{contract}\n```\n")


def ac(criteria: list[dict] = CRITERIA) -> str:
    return json.dumps({"criteria": criteria})


FULL = [
    {"case": "normal", "kind": "unit", "given": "a 3x3 board", "then": "returns 9"},
    {"case": "boundary", "kind": "unit", "given": "an empty board", "then": "returns 0"},
    {"case": "error", "kind": "unit", "given": "a width of -1", "then": "raises ValueError"},
]


class Existing(unittest.TestCase):
    """既存のモードの Python の箱。HEAD には src/game/board.py と src/game/rules.py がある。"""

    HEAD = {"src/game/board.py", "src/game/rules.py"}

    def setUp(self) -> None:
        for p in (mock.patch.dict(swa.LANGUAGE, swa.LANGUAGES["python"], clear=True),
                  mock.patch.dict(swa.LAYOUT, swa.LAYOUT_DEFAULT),
                  mock.patch.dict(swa.RUN, {"mode": "existing"}),
                  mock.patch.object(swa, "head_files", return_value=self.HEAD),
                  mock.patch.object(swa, "existing_declarations", return_value={
                      "src/game/board.py": ["def score(board: Board) -> int -- defined in game.board"],
                      "src/game/rules.py": ["def bonus() -> int -- defined in game.rules"]})):
            p.start()
            self.addCleanup(p.stop)

    def design(self, docs=None, changes=None, acs=None):
        docs = docs or {}
        changes = changes or {}
        if acs is None:
            acs = {**{mid: ac(FULL) for mid in docs},
                   **{swa.CHANGE_PREFIX + name: ac() for name in changes}}
        return swa.design_problems(docs, acs, changes)


class TheShapeOfAChange(Existing):
    def test_a_well_formed_change_passes_without_every_case(self):
        units, problems = self.design(changes={
            "ScoreBonus": doc({"edits": "game/board"}, {"edits": "game/rules"})})
        self.assertEqual(problems, [])
        change = units["changes/ScoreBonus"]
        self.assertEqual(change["unit"], "change")
        self.assertEqual(change["files"], ["src/game/board.py", "src/game/rules.py"])
        self.assertEqual(change["files_test"], ["tests/test_changes_ScoreBonus.py"])

    def test_a_change_edits_only_files_that_exist(self):
        _, problems = self.design(changes={"Bonus": doc({"edits": "game/missing"})})
        self.assertTrue(any(p.startswith("changes/Bonus.md: edits game/missing, which is not")
                            for p in problems), problems)

    def test_a_change_names_the_files_it_edits(self):
        _, problems = self.design(changes={
            "Bonus": doc({"requires": "def bonus() -> int", "from": "game/rules"})})
        self.assertTrue(any("names no file it edits" in p for p in problems), problems)

    def test_a_provided_name_lives_in_a_file_the_change_edits(self):
        _, problems = self.design(changes={"Bonus": doc(
            {"edits": "game/board"},
            {"provides": "def score(board: Board, rate: int) -> int", "in": "game/rules"})})
        self.assertTrue(any("which is not one of the files it edits" in p for p in problems),
                        problems)

    def test_a_change_s_name_becomes_a_test_name(self):
        _, problems = self.design(changes={"score-bonus": doc({"edits": "game/board"})})
        self.assertTrue(any(p.startswith("changes/score-bonus.md: a change's name")
                            for p in problems), problems)

    def test_a_module_may_not_rewrite_an_existing_file(self):
        _, problems = self.design(docs={
            "game/board": doc({"provides": "def score() -> int", "entry": True})})
        self.assertTrue(any(p.startswith("modules/game/board.md: src/game/board.py already "
                                         "exists") for p in problems), problems)

    def test_a_module_may_not_sit_where_the_changes_are(self):
        _, problems = self.design(docs={
            "changes/x": doc({"provides": "def x() -> int", "entry": True})})
        self.assertTrue(any("is kept for the changes" in p for p in problems), problems)

    def test_criteria_without_a_change_are_named(self):
        _, problems = self.design(changes={"Bonus": doc({"edits": "game/board"})},
                                  acs={"changes/Bonus": ac(), "changes/Gone": ac()})
        self.assertIn("ac/changes/Gone.json: there is no changes/Gone.md for it", problems)

    def test_the_new_mode_has_no_changes(self):
        with mock.patch.dict(swa.RUN, {"mode": "new"}):
            _, problems = self.design(
                docs={"game/new": doc({"provides": "def f() -> int", "entry": True})},
                changes={"Bonus": doc({"edits": "game/board"})})
        self.assertTrue(any(p.startswith("changes/: changes are for the existing mode")
                            for p in problems), problems)


class TheInterfaceCheckWithChanges(Existing):
    def check(self, docs=None, changes=None) -> tuple[dict, list[str]]:
        units, problems = self.design(docs, changes)
        self.assertEqual(problems, [])
        return units, swa.interface_problems(units)

    def test_a_module_that_uses_a_changed_signature_comes_after_the_change(self):
        units, problems = self.check(
            docs={"game/report": doc(
                {"requires": "def score(board: Board, rate: int) -> int", "from": "game/board"},
                {"provides": "def report() -> str", "entry": True})},
            changes={"Rate": doc(
                {"edits": "game/board"},
                {"provides": "def score(board: Board, rate: int) -> int", "in": "game/board"})})
        self.assertEqual(problems, [])
        self.assertEqual(swa.module_deps(units)["game/report"], ["changes/Rate"])
        self.assertEqual(swa.module_order(units)[0], ["changes/Rate", "game/report"])

    def test_the_signature_must_match_what_the_change_puts_there(self):
        _, problems = self.check(
            docs={"game/report": doc(
                {"requires": "def score(board: Board) -> int", "from": "game/board"},
                {"provides": "def report() -> str", "entry": True})},
            changes={"Rate": doc(
                {"edits": "game/board"},
                {"provides": "def score(board: Board, rate: int) -> int", "in": "game/board"})})
        self.assertTrue(any(p.startswith("署名の一致: game/report requires "
                                         "`def score(board: Board) -> int` from game/board")
                            for p in problems), problems)

    def test_from_names_a_file_not_a_change(self):
        _, problems = self.check(
            docs={"game/report": doc(
                {"requires": "def bonus() -> int", "from": "changes/Rate"},
                {"provides": "def report() -> str", "entry": True})},
            changes={"Rate": doc({"edits": "game/rules"})})
        self.assertTrue(any("`from` names a file" in p for p in problems), problems)

    def test_what_a_change_provides_is_not_unused(self):
        # 既存のコードがすでに呼んでいる。
        _, problems = self.check(changes={"Rate": doc(
            {"edits": "game/board"},
            {"provides": "def score(board: Board, rate: int) -> int", "in": "game/board"})})
        self.assertEqual(problems, [])

    def test_a_change_may_use_the_existing_code_it_does_not_change(self):
        _, problems = self.check(changes={"Rate": doc(
            {"edits": "game/board"},
            {"requires": "def bonus() -> int", "from": "game/rules"})})
        self.assertEqual(problems, [])


class TheDownstreamStepOfAChange(Existing):
    def step(self) -> dict:
        units, problems = self.design(changes={"Rate": doc(
            {"edits": "game/board"}, {"edits": "game/rules"},
            {"provides": "def score(board: Board, rate: int) -> int", "in": "game/board"})})
        self.assertEqual(problems, [])
        with mock.patch.object(swa, "basic_overview", return_value="放置ゲーム。"), \
             mock.patch.object(swa, "basic_section", return_value="名前は英語で書く。"):
            return swa.build_tasks(units, {"language": "python", "mode": "existing"})["steps"][0]

    def test_the_step_writes_every_file_it_edits(self):
        step = self.step()
        self.assertEqual(step["id"], "changes/Rate")
        self.assertEqual(step["unit"], "change")
        self.assertEqual(step["files_write"], ["src/game/board.py", "src/game/rules.py"])
        self.assertEqual(step["files_test"], ["tests/test_changes_Rate.py"])
        self.assertEqual(step["contracts"]["provides"],
                         ["def score(board: Board, rate: int) -> int -- defined in game.board"])
        self.assertEqual(step["expected_tests"], 1)

    def test_the_context_says_it_is_a_change_and_carries_the_conventions(self):
        context = self.step()["context"]
        self.assertIn("## This change: changes/Rate", context)
        self.assertIn("名前は英語で書く。", context)
        self.assertIn("得点に倍率を掛ける。", context)

    def test_the_test_brief_asks_for_tests_that_fail_against_the_code_as_it_is(self):
        step = dict(self.step(), contracts={"provides": [], "requires": [], "invariants": []})
        with mock.patch.object(swa, "dep_contracts", return_value="(none)"), \
             mock.patch.object(swa, "library_refs_section", return_value=""), \
             mock.patch.object(swa, "head_sources", return_value={}), \
             mock.patch.object(swa, "PROJECT", Path(tempfile.gettempdir()) / "swa-none"):
            brief = swa.brief_test_write(step, "context")
            impl = swa.brief_impl(step, "context", "", "")
        self.assertIn("must fail\nwhen run against the code as it is now", brief)
        self.assertNotIn("do not create the module under test", brief)
        self.assertIn("(none -- every name this step touches keeps its signature)", brief)
        self.assertIn("changing the existing code as this change describes", impl)


class TheStagesWithChanges(Existing):
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
            "TASKS": root / ".runner" / "tasks.json", "DOCS_BASIC": root / "docs" / "basic",
            "DOCS_MODULES": root / "docs" / "modules",
            "DOCS_CHANGES": root / "docs" / "changes", "AC": root / "ac",
            "commit_paths": lambda *a: None, "ledger": lambda event, **f: None,
            "basic_overview": lambda: "",
        }.items():
            p = mock.patch.object(swa, name, value)
            p.start()
            self.addCleanup(p.stop)
        (root / "plan").mkdir()
        swa.write_texts(swa.DOCS_CHANGES, {"Rate": doc({"edits": "game/board"})}, ".md")
        swa.write_texts(swa.AC, {"changes/Rate": ac()}, ".json")

    def test_a_change_is_approved_and_built_downstream(self):
        units, _ = swa.current_design()
        swa.write_stage(stage="midstream", language="python", mode="existing",
                        critiqued=swa.design_digest(units))
        self.assertEqual(swa.cmd_modules_approve(), 0)
        tasks = json.loads(swa.TASKS.read_text(encoding="utf-8"))
        self.assertEqual([(s["id"], s["unit"]) for s in tasks["steps"]],
                         [("changes/Rate", "change")])

    def test_reopen_knows_the_changes(self):
        swa.write_stage(stage="downstream", language="python", mode="existing")
        with mock.patch.object(swa, "clean_tree"):
            self.assertEqual(swa.cmd_reopen(["changes/Rate"]), 0)
        self.assertEqual(swa.read_stage()["open"], ["changes/Rate"])

    def test_a_sent_back_draft_may_change_only_the_open_changes(self):
        out = self.root / "out"
        before = {"Rate": doc({"edits": "game/board"}),
                  "Other": doc({"edits": "game/rules"})}
        with mock.patch.object(swa, "PLANNER_OUT", out):
            swa.write_texts(out / "changes", {
                "Rate": doc({"edits": "game/board"}, behaviour="変えた。"),
                "Other": doc({"edits": "game/rules"}, behaviour="変えた。")}, ".md")
            swa.write_texts(out / "ac", {"changes/Rate": ac(), "changes/Other": ac()}, ".json")
            problems = swa.check_modules_out(
                ["changes/Rate"], {}, {"changes/Rate": ac(), "changes/Other": ac()}, before)
        self.assertEqual(problems, ["差し戻し: changes/Other.md changed, but only "
                                    "changes/Rate may change"])


class RedAgainstTheCodeAsItIs(Existing):
    """署名の変わらない変更は、スタブを作らずに今のコードに対して Red を取る。"""

    STEP = {"id": "changes/Rate", "unit": "change", "goal": "g", "depends_on": [],
            "expected_tests": 1, "max_attempts": 1, "kind": "unit",
            "files_write": ["src/game/board.py"], "files_test": ["tests/test_changes_Rate.py"],
            "acceptance": CRITERIA,
            "contracts": {"provides": [], "requires": [], "invariants": []}}

    def setUp(self) -> None:
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / ".runner").mkdir()
        (root / ".runner" / "tasks.json").write_text('{"steps": [], "mode": "existing"}',
                                                     encoding="utf-8")
        self.failed: list[swa.Halt] = []
        self.greens: list[int] = []
        self.stubbed = 0
        self.runs: list[swa.TestRun] = []

        def stub(step, lines, originals):
            self.stubbed += 1
            return {}

        for name, value in {
            "STATE": root / ".runner", "TASKS": root / ".runner" / "tasks.json",
            "load_settings": lambda tasks: None,
            "load_plan": lambda sid: (self.STEP, "context"),
            "ledger": lambda event, **f: None, "touched_paths": lambda: set(),
            "set_writable": lambda **kw: None, "assert_touched": lambda *a: None,
            "assert_written": lambda *a: None, "check_baseline": lambda: None,
            "head_sources": lambda paths: {"src/game/board.py": "def score(): ..."},
            "generate_stub": stub, "stub_kept_the_rest": lambda step, originals: [],
            "restore_to_head": lambda paths: None, "freeze_tests": lambda: {},
            "frozen_tests_text": lambda step: "",
            "pytest_run": lambda tag, files: self.runs.pop(0),
            "call_solver": lambda phase, brief, backend=None: "",
            "complete_green": lambda sid, goal, n, design="": self.greens.append(n),
            "fail_module": lambda step, halt, n, run: self.failed.append(halt),
        }.items():
            p = mock.patch.object(swa, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_no_stub_is_made_and_a_red_assertion_goes_on_to_green(self):
        red = swa.TestRun(1, 1, 0, 0, ["AssertionError"], [], "")
        green = swa.TestRun(3, 0, 0, 0, [], ["t"], "")
        self.runs = [red, green]
        self.assertEqual(swa.run_step("changes/Rate"), 0)
        self.assertEqual(self.stubbed, 0)
        self.assertEqual(self.greens, [1])

    def test_a_test_the_code_already_passes_stops_the_change(self):
        self.runs = [swa.TestRun(1, 0, 0, 0, [], ["test_rate"], "")]
        self.assertEqual(swa.run_step("changes/Rate"), 2)
        self.assertTrue(self.failed[0].reason.startswith(
            "R4: some tests already pass against the code as it is"), self.failed[0].reason)

    def test_a_test_that_breaks_on_a_name_error_is_not_red(self):
        self.runs = [swa.TestRun(1, 1, 0, 0, ["NameError"], [], "")]
        self.assertEqual(swa.run_step("changes/Rate"), 2)
        self.assertTrue(self.failed[0].reason.startswith("R5"), self.failed[0].reason)

    def test_a_change_that_provides_a_name_is_stubbed(self):
        step = dict(self.STEP, contracts={
            "provides": ["def score(board: Board, rate: int) -> int -- defined in game.board"],
            "requires": [], "invariants": []})
        self.runs = [swa.TestRun(1, 1, 0, 0, ["AssertionError"], [], ""),
                     swa.TestRun(3, 0, 0, 0, [], ["t"], "")]
        with mock.patch.object(swa, "load_plan", lambda sid: (step, "context")):
            self.assertEqual(swa.run_step("changes/Rate"), 0)
        self.assertEqual(self.stubbed, 1)


class CommittingADesignWithoutChanges(unittest.TestCase):
    """変更が1つも無い詳細設計でも、空の docs/changes/ でコミットが落ちない。"""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for args in (["init", "-q"], ["config", "user.email", "runner@example.com"],
                     ["config", "user.name", "runner"]):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)
        # run の cwd の既定は定義した時の PROJECT なので、ここで作ったリポジトリを渡す。
        run = swa.run
        for name, value in {"PROJECT": self.root, "publish": lambda what: None,
                            "run": lambda cmd, **kw: run(cmd, **{"cwd": self.root, **kw})}.items():
            patcher = mock.patch.object(swa, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def log(self) -> str:
        return subprocess.run(["git", "log", "--name-only", "--format=%s"], cwd=self.root,
                              check=True, capture_output=True, text=True).stdout

    def test_an_empty_changes_directory_is_left_out(self):
        (self.root / "docs" / "modules").mkdir(parents=True)
        (self.root / "docs" / "modules" / "savedata.md").write_text("# savedata\n", encoding="utf-8")
        (self.root / "docs" / "changes").mkdir()
        swa.commit_paths([self.root / "docs" / "modules", self.root / "docs" / "changes"],
                         "docs: write the module design", "the module design")
        self.assertIn("docs/modules/savedata.md", self.log())

    def test_a_changes_directory_emptied_since_the_last_commit_records_the_removal(self):
        changes = self.root / "docs" / "changes"
        changes.mkdir(parents=True)
        (changes / "Rate.md").write_text("# Rate\n", encoding="utf-8")
        swa.commit_paths([changes], "docs: one", "one")
        (changes / "Rate.md").unlink()
        swa.commit_paths([changes], "docs: two", "two")
        self.assertFalse(subprocess.run(["git", "ls-files"], cwd=self.root, check=True,
                                        capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    unittest.main()
