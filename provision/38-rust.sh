#!/usr/bin/env bash
# Rust のツールチェーン。Rust の計画をこの箱で走らせるためにある。
#
#   sudo bash 38-rust.sh                    # 既定の stable と nightly を入れる
#   sudo bash 38-rust.sh toolchain <版>     # 版を足す（1.85.0、nightly-2026-06-01 など）
#
# rustup を apt から入れ、ツールチェーンを /opt/swa/rust に置く。root のもので、
# runner と solver は読むだけ。stable と、日付で固定した nightly の両方を必ず入れる。
# nightly はカーネルに要る機能（build-std、割り込みの ABI）のためにあり、rust-src と
# llvm-tools を付ける。どちらを使うかは、リポジトリの rust-toolchain.toml が決める
# （新規のモードではランナーが書く）。
#
# 入っている版は toolchains.json に書く。ランナーとダッシュボードが読む。
#
# テストは cargo-nextest で走らせる。junit を出すのはこれだけだ。ここで一度だけ
# crates.io から組み、凍結する。
#
# 走行中はネットワークに出ない。クレートは、基本設計の承認の後に root の
# swa-fetch-crates が取りに行く（provision/swa_crates.py）。runner に許すのはその
# 1つだけで、引数は取らない。
set -euo pipefail
cd "$(dirname "$0")"

[ "$(id -u)" -eq 0 ] || { echo "sudo で流す" >&2; exit 1; }

RUST_HOME=/opt/swa/rust
export RUSTUP_HOME="$RUST_HOME/rustup"
export CARGO_HOME="$RUST_HOME/cargo"
BUILD=/srv/swa/rust
VENDOR=/srv/swa/rust-vendor
# 版を固定する。範囲で書くと、箱を作り直したときに同じ設計の結果が変わる。上げるときは
# ここを書き換えて流し直すか、ダッシュボードの「Rust」から版を足す。
RUST_STABLE="1.97.0"
RUST_NIGHTLY="nightly-2026-11-01"
NEXTEST_VERSION="0.9.151"
# nightly に入れるターゲット。QEMU の上のカーネルのため。
NIGHTLY_TARGETS=(x86_64-unknown-none)
PROXIES=(cargo rustc rustdoc rustfmt cargo-clippy clippy-driver rust-gdb rust-lldb)
# 版の形。行にもオプションにもならないものだけを通す。
VERSION_RE='^([0-9]+\.[0-9]+(\.[0-9]+)?|stable|beta|nightly(-[0-9]{4}-[0-9]{2}-[0-9]{2})?)$'

# ---- rustup -----------------------------------------------------------------
if ! command -v rustup >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rustup
fi
RUSTUP="$(command -v rustup)"
install -d -o root -g root -m 755 /opt/swa "$RUST_HOME" "$RUSTUP_HOME" "$CARGO_HOME" \
  "$CARGO_HOME/bin"
# rustup は argv[0] で cargo や rustc の代わりになる。リポジトリの rust-toolchain.toml が
# 版を選び、箱に無い版なら取りに行かずに止まる（走行中はネットワークが無い）。
for proxy in "${PROXIES[@]}"; do
  ln -sfn "$RUSTUP" "$CARGO_HOME/bin/$proxy"
done

install_toolchain() {
  local version="$1"
  [[ "$version" =~ $VERSION_RE ]] || { echo "38-rust: 版の形ではない: $version" >&2; exit 1; }
  local -a extra=()
  case "$version" in
    nightly*) extra=(--component rust-src --component llvm-tools)
              for target in "${NIGHTLY_TARGETS[@]}"; do extra+=(--target "$target"); done ;;
  esac
  "$RUSTUP" toolchain install "$version" --profile minimal --no-self-update "${extra[@]}"
}

write_toolchains() {
  python3 - "$RUST_HOME/toolchains.json" "$RUST_STABLE" "$RUST_NIGHTLY" \
    "$("$RUSTUP" toolchain list | sed 's/ .*//' | sed 's/-x86_64-unknown-linux-gnu$//')" <<'PY'
import json, sys
path, stable, nightly, listed = sys.argv[1:5]
toolchains = sorted(t for t in listed.split() if t)
json.dump({"stable": stable, "nightly": nightly, "toolchains": toolchains},
          open(path, "w", encoding="utf-8"), indent=2)
PY
  chmod 644 "$RUST_HOME/toolchains.json"
}

