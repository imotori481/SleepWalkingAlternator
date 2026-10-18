# よく使うコマンド

打つ場所は2つある。

| 場所 | 何か |
|---|---|
| ホスト | Windows の cmd、PowerShell、Git Bash。`host\` のスクリプトと git を使う |
| 箱 | `ssh swa-dev` で入った保守ユーザーの端末。`swa` コマンドを使う |

ホストの `swa` は `host\swa.cmd` のこと。中身は `ssh -t swa-dev swa <args>` で、ディストロの
起動と sshd の待機も先に済ませる。だから下の `swa` の行は、ホストと箱のどちらで打っても同じに動く。

ホストで `swa` だけで打つには、`host` ディレクトリをユーザーの PATH に足す。PowerShell で1回だけ
打ち、端末を開き直す。`swa-pull`、`swa-pr`、`swa-dashboard` も同じく名前だけで打てるようになる。

```powershell
$hostDir = "<repo-dir>\host"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", "$userPath;$hostDir", "User")
```

VS Code のターミナルは、VS Code 本体が起動したときの PATH を受け継ぐ。足したあとは、ターミナルでは
なく VS Code を全部閉じて起動し直す。Git Bash は拡張子を補わないので、`swa` ではなく `swa.cmd` と打つ。

PATH に足していなければ、`<repo-dir>` でパスごと呼ぶ。cmd なら `host\swa.cmd <args>`、
PowerShell なら `.\host\swa.cmd <args>`、Git Bash なら `./host/swa.cmd <args>`。

`<...>` は自分の値に置き換える。

| 記号 | 何を入れるか |
|---|---|
| `<repo-dir>` | ホストにクローンした SWA のリポジトリ |
| `<spec>` | 仕様書のファイルのパス。手元だけで使うものは `<repo-dir>\requirements\local\` に置く |
| `<module>` | モジュールの ID。詳細設計仕様書のパスから `docs/modules/` と `.md` を除いたもの（`core/board` など） |
| `<comment>` | 設計を書き直させるときに人が付けるコメント |
| `<project>` | 箱の中でのプロジェクトの名前。英小文字、数字、`.` `_` `-` |
| `<repo-url>` | 対象のリポジトリの GitHub の URL |
| `<clone-dir>` | ホストで対象のリポジトリをクローンしたディレクトリ |
| `<branch>` | SWA に作業させるブランチの名前 |
| `<base-branch>` | 元にするブランチの名前（`main` など） |
| `<pr-branch>` | PR に出すブランチの名前 |
| `<admin-user>` | 箱の保守ユーザーの名前 |
| `<src-dir>` | ソルバーがコードを書くディレクトリ。作業ツリーの根からの相対パス（`Assets/Source` など） |
| `<unity-project-dir>` | Unity で開いたことのあるプロジェクトのディレクトリ。`Assembly-CSharp.csproj` があるところ |
| `<tests-dir>` | ソルバーがテストを書くディレクトリ。`<src-dir>` を含まず、`<src-dir>` に含まれない場所 |
| `<you>` | Windows のユーザー名 |
| `<mirror-dir>` | `swa-pull` が写したプロジェクトのディレクトリ |
| `<port>` | ダッシュボードが待ち受けるポート。既定は 8443 |

## 走らせる（ホストでも箱でも）

流れは3段で、各段の出口で人が止める。上流で基本設計、中段で詳細設計と受け入れ条件、下流で
実装を作る。段を進めるのは `swa approve` だけだ。

| やりたいこと | コマンド |
|---|---|
| 仕様書を置き、基本設計を書かせる | `swa go <spec>... --language <言語>` |
| 持ち込む先を選んで始める | `swa go <spec>... --language <言語> --framework <持ち込む先>` |
| 今の段の設計を承認して次へ流す | `swa approve` |
| コメントを付けて今の段の設計を書き直させる | `swa reject <comment>` |
| 直すモジュールを選んで中段に戻す | `swa reopen <module>...` |
| 止まったところから続ける | `swa continue` |
| 状態を見る | `swa status` |
| ログを追う（Ctrl-C で抜けても走行は続く） | `swa log` |
| 止める | `swa stop` |
| いまの作業を JSON で見る | `swa now` |

言語は `python`、`typescript`、`cpp`、`csharp` のどれかで、省くと `python`。ホストで打つときは、
`<spec>` にホストのファイルのパスを1つだけそのまま渡せる。箱で打つときは複数渡せる。

段ごとに `swa approve` と `swa reject` がすることは次のとおり。

| 段 | `swa approve` | `swa reject <comment>` |
|---|---|---|
| 上流 | 基本設計を承認し、詳細設計を書かせてクリティックに読ませる | 基本設計を書き直させる |
| 中段 | 詳細設計を承認し、全モジュールを実装する | 詳細設計を書き直させ、クリティックに読ませ直す |

上流の成果物は `docs/basic/`、中段の成果物は `docs/modules/` と `ac/` にある。写しには `docs/`
だけが入る。受け入れ条件は箱で読む。

```bash
sudo -u runner cat /srv/swa/project/ac/<module>.json
```

## 止まったとき（ホストでも箱でも）

止まった理由と次の手は、`swa status` とログの最後の行に出る。

モジュールが下流で試行を使い切ると、走行は中段に戻って止まる。止まった理由は
`plan/FAILURE.md` にあり、`swa status` が先頭を見せる。直すモジュールを `swa reopen` で選び、
`swa reject <comment>` で書き直させる。設計を変えないなら、そのまま `swa approve` で流し直す。

| やりたいこと | コマンド |
|---|---|
| 途中で止まったモジュールを最後のコミットに戻す | `swa raw reset <module>` |
| 今の設計を検査する | `swa raw check` |
| クリティックの指摘を見る | `swa findings` |
| 批評だけをやり直す | `swa raw modules critique` |

`swa raw` は `swa.py` をそのまま runner として前面で呼ぶ。動詞の一覧は `swa raw --help`。

クリティックの指摘はプランナーに戻らない。書き直させたい指摘は、`swa reject` のコメントに書く。

走行の設定（試行回数、時間切れ、ソルバーの段）は `/srv/swa/settings.json` に置く。root が書く。

## プロジェクトを切り替える（ホストでも箱でも）

| やりたいこと | コマンド |
|---|---|
| 一覧を見る（`*` が今のもの） | `swa project list` |
| 今のプロジェクトの名前 | `swa project current` |
| 空のプロジェクトを用意する | `swa project init <project>` |
| 既存リポジトリのブランチを受け入れる用意をする | `swa project init <project> --branch <branch>` |
| 書き込みの柵の場所を決めて用意する | `swa project init <project> --src <src-dir> --tests <tests-dir>` |
| 作ってあるプロジェクトの柵の場所を変える | `swa project layout <project> --src <src-dir> --tests <tests-dir>` |
| Unity の参照アセンブリを送る（ホストだけ） | `swa-unity-refs <project> <unity-project-dir>` |
| 切り替える | `swa project use <project>` |
| ディレクトリと走行ログごと消す（今のものは消せない） | `swa project remove <project>` |
| `swa-project.sh` より前に作った箱に名前を付ける | `swa project adopt <project>` |

走行中は切り替えられない。先に `swa stop` か、終わるのを待つ。

## 既存のリポジトリのブランチで作業させる

GitHub とやり取りするのはホストだけだ。箱には GitHub の資格情報を置かない。ホストと箱のあいだは
`swa-runner`（ホストの `~/.ssh/config` に書いた接続先）で push と pull をする。
ホストの git のコマンドは、どれも `<clone-dir>` で打つ。

### 取り込む

ホストで1行打つ。下の1から4をまとめて流し、切り替えが終わるまで待つ。クローンは `C:\dev\roop-engin\projects\<project>` に置く。
ダッシュボードの「取り込み」タブでも同じことができる。

```bash
swa-import <project> <repo-url> <branch> [<base-branch>] [--src <src-dir>] [--tests <tests-dir>]
```

`--src` と `--tests` は書き込みの柵の場所で、省くと `src` と `tests`。

手で打つときは次の順に流す。

1. 作業用ブランチを切る（ホスト）

    ```bash
    git clone <repo-url> <clone-dir>
    cd <clone-dir>
    git switch -c <branch> <base-branch>
    ```

    もうクローンしてあるなら、`<clone-dir>` で最後の1行だけ打つ。

2. 受け皿を作る（箱）

    ```bash
    swa project init <project> --branch <branch>
    ```

3. ブランチを箱へ送る（ホスト）

    ```bash
    git push swa-runner:/srv/swa/projects/<project>/repo.git <branch>
    ```

4. 切り替えて走らせる（箱）

    ```bash
    swa project use <project>
    swa go <spec> --language <言語>
    ```

    `use` は、ブランチが push されていなければ何も動かさずに止まる。初回はプロビジョニングが
    走るので数分かかる。

### 成果を引き取る（ホスト）

```bash
swa-pull
```

`C:\dev\roop-engin\projects\<project>` の `<branch>` が箱の先まで進む。早送りできないときは `NOTE` が
出て、箱の成果は `swa/<branch>` にだけ入る。そのときは `<clone-dir>` で自分で合わせる。

```bash
git merge swa/<branch>
```

### PR に出す（ホスト）

全モジュールが緑になると、段は最終確認に移る。ダッシュボードで最終確認を承認すると、`<branch>-pr` から `<base-branch>` への PR が出る。
`swa-pr` の下書きの PR が開いていれば、新しく出さずに、その下書きが承認した状態で正式な PR になる。
先に `swa-pull` を流して、写しを箱の先まで進めておく。仕組みと前提は
[host/dashboard/README.md](../host/dashboard/README.md) の「プルリクエスト」にある。

全モジュールが緑になる前に出すなら、`swa-pull` のあとに `swa-pr` を打つ。ダッシュボードの「ホストの写し」タブの
「下書きの PR を出す」も同じことをする。最後に緑になったモジュールまでが、
`<branch>-draft` から `<base-branch>` への下書きの PR になる。
緑が増えたら、`swa-pull` と `swa-pr` をもう一度打てば同じ PR が更新される。
箱が写しより先に進んでいると、`swa-pr` は `NOTE` を出し、PR の本文にも印が付く。そのときは `swa-pull` から打ち直す。

| やりたいこと | コマンド |
|---|---|
| 途中の成果を下書きの PR に出す | `swa-pr` |
| 写しの場所を指定して出す | `swa-pr --project <mirror-dir>` |

`swa-import` より前に取り込んだプロジェクトは、親ブランチを1回だけ記録する。

```bash
git -C <clone-dir> config branch.<branch>.swaBase <base-branch>
```

手で出すときは次のとおり。`<branch>` には、箱が置いた環境のファイル（`conftest.py`、`index.html`、`vitest.config.mjs`、
`.gitignore` への追記）と設計（`plan/`、`docs/spec/`、`docs/basic/`、`docs/modules/`）がコミットされている。PR には要らないので、別のブランチで
消してから出す。`<branch>` そのものは消さずに残す。箱はこれからもそこで作業する。

```bash
git switch -c <pr-branch> <branch>
git rm -r -q --ignore-unmatch plan docs/spec docs/basic docs/modules conftest.py index.html vitest.config.mjs
git checkout origin/<base-branch> -- .gitignore
git commit -m "chore: SWAの環境のファイルを除く"
git push origin <pr-branch>
```

`<base-branch>` に `.gitignore` が無ければ、`git checkout` の行は失敗する。そのときは代わりに
`git rm -q .gitignore` を打つ。箱が作ったファイルなので、消せば元に戻る。

そのあと GitHub で `<pr-branch>` から `<base-branch>` へ PR を出す。

### 取り込むときの条件

- ソルバーが書けるのは、柵の2つのディレクトリの下だけだ。既定は `src/` と `tests/`。コードが別の場所にあるリポジトリ（Unity なら `Assets/` の下）は、`swa project layout` で場所を決める
- 自前の `conftest.py`、`index.html`、`vitest.config.mjs` があると、プロビジョニングは上書きせずに止まる
- `.gitignore` に `node_modules/` があると `35-node.sh` が止まる
- 依存パッケージは入らない。箱にあるのは pytest と vitest だけだ
- 既存のファイルでは、スタブは契約が挙げた名前の宣言だけを差し替える。既存のテストは凍結されるので、振る舞いを変えるとそのテストが回帰として落ちる

## C++ で作業させる

```bash
swa go <spec> --language cpp
```

箱は標準の C++17 のロジックだけを g++ と GoogleTest で確かめる。DXライブラリや Windows の API は箱に無い。

- `DxLib.h` や `windows.h` のように、標準でもリポジトリのものでもないヘッダを include するファイルはビルドから外す。外したファイルはプランナーのブリーフに並ぶ
- 描画、入力、音を扱うファイルもソルバーが書けるが、箱ではビルドも実行もしない。人が Visual Studio でビルドして画面を確かめる
- `DxLib.h` を include するファイルがあるか、要件が DXライブラリに触れていれば、プランナーに DXライブラリの主な関数の早見表を渡す
- 手元の `DxLib.h` を `swa refs dxlib <DxLib.h>` で送ると、箱の `/srv/swa/refs/dxlib` に置かれ、ソルバーが早見表に無い関数と定数をそこから引く。ホストで打つときは、ホストのファイルのパスをそのまま渡せる。DXライブラリを入れ替えたら送り直す
- 新しい `.cpp` と `.h` は Visual Studio のプロジェクト（`.vcxproj`）に入らない。詳細設計仕様書のパスを見て、人が足す
- ソースは ASCII だけで書かせる。画面に日本語を出すなら、Visual Studio でソースの文字コードの扱い（`/utf-8` など）を決めてから人が書き足す
- C++ の既存コードの宣言はまだプランナーに渡らない。スタブはソルバーが書き、ランナーは既存のファイルの残りが変わっていないかを確かめない

## 見る

| やりたいこと | 場所 | コマンド |
|---|---|---|
| 成果物をホストに写す | ホスト | `swa-pull` |
| VS Code で箱に入る | ホスト | `swa-dev` |
| 端末で箱に入る | ホスト | `ssh swa-dev` |

## ダッシュボード（ホスト）

ダッシュボードは `127.0.0.1:8443` だけで待ち受ける。「いまの作業」「設計」「クリティックの指摘」「モジュール」は
箱から直接読み、それ以外の欄はホストの写し（`C:\dev\roop-engin\project`）を読む。トークン消費の
グラフは、`C:\dev\roop-engin` の下の写しを全部読み、箱の今の回を重ねる。

### 起動する

| やりたいこと | コマンド |
|---|---|
| 設定ファイルを作る（初回だけ） | `copy host\dashboard\config.example.json host\dashboard\config.json` |
| 写しを最新にする | `swa-pull` |
| 起動する | `swa-dashboard` |
| 写しの場所を指定して起動する | `python host\dashboard\server.py --project <mirror-dir>` |
| ポートを変えて起動する | `python host\dashboard\server.py --project <mirror-dir> --port <port>` |
| 止める | 起動した端末で Ctrl-C |

起動したら <http://127.0.0.1:8443> を開く。`config.json` が無くても進捗の画面は使える。

`swa-dashboard` は写しのディレクトリが無いと起動しない。初回は先に `swa-pull` を流す。設計がまだ
無いあいだは、「いまの作業」だけが埋まる。

「いまの作業」は5秒ごとに `ssh swa-dev swa now` を `BatchMode=yes` で流す。鍵にパスフレーズが
あるなら、先に ssh-agent に載せておく。

### 画面から操作する

画面の「操作」で、次をコマンドなしで済ませる。

| やりたいこと | 欄 | 同じことをするコマンド |
|---|---|---|
| 仕様書から始める | 走行 | `swa go <spec> --language <言語>` |
| 止まったところから続ける | 走行 | `swa continue` |
| 止める | 走行 | `swa stop` |
| 途中で止まったモジュールを最後のコミットに戻す | 走行 | `swa raw reset <module>` |
| プロジェクトを切り替える | プロジェクト | `swa project use <project>` |
| 役ごとのモデルと effort を変える | 役のモデル | `/etc/swa/<役>.env` の `SWA_MODEL` と `SWA_EFFORT` を書き換える |
| 写しを最新にする | ホストの写し | `swa-pull` |
| 途中の成果を下書きの PR に出す | ホストの写し | `swa-pr` |
| 既存リポジトリのブランチを取り込む | 取り込み | `swa-import <project> <repo-url> <branch> [<base-branch>]` |

画面の「設計」で、段のせきをコマンドなしで済ませる。走っている間は出ない。

| やりたいこと | 段 | 同じことをするコマンド |
|---|---|---|
| 基本設計か詳細設計を承認して次の段へ流す | 上流、中段 | `swa approve` |
| コメントを付けて書き直させる | 上流、中段 | `swa reject <コメント>` |
| 直すモジュールを選んで中段に戻す | 中段（下流で止まった後）、最終確認 | `swa reopen <module>...` |

最終確認の承認と差し戻しは「人間の対応待ち」で記録する。差し戻しを記録しても箱は動かないので、
続けて「設計」で直すモジュールを中段に戻す。

箱は、これらを `swa dash` の1本で受ける。箱を更新したら、`provision.sh` を流し直して sudoers の
規則を入れる。

### スマホや他の PC から見る

| やりたいこと | コマンド |
|---|---|
| tailnet に公開する | `tailscale serve --bg --https=8443 http://127.0.0.1:8443` |
| 公開の状態を見る | `tailscale serve status` |
| 公開をやめる | `tailscale serve --https=8443 off` |
| 名簿に書くログイン名を見る | `tailscale status` |

