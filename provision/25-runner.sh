#!/usr/bin/env bash
# ランナー本体を /srv/swa/runner/swa.py に置く。何度走らせても同じ結果になる。
#
#     sudo -u runner python3 /srv/swa/runner/swa.py <verb>
#
# root 所有、runner からは読めて実行できるが書けない。ランナーは関門を強制する
# 側で、その関門はこのファイルに書いてある。runner が自分のコードを書き換え
# られたら、RED_GATE も FREEZE も VERIFY も runner の気分次第になる。
# 更新はリポジトリを pull して、このスクリプトを流し直すことで行う。
set -euo pipefail
cd "$(dirname "$0")"

SRC=../runner/swa.py
DEST=/srv/swa/runner

[ -f "$SRC" ] || { echo "25-runner: $SRC not found (run from a full clone)" >&2; exit 1; }

install -d -o root -g root -m 755 "$DEST"
install -o root -g root -m 644 "$SRC" "$DEST/swa.py"

# 保守ユーザーが打つ `swa` コマンド。PATH の通った場所に置く。
install -o root -g root -m 755 bin/swa /usr/local/bin/swa

# ホストのダッシュボードは、走行の開始と停止、続行、プロジェクトの切り替え、役のモデルの
# 変更を SSH で `swa dash` に頼む。端末の無い SSH ではパスワードを訊けないので、保守
# ユーザーにこの1つだけをパスワード無しで許す。引数まで固定するので、ほかのコマンドには
# 効かない。要求は標準入力で渡り、swa_dash.py が確かめる。
ADMIN_USER="${ADMIN_USER:-maint}"
SUDOERS=/etc/sudoers.d/swa-dash
tmp="$(mktemp)"
echo "$ADMIN_USER ALL=(root) NOPASSWD: /usr/local/bin/swa dash" > "$tmp"
visudo -cqf "$tmp" || { rm -f "$tmp"; echo "25-runner: sudoers rule does not parse" >&2; exit 1; }
install -o root -g root -m 440 "$tmp" "$SUDOERS"
rm -f "$tmp"
# 名前が loop だったころのコマンドと規則。
rm -f /usr/local/bin/loop /etc/sudoers.d/loop-dash /etc/sudoers.d/loop-continue

# ---- 検査。runner の視点で確かめる ------------------------------------
fail=0
if ! sudo -u runner test -r "$DEST/swa.py"; then
  echo "FAIL: runner should be able to: test -r $DEST/swa.py"; fail=1
fi
if sudo -u runner test -w "$DEST/swa.py"; then
  echo "FAIL: runner should NOT be able to: test -w $DEST/swa.py"; fail=1
fi
if sudo -u runner test -w "$DEST"; then
  echo "FAIL: runner should NOT be able to: test -w $DEST"; fail=1
fi
# 走行は runner として /usr/local/bin/swa を実行する。runner が書き換えられれば、
# 関門の外で好きなコマンドを走らせられる。
if sudo -u runner test -w /usr/local/bin/swa; then
  echo "FAIL: runner should NOT be able to: test -w /usr/local/bin/swa"; fail=1
fi
if ! bash -n /usr/local/bin/swa; then
  echo "FAIL: /usr/local/bin/swa does not parse"; fail=1
fi
# パスワード無しで許すのは `swa dash` だけ。runner には許さない。
if ! sudo -l -U "$ADMIN_USER" | grep -q "NOPASSWD: /usr/local/bin/swa dash"; then
  echo "FAIL: $ADMIN_USER should be able to: sudo -n /usr/local/bin/swa dash"; fail=1
fi
if sudo -l -U "$ADMIN_USER" | grep -q "NOPASSWD: /usr/local/bin/swa continue"; then
  echo "FAIL: $ADMIN_USER should NOT keep: sudo -n /usr/local/bin/swa continue"; fail=1
fi
if sudo -l -U runner 2>/dev/null | grep -q "/usr/local/bin/swa"; then
  echo "FAIL: runner should NOT be able to: sudo /usr/local/bin/swa"; fail=1
fi
# 構文が壊れたファイルを置いたまま ok と言わない。py_compile ではなく ast で
# 確かめる。py_compile は __pycache__ を書こうとし、$DEST は runner から書けない。
if ! sudo -u runner python3 -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" "$DEST/swa.py"; then
  echo "FAIL: $DEST/swa.py does not parse"; fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "25-runner: ok"
else
  echo "25-runner: RUNNER INSTALL BROKEN" >&2
fi
exit "$fail"