freeze() {
  chown -R root:root "$RUST_HOME"
  chmod -R a+rX,go-w "$RUST_HOME"
}

if [ "${1:-}" = toolchain ]; then
  [ $# -eq 2 ] || { echo "使い方: 38-rust.sh toolchain <版>" >&2; exit 2; }
  install_toolchain "$2"
  write_toolchains
  freeze
  echo "38-rust: $2 を入れた"
  exit 0
fi

install_toolchain "$RUST_STABLE"
install_toolchain "$RUST_NIGHTLY"
"$RUSTUP" default "$RUST_STABLE"

# ---- cargo-nextest -----------------------------------------------------------
if ! "$CARGO_HOME/bin/cargo" nextest --version 2>/dev/null | grep -q "^cargo-nextest $NEXTEST_VERSION"; then
  "$CARGO_HOME/bin/cargo" "+$RUST_STABLE" install cargo-nextest --locked \
    --version "$NEXTEST_VERSION" --root "$CARGO_HOME"
fi
rm -rf "$CARGO_HOME/registry" "$CARGO_HOME/git"
write_toolchains
freeze

# ---- 置き場 --------------------------------------------------------------------
# 成果物と nextest の設定は runner だけが入れる。中身はコンパイルしたコードとテストで、
# planner と critic に見えてはならない。クレートのソースは root のもので、runner は読むだけ。
install -d -o runner -g runner -m 700 "$BUILD"
install -d -o root -g root -m 755 "$VENDOR"

# ---- クレートを取りに行く入口 ----------------------------------------------------
# runner に許すのはこれ1つで、引数を取らない。sudoers の "" は引数無しだけを許す。
install -d -o root -g root -m 755 /usr/local/sbin
install -o root -g root -m 755 sbin/swa-fetch-crates /usr/local/sbin/swa-fetch-crates
SUDOERS=/etc/sudoers.d/swa-crates
tmp="$(mktemp)"
echo 'runner ALL=(root) NOPASSWD: /usr/local/sbin/swa-fetch-crates ""' > "$tmp"
visudo -cqf "$tmp" || { rm -f "$tmp"; echo "38-rust: sudoers rule does not parse" >&2; exit 1; }
install -o root -g root -m 440 "$tmp" "$SUDOERS"
rm -f "$tmp"
install -o root -g root -m 755 bin/smoke-rust /srv/swa/bin/smoke-rust

# ---- 検査 ------------------------------------------------------------------------
fail=0
if ! sudo -u runner -H /srv/swa/bin/smoke-rust; then
  echo "FAIL: Rust のテストをビルドして走らせられない"; fail=1
fi
if sudo -u runner test -w "$RUST_HOME"; then
  echo "FAIL: runner should NOT be able to: test -w $RUST_HOME"; fail=1
fi
if sudo -u runner test -w "$VENDOR"; then
  echo "FAIL: runner should NOT be able to: test -w $VENDOR"; fail=1
fi
for who in solver planner critic; do
  id -u "$who" >/dev/null 2>&1 || continue
  if sudo -u "$who" ls "$BUILD" >/dev/null 2>&1; then
    echo "FAIL: $who should NOT be able to: ls $BUILD"; fail=1
  fi
done
# runner に許すのは引数無しの swa-fetch-crates だけ。swa そのものは許さない。
if ! sudo -l -U runner 2>/dev/null | grep -q "/usr/local/sbin/swa-fetch-crates"; then
  echo "FAIL: runner should be able to: sudo -n /usr/local/sbin/swa-fetch-crates"; fail=1
fi
if sudo -l -U runner 2>/dev/null | grep -q "/usr/local/bin/swa"; then
  echo "FAIL: runner should NOT be able to: sudo /usr/local/bin/swa"; fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "38-rust: TOOLCHAIN BROKEN" >&2
  exit 1
fi
echo "38-rust: ok ($RUST_STABLE, $RUST_NIGHTLY, cargo-nextest $NEXTEST_VERSION)"
