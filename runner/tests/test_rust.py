"""Rust を計画の言語にする。

箱ではライブラリのクレートを cargo-nextest の結合テストで確かめる。失敗の形は nextest の
junit のレポートと rustc のエラーの出力に合わせてある。箱の smoke-rust が同じ形を確かめる。
クレートの根の `pub mod` の行はランナーが書く。

    python3 -m unittest discover -s runner/tests
"""

import json
import sys
import tempfile
import tomllib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import swa  # noqa: E402

# nextest の junit の1件。実測の形から、バックトレースを落としたもの。
JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="nextest-run" tests="4" skipped="0" failures="3" errors="0">
  <testsuite name="game::game_board" tests="4" skipped="0" errors="0" failures="3">
    <testcase name="passes" classname="game::game_board"/>
    <testcase name="assert_fail" classname="game::game_board">
      <failure message="thread &apos;assert_fail&apos; (9488) panicked at tests/game_board.rs:3:28" type="test failure with exit code 101">thread &apos;assert_fail&apos; (9488) panicked at tests/game_board.rs:3:28:
assertion `left == right` failed
  left: 6
 right: 9</failure>
    </testcase>
    <testcase name="stub_hit" classname="game::game_board">
      <failure message="thread &apos;stub_hit&apos; (9490) panicked at src/game/board.rs:3:34" type="test failure with exit code 101">thread &apos;stub_hit&apos; (9490) panicked at src/game/board.rs:3:34:
not implemented: __stub__</failure>
    </testcase>
    <testcase name="index_panic" classname="game::game_board">
      <failure message="thread &apos;index_panic&apos; (9485) panicked at tests/game_board.rs:6:63" type="test failure with exit code 101">thread &apos;index_panic&apos; (9485) panicked at tests/game_board.rs:6:63:
index out of bounds: the len is 0 but the index is 0</failure>
    </testcase>
  </testsuite>
</testsuites>
"""

# rustc がテストのファイルのコンパイルで落ちたときの出力。実測の形。
BUILD_FAILED = """   Compiling game v0.1.0 (/srv/swa/project)
error[E0308]: mismatched types
 --> tests/game_bad.rs:2:53
  |
2 | #[test] fn broken() { let b: Board = Board { width: "x" }; }
  |                                                     ^^^ expected `u32`, found `&str`

error[E0599]: no method named `nothere` found for struct `Board` in the current scope
 --> src/game/board.rs:9:7
  |

