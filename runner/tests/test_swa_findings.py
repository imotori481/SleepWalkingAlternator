"""`swa findings` が、指摘の写しを番号付きで見せること。

`swa now` が、その写しをダッシュボードに渡すこと。

    python3 -m unittest discover -s runner/tests
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "provision"))

import swa_findings  # noqa: E402
import swa_now  # noqa: E402

SHOWN = {"at": "2026-09-29T12:00:00+0900", "modes": {
    "coverage": [{"title": "条件が要件に逆らう", "evidence": "S2", "machine_would_notice": False}],
    "trace": [],
}}


class ShowTheFindings(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "human" / "in" / "CRITIQUE.json"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(SHOWN, ensure_ascii=False), encoding="utf-8")

    def test_show_prints_the_findings_with_their_index(self):
        out = io.StringIO()
        with redirect_stdout(out):
            swa_findings.show(str(self.path))
        text = out.getvalue()
        self.assertIn("swa reject", text)
        self.assertIn("[0] 条件が要件に逆らう", text)
        self.assertIn("どの関門も気づかない", text)
        self.assertIn("（指摘なし）", text)

    def test_swa_now_hands_the_findings_to_the_dashboard(self):
        logs = self.root / "logs"
        logs.mkdir()
        self.assertEqual(swa_now.findings(str(logs)), SHOWN)
        self.path.unlink()
        self.assertIsNone(swa_now.findings(str(logs)))


if __name__ == "__main__":
    unittest.main()
