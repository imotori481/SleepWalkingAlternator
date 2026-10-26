"""`swa findings` の中身。クリティックの指摘の、人が読む写しを見せる。

保守ユーザーが sudo なしで流す。
写し（/srv/swa/human/in/CRITIQUE.json）は、modules critique が批評のたびに書く。
グループ humanw が読め、プランナーとクリティックは読めない。

指摘はプランナーに戻らない。書き直させるかは人が決め、コメントで伝える。

    python3 swa_findings.py show <写し>
"""

from __future__ import annotations

import json
import sys

MODE_JA = {"modules": "詳細設計の批評（modules）"}


def load(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("modes"), dict) else None


def show(path: str) -> int:
    value = load(path)
    if value is None:
        print("今の回にクリティックの指摘は無い")
        return 0
    print(f"批評（{value.get('at', '')}）: 直させるなら 'swa reject <コメント>'")
    for mode, findings in value["modes"].items():
        print()
        print(f"## {MODE_JA.get(mode, mode)}")
        if not findings:
            print("（指摘なし）")
        for n, finding in enumerate(findings):
            print(f"[{n}] {finding.get('title', '')}")
            if finding.get("machine_would_notice") is False:
                print("    どの関門も気づかない")
            for line in str(finding.get("evidence", "")).splitlines():
                print(f"    {line}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "show":
        print("使い方: swa_findings.py show <写し>", file=sys.stderr)
        return 2
    return show(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