error: could not compile `game` (test "game_bad") due to 2 previous errors
"""


class Rust(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.dict(swa.LANGUAGE, swa.LANGUAGES["rust"], clear=True),
                  mock.patch.dict(swa.LAYOUT, swa.LAYOUT_DEFAULT),
                  mock.patch.dict(swa.RUN, {"mode": "new"})):
            p.start()
            self.addCleanup(p.stop)

    def patch(self, **values):
        for name, value in values.items():
            p = mock.patch.object(swa, name, value)
            p.start()
            self.addCleanup(p.stop)

    def project(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.patch(PROJECT=root, SRC=root / "src", TESTS=root / "tests")
        (root / "src").mkdir()
        return root

    def write(self, root: Path, rel: str, text: str) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def failure(self, text):
        element = ET.Element("failure", {"message": text.splitlines()[0]})
        element.text = text
        return element


class HowAFailureIsRead(Rust):
    def test_the_report_is_read_per_test(self):
        self.project()
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(JUNIT)
        self.addCleanup(Path(handle.name).unlink)
        run = swa.parse_junit(Path(handle.name))
        self.assertEqual(run.tests, 4)
        self.assertEqual(sorted(run.failure_kinds),
                         ["AssertionFailure", "IndexOutOfBounds", "StubNotImplemented"])
        self.assertEqual(run.passed_names, ["passes"])

    def test_the_stub_and_an_assertion_are_red_and_a_broken_test_is_not(self):
        self.project()
        red = swa.LANGUAGE["red_kinds"]
        stub = swa.failure_kind(self.failure(
            "thread 'a' panicked at src/game/board.rs:3:34:\nnot implemented: __stub__"))
        assertion = swa.failure_kind(self.failure(
            "thread 'b' panicked at tests/board.rs:3:28:\nassertion `left == right` failed"))
        custom = swa.failure_kind(self.failure(
            "thread 'c' panicked at tests/board.rs:4:29:\narea was off"))
        unwrap = swa.failure_kind(self.failure(
            "thread 'd' panicked at tests/board.rs:7:57:\n"
            "called `Option::unwrap()` on a `None` value"))
        elsewhere = swa.failure_kind(self.failure(
            "thread 'e' panicked at src/game/board.rs:9:9:\nboard is full"))
        self.assertEqual((stub, assertion, custom, unwrap, elsewhere),
                         ("StubNotImplemented", "AssertionFailure", "AssertionFailure",
                          "UnwrapNone", "Panic"))
        self.assertTrue(red.match(stub) and red.match(assertion) and red.match(custom))
        self.assertFalse(red.match(unwrap) or red.match(elsewhere))
        self.assertTrue(swa.LANGUAGE["fixable_crashes"].match(unwrap))

    def test_another_not_implemented_is_not_the_stub(self):
        self.project()
        kind = swa.failure_kind(self.failure(
            "thread 'a' panicked at src/a.rs:1:1:\nnot implemented: later"))
        self.assertEqual(kind, "NotImplemented")
        self.assertFalse(swa.LANGUAGE["red_kinds"].match(kind))

    def test_a_compile_error_names_the_file_that_did_not_compile(self):
        root = self.project()
        run = swa.rust_build_failure(BUILD_FAILED)
        self.assertEqual(run.failure_kinds, ["<did not compile: tests/game_bad.rs>",
                                             "<build failed: src/game/board.rs>"])
        self.assertEqual(run.failed_files, ["tests/game_bad.rs", "src/game/board.rs"])
        self.assertIn("tests/game_bad.rs:2: error: mismatched types", run.output)
        self.assertIsNone(swa.rust_build_failure("   Compiling game v0.1.0\n"))
        self.assertTrue(root.is_dir())

    def test_a_test_binary_is_owned_by_its_file(self):
        self.assertEqual(swa.test_owner("game::game_board"), "game_board")
        self.assertEqual(swa.test_owner("tests/game_board.rs"), "game_board")
        step = {"files_test": ["tests/game_board.rs", "tests/game_board_integration.rs"]}
        self.assertTrue({"game_board", "game_board_integration"} <= swa.own_test_keys(step))


class TheTests(Rust):
    def test_test_files_sit_directly_in_the_tests_folder(self):
        self.assertEqual(swa.module_test_files("game/board", True, True),
                         ["tests/game_board.rs", "tests/game_board_integration.rs"])

    def test_the_command_selects_the_step_s_binaries_and_stays_offline(self):
        self.project()
        argv, env = swa.test_argv(["tests/game_board.rs"], Path("/tmp/x.xml"))
        self.assertEqual(argv[:3], [str(swa.CARGO), "nextest", "run"])
        for flag in ("--offline", "--locked"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--test") + 1], "game_board")
        self.assertEqual(env["CARGO_NET_OFFLINE"], "true")
        self.assertEqual(env["RUST_BACKTRACE"], "0")

    def test_the_vendored_crates_replace_crates_io_once_they_are_there(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.patch(RUST_VENDOR=Path(temp.name), SWA=Path(temp.name))
        self.assertEqual(swa.rust_vendor_args(), [])
        swa.rust_vendor().mkdir(parents=True)
        args = swa.rust_vendor_args()
        self.assertIn('source.crates-io.replace-with="swa-vendor"', args)

    def test_test_names_are_read_from_test_functions(self):
        text = "#[test]\nfn score_counts_rows() {}\n#[test]\n#[should_panic]\nfn rejects() {}\n" \
               "fn helper() {}\n"
        self.assertEqual(swa.test_names(text), ["score_counts_rows", "rejects"])


class TheContract(Rust):
    def test_types_methods_and_functions_are_named(self):
        self.assertEqual(swa.declared_name("pub struct Board { pub width: u32 }"), "Board")
        self.assertEqual(swa.declared_name("pub fn Board::score(&self) -> u32"), "Board::score")
        self.assertEqual(swa.declared_name("pub fn count_lines(board: &Board) -> usize"),
                         "count_lines")
        self.assertEqual(swa.declared_name("pub enum Stone { Black, White }"), "Stone")
        self.assertEqual(swa.declared_name("pub const MAX: u32"), "MAX")

    def test_a_bare_container_is_shapeless(self):
        self.assertEqual(swa.shapeless_types("pub fn cells(&self) -> Vec"), ["Vec"])
        self.assertEqual(swa.shapeless_types("pub fn cells(&self) -> Vec<Cell>"), [])

    def test_a_module_path_is_snake_case_and_not_a_crate_root(self):
        for mid in ("lib", "game/mod", "bin/tool", "Game/board", "game-board"):
            with self.subTest(mid=mid), mock.patch.object(swa, "head_files", return_value=set()):
                _, problems = swa.design_problems({mid: "x"}, {})
                self.assertTrue(any("snake_case" in p for p in problems), problems)


class TheCrates(Rust):
    def docs(self, block: str) -> dict[str, str]:
        return {"design": f"## 概要\nライブラリ。\n\n## 使うクレート\n```toml crates\n{block}```\n"}

    def test_the_crates_block_is_read(self):
        crates, problems = swa.rust_design_crates(self.docs(
            'serde = { version = "1", features = ["derive"] }\nrand = "0.8"\n'))
        self.assertEqual(problems, [])
        self.assertEqual(crates["rand"], "0.8")
        self.assertEqual(crates["serde"]["features"], ["derive"])

    def test_no_section_means_no_crates(self):
        self.assertEqual(swa.rust_design_crates({"design": "## 概要\nライブラリ。\n"}), ({}, []))

    def test_a_source_outside_crates_io_or_a_missing_version_is_refused(self):
        for block in ('mine = { path = "../mine" }\n', 'theirs = { git = "https://x/y" }\n',
                      'serde = { features = ["derive"] }\n', 'bad name = "1"\n', "not toml\n"):
            with self.subTest(block=block):
                crates, problems = swa.rust_design_crates(self.docs(block))
                self.assertEqual(crates, {})
                self.assertTrue(problems)

    def test_the_basic_design_is_checked_for_the_crates(self):
        self.assertTrue(swa.basic_problems(self.docs('x = { path = "." }\n')))
        self.assertEqual(swa.basic_problems(self.docs('rand = "0.8"\n')), [])

    def test_a_new_crate_s_manifest_names_the_crates(self):
        with mock.patch.object(swa, "rust_crate_name", return_value="game"):
            text = swa.rust_manifest({"rand": "0.8", "serde": {"version": "1",
                                                                "features": ["derive"]}})
        value = tomllib.loads(text)
        self.assertEqual(value["package"]["name"], "game")
        self.assertEqual(value["package"]["edition"], swa.RUST_EDITION)
        self.assertEqual(value["dependencies"]["serde"]["features"], ["derive"])

    def test_an_existing_manifest_gets_only_the_missing_crates(self):
        text = ('[package]\nname = "app"\nversion = "0.1.0"\n\n[dependencies]\nrand = "0.8"\n'
                '\n[dev-dependencies]\nproptest = "1"\n')
        new = swa.rust_add_dependencies(text, {"rand": "0.9", "proptest": "1", "log": "0.4"})
        value = tomllib.loads(new)
        self.assertEqual(value["dependencies"], {"rand": "0.8", "log": "0.4"})
        self.assertEqual(value["dev-dependencies"], {"proptest": "1"})
        self.assertEqual(swa.rust_add_dependencies(text, {"rand": "0.9"}), text)
        bare = swa.rust_add_dependencies('[package]\nname = "app"\n', {"log": "0.4"})
        self.assertEqual(tomllib.loads(bare)["dependencies"], {"log": "0.4"})


class TheCrateRoot(Rust):
    def test_every_file_gets_a_pub_mod_line_in_its_parent(self):
        root = self.project()
        self.write(root, "src/game/board.rs", "pub struct Board;\n")
        self.write(root, "src/rules.rs", "pub fn ok() {}\n")
        changed = swa.rust_write_mods()
        self.assertEqual(sorted(changed), ["src/game/mod.rs", "src/lib.rs"])
        lib = (root / "src/lib.rs").read_text(encoding="utf-8")
        self.assertIn("pub mod game;\npub mod rules;\n", lib)
        self.assertIn("pub mod board;", (root / "src/game/mod.rs").read_text(encoding="utf-8"))
        self.assertEqual(swa.rust_write_mods(), [])

    def test_a_line_already_written_outside_the_block_is_kept_and_not_repeated(self):
        root = self.project()
        self.write(root, "src/lib.rs", "#![no_std]\n//! The crate.\nmod rules;\npub fn f() {}\n")
        self.write(root, "src/rules.rs", "")
        self.write(root, "src/board.rs", "")
        swa.rust_write_mods()
        lib = (root / "src/lib.rs").read_text(encoding="utf-8")
        self.assertTrue(lib.startswith("#![no_std]\n//! The crate.\n" + swa.RUST_MODS_BEGIN))
        self.assertIn("pub mod board;", lib)
        self.assertNotIn("pub mod rules;", lib)
        self.assertIn("mod rules;\npub fn f() {}", lib)

    def test_a_sibling_file_declares_its_folder_s_modules(self):
        root = self.project()
        self.write(root, "src/game.rs", "pub fn g() {}\n")
        self.write(root, "src/game/board.rs", "")
        swa.rust_write_mods()
        self.assertIn("pub mod board;", (root / "src/game.rs").read_text(encoding="utf-8"))
        self.assertFalse((root / "src/game/mod.rs").exists())

    def test_a_removed_module_s_line_goes_and_an_empty_mod_rs_with_it(self):
        root = self.project()
        board = self.write(root, "src/game/board.rs", "")
        self.write(root, "src/rules.rs", "")
        swa.rust_write_mods()
        board.unlink()
        swa.rust_write_mods()
        self.assertFalse((root / "src/game/mod.rs").exists())
        lib = (root / "src/lib.rs").read_text(encoding="utf-8")
        self.assertNotIn("game", lib)
        self.assertIn("pub mod rules;", lib)

    def test_binaries_are_not_modules(self):
        root = self.project()
        self.write(root, "src/main.rs", "fn main() {}\n")
        self.write(root, "src/bin/tool.rs", "fn main() {}\n")
        self.assertEqual(swa.rust_write_mods(), [])

    def test_only_the_block_changing_is_not_a_stray_write(self):
        root = self.project()
        lib = self.write(root, "src/lib.rs", "pub fn f() {}\n")
        self.write(root, "src/board.rs", "")
        swa.rust_write_mods()
        head = SimpleNamespace(returncode=0, stdout="pub fn f() {}\n")
        with mock.patch.object(swa, "run", return_value=head):
            self.assertTrue(swa.rust_only_mods_changed("src/lib.rs"))
            lib.write_text(lib.read_text(encoding="utf-8") + "pub fn g() {}\n", encoding="utf-8")
            self.assertFalse(swa.rust_only_mods_changed("src/lib.rs"))


class TheExistingCode(Rust):
    def test_public_declarations_are_read_without_their_bodies(self):
        text = """//! A board.
