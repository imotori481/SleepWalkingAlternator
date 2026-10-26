# 起動スクリプト（planner-run、critic-run、solver-claude）に共通の前置き。
# 45-agent-invoke.sh が root 所有の 644 で /srv/swa/bin に置く。役のアカウントは
# 書けないので、source しても柵は緩まない。
#
#     . /srv/swa/bin/agent-common.sh
#     agent_setup <自分の名前> <役>
#     agent_subagent_model <自分の名前> <役>   # 助手を使う役だけ

# 資格情報、モデルと effort、使い捨ての HOME を用意する。role_args を設定する。
#
# 資格情報は役ごとに、その uid だけが読めるファイルに置く。利用枠を使い切った役が
# 別の役の実行を止められてはならず、1つが破られても別の役の資格情報が渡っては
# ならない。CLAUDE_CODE_OAUTH_TOKEN は `claude setup-token` で作るサブスクリプション
# のトークン。ANTHROPIC_API_KEY_CONSOLE は予備に置く従量課金の Console クレジット。
# export するのはちょうど1つなので、どちらが代金を払ったかが曖昧にならない。
# トークンが無いときは、分かりにくい認証エラーではなく課金に切り替わる。
#
# <役>.env の SWA_MODEL を --model で、SWA_EFFORT を --effort で渡す。空なら
# アカウントの既定。effort の値が間違っていたら、claude を呼ぶ前に止める。claude の
# 側で落ちると、ランナーはそれを役の失敗と扱う。
#
# HOME は呼び出しごとに使い捨てにする。Claude Code は設定、ポリシー、バックアップの
# 状態を HOME に書く。毎回新しくすれば、ある呼び出しから次へ何も持ち越せない。
# `--bare` なら1つのフラグで済むが、--bare は OAuth を拒む。サブスクリプションの
# トークンはまさに OAuth だ（2026-08-18 に実測）。
agent_setup() {
  local me="$1" role="$2"
  if [ -r "/etc/swa/$role.env" ]; then
    set -a
    . "/etc/swa/$role.env"
    set +a
  fi
  if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    if [ -n "${ANTHROPIC_API_KEY_CONSOLE:-}" ]; then
      export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY_CONSOLE"
      echo "$me: サブスクリプションのトークンが無いので、Console のクレジットを使う" >&2
    else
      echo "$me: /etc/swa/$role.env に資格情報が無い" >&2
      echo "    サブスクリプション（推奨）: sudo -u $role -H claude setup-token で発行して書く" >&2
      exit 3
    fi
  fi
  unset ANTHROPIC_API_KEY_CONSOLE

  role_args=()
  if [ -n "${SWA_MODEL:-}" ]; then
    role_args+=(--model "$SWA_MODEL")
  fi
  if [ -n "${SWA_EFFORT:-}" ]; then
    case "$SWA_EFFORT" in
      low|medium|high|xhigh|max) role_args+=(--effort "$SWA_EFFORT") ;;
      *) echo "$me: bad SWA_EFFORT in $role.env: $SWA_EFFORT" >&2; exit 5 ;;
    esac
  fi

  HOME="$(mktemp -d)"
  export HOME
  trap 'rm -rf "$HOME"' EXIT
}

# <役>.env の SWA_SUBAGENT_MODEL を確かめる。空なら 1 を返し、助手を使わない。
# 値は --agents の JSON に埋め込むので、英数字と . _ - だけを通す。
# CLAUDE_CODE_SUBAGENT_MODEL は、名前を指定しない助手のモデルも同じものにする。
agent_subagent_model() {
  local me="$1" role="$2"
  [ -n "${SWA_SUBAGENT_MODEL:-}" ] || return 1
  if ! [[ "$SWA_SUBAGENT_MODEL" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "$me: bad SWA_SUBAGENT_MODEL in $role.env: $SWA_SUBAGENT_MODEL" >&2
    exit 5
  fi
  export CLAUDE_CODE_SUBAGENT_MODEL="$SWA_SUBAGENT_MODEL"
}
