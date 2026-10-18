#!/usr/bin/env bash
# WSL2 の Ubuntu-24.04 ディストロの中に、ループのサンドボックスを作る。
# 冪等。何度流してもよい。
#
#   sudo ./provision.sh
#
# ディストロの既定ユーザー（保守ユーザー）は `maint` を想定している。
# 名前が違うときは:  sudo ADMIN_USER=<name> ./provision.sh
#
# 順番に意味がある。15-authkeys は 50-lockdown より前に流す（runner に
# ログインを許すのは 50-lockdown だから）。08-rename は /srv/swa を作る 20-layout より
# 前に流す。40-perms は /srv/swa の下に
# ファイルを作るものすべての後に流す。
set -euo pipefail
cd "$(dirname "$0")"

[ "$(id -u)" -eq 0 ] || { echo "sudo で流す" >&2; exit 1; }

# 05-isolation を最初に流す。wsl.conf が効いていなければ、プロビジョニングする
# サンドボックスが無い。その後のステップはすべて成功しつつ、何も意味しなくなる。
for s in 05-isolation.sh 08-rename.sh 10-users.sh 15-authkeys.sh 20-layout.sh 25-runner.sh 30-python.sh 35-node.sh 36-dotnet.sh 37-cpp.sh 40-perms.sh 45-agent-invoke.sh 50-lockdown.sh; do
  echo
  echo "=== $s ==="
  bash "$s"
done

# 全ステップが通ったコミットを残す。'swa update' は、これが今のコミットと同じなら
# プロビジョニングを飛ばす。途中で落ちれば書かれないので、次の 'swa update' が流し直す。
git -C .. rev-parse HEAD > /etc/swa/provisioned

echo
echo "=== プロビジョニング完了 ==="
echo "次は3役の資格情報を /etc/swa/<役>.env に入れる（provision/README §2-9）。"
echo "そのあと、最初の往復を確かめる:"
echo "    sudo -u runner /srv/swa/bin/smoke-solver"
echo
echo "60-egress.sh は流していない。流すかどうかは provision/README §4 を読んで決める。"
echo "流すまで、solver の外向きの通信は制限されない。"
echo
echo "この箱は、wsl.exe のセッションが握っているあいだだけ動く。握っているのは"
echo "Windows の keepalive タスクだ。ログオフをまたいだ無人の走行はできない"
echo "（provision/README §3-1）。"