use std::fmt;

/// The board.
#[derive(Debug, Clone)]
pub struct Board {
    pub width: u32,
    cells: Vec<u8>,
}

pub enum Stone { Black, White }

struct Hidden;

impl Board {
    pub fn new(width: u32) -> Board { Board { width, cells: vec![] } }
    fn private(&self) -> u32 { 0 }
    pub fn score(&self) -> u32 { if self.width > 0 { 1 } else { 0 } }
}

impl fmt::Display for Board {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result { write!(f, "b") }
}

pub fn count_lines(board: &Board) -> usize { board.width as usize }
pub const MAX: u32 = 9;
"""
        lines = swa.rust_declarations(text, "src/game/board.rs")
        where = " -- defined in crate::game::board"
        self.assertEqual(lines, [
            f"pub struct Board {{ pub width: u32 }}{where}",
            f"pub enum Stone {{ Black, White }}{where}",
            f"pub fn Board::new(width: u32) -> Board{where}",
            f"pub fn Board::score(&self) -> u32{where}",
            f"pub fn count_lines(board: &Board) -> usize{where}",
            f"pub const MAX: u32{where}",
        ])

    def test_the_crate_root_is_named_as_such(self):
        lines = swa.rust_declarations("pub fn f() -> u32 { 1 }\n", "src/lib.rs")
        self.assertEqual(lines, ["pub fn f() -> u32 -- defined in the crate root"])


class TheLayout(Rust):
    def test_the_tests_fence_has_to_sit_beside_the_code(self):
        self.project()
        self.assertIsNone(swa.rust_problem())
        with mock.patch.dict(swa.LAYOUT, {"src": "src", "tests": "test"}):
            self.assertIn("tests fence has to be tests", swa.rust_problem())
        with mock.patch.dict(swa.LAYOUT, {"src": "crates/app/src", "tests": "crates/app/tests"}):
            self.assertIsNone(swa.rust_problem())

    def test_an_existing_crate_needs_a_package_manifest(self):
        root = self.project()
        with mock.patch.dict(swa.RUN, {"mode": "existing"}):
            self.assertIn("no Cargo.toml", swa.rust_problem())
            self.write(root, "Cargo.toml", '[workspace]\nmembers = ["a"]\n')
            self.assertIn("workspace", swa.rust_problem())
            self.write(root, "Cargo.toml", '[package]\nname = "app"\nversion = "0.1.0"\n')
            self.assertIsNone(swa.rust_problem())
            self.assertEqual(swa.rust_import_name(), "app")

    def test_a_new_crate_is_named_after_the_project(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "projects").mkdir()
        (root / "projects" / "CURRENT").write_text("my-game\n", encoding="utf-8")
        self.patch(SWA=root)
        self.assertEqual(swa.rust_crate_name(), "my_game")
        (root / "projects" / "CURRENT").write_text("2048\n", encoding="utf-8")
        self.assertEqual(swa.rust_crate_name(), "swa_2048")

    def test_the_toolchain_file_names_the_box_s_channel(self):
        root = self.project()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        toolchains = Path(temp.name) / "toolchains.json"
        toolchains.write_text(json.dumps({"stable": "1.97.0", "nightly": "nightly-2026-11-01"}),
                              encoding="utf-8")
        self.patch(RUST_TOOLCHAINS=toolchains, DOCS_BASIC=root / "docs" / "basic",
                   rust_crate_name=lambda: "game")
        written = swa.rust_write_manifest()
        self.assertEqual([p.name for p in written], ["Cargo.toml", "rust-toolchain.toml"])
        self.assertIn('channel = "1.97.0"', (root / "rust-toolchain.toml").read_text())


class TheStub(Rust):
    def test_the_stub_brief_asks_for_the_marked_panic(self):
        step = {"contracts": {"provides": ["pub fn Board::score(&self) -> u32"]},
                "files_write": ["src/game/board.rs"]}
        with mock.patch.object(swa, "render_provides", return_value="pub fn Board::score"):
            text = swa.brief_stub(step)
        self.assertIn('unimplemented!("__stub__")', text)
        self.assertIn("impl Board", text)
        self.assertIn("Never write a `mod` line", text)


if __name__ == "__main__":
    unittest.main()
