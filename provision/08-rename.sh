#!/usr/bin/env bash
# 名前が loop だったころに作った箱を、swa の名前に移す。冪等。移すものが無ければ何もしない。
#
# 20-layout より前に流す。20-layout は /srv/swa が無ければ空で作る。先に作られると、
# /srv/loop の中身を移す先がふさがる。
#
# 移すもの:
#   /srv/loop            -> /srv/swa。中の絶対パスのリンクと、作業ツリーの origin も向け直す
#   /etc/loop            -> /etc/swa。<役>.env の LOOP_* は SWA_* に書き換える
#   10-loop-dev.conf     -> 10-swa-dev.conf。保守ユーザーの AllowUsers を持つので消さずに移す
#   runner の safe.directory の /srv/loop
# 消すもの:
#   venv とビルドの置き場のうち /srv/loop を埋め込んだもの。後のステップが作り直す
#   loop-llm.service。使うなら 70-local-solver.sh を流し直して swa-llm を作る
#   /usr/local/bin/loop と sudoers の規則は 25-runner、sshd の 00-loop.conf は 50-lockdown が消す
set -euo pipefail

OLD=/srv/loop
NEW=/srv/swa

if pgrep -u runner -f 'loop\.py' >/dev/null 2>&1; then
  echo "08-rename: loop.py が走っている。先に古い箱の loop stop で止める" >&2
  exit 1
fi

# $1 を $2 に移す。両方あれば、どちらが正しいかここでは決められないので止まる。
move() {
  [ -e "$1" ] || [ -L "$1" ] || return 0
  if [ -e "$2" ] || [ -L "$2" ]; then
    echo "08-rename: $1 と $2 が両方ある。残すほうを決めてから流し直す" >&2
    exit 1
  fi
  mv -T "$1" "$2"
  echo "08-rename: $1 -> $2"
}

move "$OLD" "$NEW"
move /etc/loop /etc/swa
move /etc/ssh/sshd_config.d/10-loop-dev.conf /etc/ssh/sshd_config.d/10-swa-dev.conf

if [ -d /etc/swa ]; then
  for env in /etc/swa/*.env; do
    [ -f "$env" ] || continue
    if grep -q '^LOOP_' "$env"; then
      sed -i 's/^LOOP_/SWA_/' "$env"
      echo "08-rename: $env の LOOP_* を SWA_* に書き換えた"
    fi
  done
fi

if [ -d "$NEW" ]; then
  # swa-project.sh のリンクは絶対パスで張ってある。
  find "$NEW" -xdev -type l -lname "$OLD/*" -print0 | while IFS= read -r -d '' link; do
    target="$(readlink "$link")"
    ln -sfn "$NEW/${target#"$OLD"/}" "$link"
    echo "08-rename: $link -> $NEW/${target#"$OLD"/}"
  done

  # 作業ツリーの origin は /srv/loop/repo.git を指している。今のものと、しまってあるもの。
  for tree in "$NEW/project" "$NEW"/projects/*/project; do
    [ -d "$tree/.git" ] || continue
    url="$(sudo -u runner git -C "$tree" remote get-url origin 2>/dev/null || true)"
    case "$url" in
      "$OLD"/*)
        sudo -u runner git -C "$tree" remote set-url origin "$NEW/${url#"$OLD"/}"
        echo "08-rename: $tree の origin を $NEW/${url#"$OLD"/} に向け直した" ;;
    esac
    # venv のスクリプトは自分の絶対パスを持つ。30-python が作り直す。
    if grep -qs "$OLD/" "$tree/.venv/bin/activate"; then
      rm -rf "$tree/.venv"
      echo "08-rename: $tree/.venv を消した"
    fi
  done

  # CMakeCache と obj は絶対パスを持つ。置き場は 36-dotnet と 37-cpp が作り直す。
  for build in "$NEW/cpp/build" "$NEW/dotnet/build"; do
    if [ -d "$build" ] && grep -rqs --include=CMakeCache.txt --include=project.assets.json "$OLD/" "$build"; then
      rm -rf "$build"
      echo "08-rename: $build を消した"
    fi
  done
fi

if id runner >/dev/null 2>&1; then
  dirs="$(sudo -u runner git config --global --get-all safe.directory 2>/dev/null || true)"
  if printf '%s\n' "$dirs" | grep -q "^$OLD\(/\|$\)"; then
    sudo -u runner git config --global --unset-all safe.directory
    printf '%s\n' "$dirs" | sed "s#^$OLD\(/\|\$\)#$NEW\1#" | awk 'NF && !seen[$0]++' \
      | while IFS= read -r d; do sudo -u runner git config --global --add safe.directory "$d"; done
    echo "08-rename: runner の safe.directory を $NEW に向け直した"
  fi
fi

if [ -f /etc/systemd/system/loop-llm.service ]; then
  systemctl disable --now loop-llm >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/loop-llm.service
  systemctl daemon-reload
  echo "08-rename: loop-llm.service を消した。ローカルのソルバーを使うなら 70-local-solver.sh を流し直す"
fi