公開するには、`config.json` の `remote` に公開名（`<machine>.<tailnet>.ts.net:8443`）と、見てよい人の
Tailscale のログインを書く。どちらかが無ければ、tailnet からの要求はすべて拒まれる。
`tailscale funnel` は使わない。インターネット全体に公開される。

リモートから、最終確認の承認、走行の開始、プロジェクトの切り替え、モデルの変更、写しの更新、
下書きの PR、取り込みはできない。最終確認の差し戻し、設計のせきの承認と差し戻し、中段に戻すモジュールの選択、
走行の停止と続行、止まったモジュールのやり直しはできる。

設定の詳細: [host/dashboard/README.md](../host/dashboard/README.md)

## 箱を保守する

### 更新する（箱）

スクリプトやランナーを更新したら、`swa update` を流す。このリポジトリを pull し、プロビジョニングを
流し直す。何度流しても同じ状態になる。走行中とプロジェクトの切り替え中は断る。
ホストからは `host\swa.cmd` で `swa update` と打つ。

pull の後のコミットが、最後にプロビジョニングが通ったコミット（`/etc/swa/provisioned`）と同じなら、
プロビジョニングを飛ばす。プロビジョニングが途中で落ちたときは記録が古いままなので、次の
`swa update` が流し直す。コミットが同じでも流し直すときは `--force` を付ける。

