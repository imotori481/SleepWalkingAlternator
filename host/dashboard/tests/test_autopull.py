"""箱の bare のブランチの先が動いたら、写しを1回だけ引く。"""

import json
import tempfile
import unittest
from pathlib import Path

from host.dashboard.autopull import DEFAULT_INTERVAL, AutoPull, fingerprint, settings


def now(*heads, error=None):
    if error:
        return {"error": error}
    return {"projects": [{"name": name, "state": "new", "branch": "main", "head": head}
                         for name, head in heads]}


class FakeMirror:
    def __init__(self):
        self.running, self.returncode, self.starts = False, None, 0

    def status(self):
        return {"running": self.running, "returncode": self.returncode}

    def start(self):
        if self.running:
            raise ValueError("swa-pull is already running")
        self.running, self.returncode = True, None
        self.starts += 1

    def finish(self, returncode=0):
        self.running, self.returncode = False, returncode


class Watch(unittest.TestCase):
    def setUp(self):
        self.answer = now(("game", "a1"))
        self.mirror = FakeMirror()
        self.auto = AutoPull(lambda: self.answer, self.mirror, DEFAULT_INTERVAL)

    def test_the_first_look_pulls_once(self):
        self.assertTrue(self.auto.check())
        self.mirror.finish()
        self.assertFalse(self.auto.check())
        self.assertEqual(self.mirror.starts, 1)

    def test_a_new_commit_pulls_again(self):
        self.auto.check()
        self.mirror.finish()
        self.answer = now(("game", "b2"))
        self.assertTrue(self.auto.check())
        self.assertEqual(self.mirror.starts, 2)

    def test_a_commit_while_pulling_is_pulled_after_it(self):
        self.auto.check()
        self.answer = now(("game", "b2"))
        self.assertFalse(self.auto.check())
        self.mirror.finish()
        self.assertTrue(self.auto.check())

    def test_a_failed_pull_is_tried_again(self):
        self.auto.check()
        self.mirror.finish(returncode=1)
        self.assertTrue(self.auto.check())
        self.assertEqual(self.mirror.starts, 2)

    def test_an_unreachable_box_pulls_nothing(self):
        self.answer = now(error="could not reach the sandbox")
        self.assertFalse(self.auto.check())
        self.assertEqual(self.mirror.starts, 0)

    def test_a_pull_started_from_the_page_is_not_doubled(self):
        self.mirror.start()
        self.assertFalse(self.auto.check())
        self.assertEqual(self.mirror.starts, 1)

    def test_any_project_moving_counts(self):
        self.answer = now(("game", "a1"), ("old", "c3"))
        self.auto.check()
        self.mirror.finish()
        self.answer = now(("game", "a1"), ("old", "d4"))
        self.assertTrue(self.auto.check())

    def test_the_order_of_projects_does_not_matter(self):
        self.assertEqual(fingerprint(now(("a", "1"), ("b", "2"))),
                         fingerprint(now(("b", "2"), ("a", "1"))))


class Settings(unittest.TestCase):
    def config(self, value):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_it_is_on_by_default(self):
        self.assertEqual(settings(Path("does-not-exist.json")), (True, DEFAULT_INTERVAL))
        self.assertEqual(settings(self.config({"live": {}})), (True, DEFAULT_INTERVAL))

    def test_it_can_be_turned_off_and_slowed(self):
        self.assertEqual(settings(self.config({"mirror": {"auto_pull": False}})),
                         (False, DEFAULT_INTERVAL))
        self.assertEqual(settings(self.config({"mirror": {"interval_seconds": 120}})),
                         (True, 120))

    def test_a_bad_interval_is_refused(self):
        for bad in (0, 4, "30", True, 1.5):
            with self.assertRaises(ValueError):
                settings(self.config({"mirror": {"interval_seconds": bad}}))


if __name__ == "__main__":
    unittest.main()
