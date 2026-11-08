"""Rust のクレートを取りに行く。swa-fetch-crates が root で流す。

走行は runner として動き、ネットワークを持たせない。基本設計の承認の後、ランナーの
`crates fetch` が Cargo.toml を書き、`sudo -n /usr/local/sbin/swa-fetch-crates` で
これを呼ぶ。引数は取らない。どのプロジェクトのクレートを取るかは、箱のファイルから決める。

取りに行くのは cargo vendor で、ビルドスクリプトも手続きマクロも走らせない。それでも
リポジトリの中身は root に渡さない。クレートのディレクトリを一時の場所に写し、`.cargo`
（rustc を差し替えられる設定）、シンボリックリンク、.git、成果物を落としてから流す。
CARGO_HOME は空の一時の場所で、ツールチェーンは箱の stable に固定する
（リポジトリの rust-toolchain.toml は、箱に無い版を取りに行こうとする）。

置いたものは root の持ち物にし、runner は読むだけにする。Cargo.lock だけは
リポジトリのファイルなので、runner の持ち物で書き戻す。

    python3 swa_crates.py fetch <作業ツリー> <vendor の置き場> <プロジェクト名>
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))

import swa  # noqa: E402

PROJECT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
# 写さないもの。成果物、git、ランナーの持ち物、cargo の設定。
SKIPPED = {".git", "target", ".cargo", "plan", "ac", "docs", ".runner", ".venv",
           "node_modules"}
TIMEOUT = 1500


class Refused(Exception):
    pass


def copy_crate(source: Path, dest: Path) -> None:
    """クレートのディレクトリを写す。シンボリックリンクと SKIPPED は落とす。"""
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {n for n in names
                if n in SKIPPED or os.path.islink(os.path.join(directory, n))}
    shutil.copytree(source, dest, ignore=ignore)


def crate_dir(project: Path, layout: dict[str, str]) -> Path:
    parent = Path(layout["src"]).parent
    return project if str(parent) in ("", ".") else project / parent


def stable(toolchains: Path) -> str:
    try:
        value = json.loads(toolchains.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused(f"cannot read {toolchains}: {error}")
    channel = value.get("stable") if isinstance(value, dict) else None
    if not isinstance(channel, str) or not channel:
        raise Refused(f"{toolchains} names no stable toolchain")
    return channel


def install(tree: Path, final: Path) -> None:
    """vendor の木を root の持ち物にして、置き場に入れ替える。"""
    for path in [tree, *tree.rglob("*")]:
        if path.is_symlink():
            path.unlink()
            continue
        os.chown(path, 0, 0)
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(final.parent, 0o755)
    staged = final.with_name(final.name + ".new")
    shutil.rmtree(staged, ignore_errors=True)
    shutil.move(str(tree), staged)
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staged, final)


def write_lock(lock: Path, text: str, owner: Path) -> None:
    """Cargo.lock を、クレートのディレクトリの持ち主のファイルとして書き戻す。"""
    status = owner.stat()
    temporary = lock.with_name(".Cargo.lock.swa")
    temporary.write_text(text, encoding="utf-8")
    os.chown(temporary, status.st_uid, status.st_gid)
    os.chmod(temporary, 0o644)
    os.replace(temporary, lock)


def fetch(project: Path, vendor_root: Path, name: str, *, cargo: Path = swa.CARGO,
          rustup_home: Path = swa.RUSTUP_HOME, toolchains: Path = swa.RUST_TOOLCHAINS,
          layout: dict[str, str] | None = None) -> str:
    if not PROJECT_NAME.fullmatch(name):
        raise Refused(f"not a project name: {name!r}")
    layout = layout or swa.read_layout()
    crate = crate_dir(project, layout)
    if not (crate / "Cargo.toml").is_file():
        raise Refused(f"there is no {crate / 'Cargo.toml'}; the runner writes it first")
    channel = stable(toolchains)
    with tempfile.TemporaryDirectory(prefix="swa-crates-") as temp:
        work = Path(temp)
        copy_crate(crate, work / "crate")
        # Cargo.toml が名指すライブラリのファイルが無いと、cargo は読み込みで止まる。
        # 中身は要らない。写したのはリポジトリのものなので、無いときだけ空で置く。
        (work / "crate" / "src").mkdir(exist_ok=True)
        lib = work / "crate" / "src" / "lib.rs"
        if not lib.exists():
            lib.write_text("", encoding="utf-8")
        env = {"PATH": f"{cargo.parent}:/usr/bin:/bin", "RUSTUP_HOME": str(rustup_home),
               "CARGO_HOME": str(work / "cargo-home"), "RUSTUP_TOOLCHAIN": channel,
               "CARGO_TERM_COLOR": "never", "LC_ALL": "C", "LANG": "C",
               "HOME": str(work)}
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY",
                    "no_proxy", "SSL_CERT_FILE", "CARGO_HTTP_CAINFO"):
            if key in os.environ:
                env[key] = os.environ[key]
        proc = subprocess.run(
            [str(cargo), "vendor", "--versioned-dirs", "--manifest-path",
             str(work / "crate" / "Cargo.toml"), str(work / "vendor")],
            cwd=work, env=env, capture_output=True, text=True, timeout=TIMEOUT)
        if proc.returncode != 0:
            raise Refused("cargo vendor failed:\n" + (proc.stderr or proc.stdout)[-4000:])
        (work / "vendor").mkdir(exist_ok=True)
        locked = (work / "crate" / "Cargo.lock").read_text(encoding="utf-8")
        install(work / "vendor", vendor_root / name)
        write_lock(crate / "Cargo.lock", locked, crate)
    count = sum(1 for _ in (vendor_root / name).iterdir())
    return f"vendored {count} crate(s) into {vendor_root / name}"


def main(argv: list[str]) -> int:
    if len(argv) != 5 or argv[1] != "fetch":
        print("使い方: swa_crates.py fetch <作業ツリー> <vendor の置き場> <プロジェクト名>",
              file=sys.stderr)
        return 2
    try:
        print(fetch(Path(argv[2]), Path(argv[3]), argv[4]))
        return 0
    except Refused as error:
        print(f"swa-fetch-crates: {error}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"swa-fetch-crates: cargo vendor did not finish within {TIMEOUT}s",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