```bash
swa update
swa update --force
```

`swa update` は最初のプロビジョニングが置く。それより前は次の2行を流す。

```bash
sudo git -C /opt/swa pull
cd /tmp && sudo ADMIN_USER=<admin-user> bash /opt/swa/provision/provision.sh
```

### 配管を確かめる（箱）

smoke は、箱の配管が繋がっているかを最小の往復で確かめる検査だ。箱を作ったあと、資格情報を
入れ替えたあと、プロビジョニングのスクリプトや起動スクリプトを直したあとに流す。
runner として流す。

| smoke | 確かめること |
|---|---|
| `smoke-solver` | ランナーがソルバーを別の uid で起動できるか。認証、端末なしの実行、書いたファイルの所有者 |
| `smoke-pytest` | ソルバーが pytest を実行できないこと |
| `smoke-planner` | プランナーが動き、設計にもテストにも直接触れず、コードを読めても書けないこと |
| `smoke-critic` | クリティックが起動でき、書いたファイルを読み戻せること |
| `smoke-dom` | happy-dom の UI の関門が、生きた UI で通り、壊れた UI で落ちること |
| `smoke-page` | 開発サーバで `index.html` を開くと `src/main.ts` の `start` まで届くこと |

```bash
sudo -u runner /srv/swa/bin/smoke-solver
sudo -u runner /srv/swa/bin/smoke-pytest
sudo -u runner /srv/swa/bin/smoke-planner
sudo -u runner /srv/swa/bin/smoke-critic
sudo -u runner /srv/swa/bin/smoke-dom
sudo -u runner /srv/swa/bin/smoke-page
```

### keepalive を起こし直す（ホスト）

VM が落ちて keepalive が戻らないときは、cmd でタスクを起こし直す。

```bat
schtasks /run /tn "WSL-keepalive-Ubuntu-24-04"
```

## リポジトリのテスト（ホスト）

ホストにクローンした SWA のリポジトリの根で流す。Python 3 が要るので、普段使いの WSL
ディストロ（箱の `Ubuntu-24.04` ではないもの）から流す。箱は Windows のパスを見せないので、
そこでは流せない。

```bash
python3 -m unittest discover -s runner/tests
python3 -m unittest discover -s host/dashboard/tests
```

## 詳しい説明

- 段と止まる場面: [RUNNER_SPEC.md](RUNNER_SPEC.md) §3、§7
- プロジェクトの切り替え: [provision/README.md](../provision/README.md) §2-11
- ホスト側のスクリプトと SSH の設定: [host/README.md](../host/README.md)
- ダッシュボードの設計と設定: [host/dashboard/README.md](../host/dashboard/README.md)
- `swa.py` の動詞と終了コード: [RUNNER_SPEC.md](RUNNER_SPEC.md)
