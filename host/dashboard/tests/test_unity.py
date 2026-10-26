import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from host.dashboard.unity import UnityRefs, check_folder, host_state


class UnityProject(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.folder = root / "Puzzle"
        (self.folder / "ProjectSettings").mkdir(parents=True)
        (self.folder / "Packages").mkdir()
        self.version = self.folder / "ProjectSettings" / "ProjectVersion.txt"
        self.version.write_text("m_EditorVersion: 6000.3.10f1\n", encoding="utf-8")
        self.csproj = self.folder / "Assembly-CSharp.csproj"
        self.unity = UnityRefs(root / "state")

    def tearDown(self):
        self.temp.cleanup()

    def age(self, path, seconds):
        at = time.time() - seconds
        os.utime(path, (at, at))


class TheFolder(UnityProject):
    def test_only_an_absolute_unity_project_is_taken(self):
        self.assertEqual(check_folder(str(self.folder)), self.folder.resolve())
        for value in ("", "  ", None, "Puzzle", "-DryRun", str(self.folder / "ProjectSettings")):
            with self.assertRaises(ValueError):
                check_folder(value)

    def test_it_is_remembered_for_each_project(self):
        self.unity.remember("thm01", str(self.folder))
        self.assertEqual(self.unity.status("thm01")["folder"], str(self.folder.resolve()))
        self.assertIsNone(self.unity.status("other")["folder"])

    def test_a_bad_project_name_is_refused(self):
        for name in ("CURRENT", "../x", "-x", "", None):
            with self.assertRaises(ValueError):
                self.unity.remember(name, str(self.folder))


class TheCsproj(UnityProject):
    def test_a_missing_csproj_is_said(self):
        self.assertEqual(host_state(self.folder), {"csproj": False, "older_than": []})

    def test_a_csproj_older_than_the_packages_names_them(self):
        manifest = self.folder / "Packages" / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        self.csproj.write_text("<Project/>", encoding="utf-8")
        self.age(self.csproj, 60)
        self.age(self.version, 120)
        self.assertEqual(host_state(self.folder),
                         {"csproj": True, "older_than": ["Packages/manifest.json"]})

    def test_a_fresh_csproj_is_ready(self):
        self.csproj.write_text("<Project/>", encoding="utf-8")
        self.age(self.version, 60)
        self.assertEqual(host_state(self.folder), {"csproj": True, "older_than": []})


class TheScript(UnityProject):
    @patch("host.dashboard.job.subprocess.Popen")
    def test_it_runs_the_script_with_an_argument_array_and_no_shell(self, popen):
        popen.return_value.stdout = iter(["Unity 6000.3.10f1, C# 9.0\n"])
        popen.return_value.wait.return_value = 0
        self.unity.remember("thm01", str(self.folder))
        self.unity.start("thm01", True)
        self.unity.thread.join(5)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-3:], ["thm01", str(self.folder.resolve()), "-DryRun"])
        self.assertTrue(argv[argv.index("-File") + 1].endswith("swa-unity-refs.ps1"))
        self.assertIs(popen.call_args.kwargs["shell"], False)
        status = self.unity.status("thm01")
        self.assertEqual((status["running"], status["returncode"], status["dry_run"]),
                         (False, 0, True))
        self.assertEqual(status["output"], ["Unity 6000.3.10f1, C# 9.0"])

    @patch("host.dashboard.job.subprocess.Popen")
    def test_a_send_has_no_dry_run_flag(self, popen):
        popen.return_value.stdout = iter([])
        popen.return_value.wait.return_value = 0
        self.unity.remember("thm01", str(self.folder))
        self.unity.start("thm01", False)
        self.unity.thread.join(5)
        self.assertNotIn("-DryRun", popen.call_args.args[0])

    @patch("host.dashboard.job.subprocess.Popen")
    def test_without_a_remembered_folder_nothing_runs(self, popen):
        with self.assertRaises(ValueError):
            self.unity.start("thm01", True)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
