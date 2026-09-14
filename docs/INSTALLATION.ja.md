# PadPilot インストールガイド

[繁體中文](INSTALLATION.md) | [English](INSTALLATION.en.md) | **日本語** · [ドキュメント](README.ja.md)

## ビルド済みアプリを取得（推奨）

Apple Silicon、macOS 14 以降に対応し、Intel 版は提供しません。[GitHub Releases](https://github.com/kcayut/PadPilot/releases) の `.dmg` を開き、`PadPilot.app` を Applications にドラッグして起動します。ZIP、`SHA256SUMS`、`build-info.json` も提供します。Swift、CPython、標準ライブラリ、PadPilot のコアを同梱し、利用者によるビルドや pip パッケージの導入は不要です。

インストール済みのアプリをダブルクリックすると、操作画面とメニューバーのアイコンが同時に開きます。画面を閉じてもアイコンは残り、再度ダブルクリックすると画面を開き直せます。ログイン時やバックグラウンドでの起動では、メニューバーのアイコンのみ表示します。

新規導入は「手動のみ」が既定で、「起動時にモニターがなければ iPad に自動接続」も有効です。ログイン自動起動を有効にすると、起動後のログイン時に 1 回 30 秒で最大 3 回（合計最大 90 秒）探索し、見つからなければ停止します。対象が見つかり物理モニターがなければ 1 サイクル（最大 3 回）だけ接続を要求します。その後はメニューまたはグローバルショートカットで要求し、切断後に自動再接続しません。同じ起動セッションでアプリを再起動しても再試行しません。更新時は既存のモードとショートカットを保持します。この設定は接続成功を保証しません。[接続規則](ARCHITECTURE.ja.md#グローバル接続ショートカット)も参照してください。

**開発版は ad-hoc 署名のみで、Developer ID 署名と Apple の公証はありません。** 開発元や悪意あるソフトウェアを確認できない警告では、取得元を確認した上で [Apple の手順](https://support.apple.com/en-us/102445)に従い「プライバシーとセキュリティ → このまま開く」を利用してください。破損の警告では再取得して SHA-256 を確認します。Gatekeeper 全体を無効にしたり、すべてを誤警告と判断したりしないでください。

BetterDisplay アプリのインストール、起動、制御に必要なライセンスは引き続き必要です。独立した `betterdisplaycli` は任意で、アプリ内蔵 CLI で制御できます。`/Applications`、`~/Applications`、LaunchServices 登録先を検出します。詳細設定で App／CLI のパスを手動指定することもできます。

### スクリプトでの導入と Python 選択

設定を保存して画面を閉じてから、公式スクリプトを取得して実行します。既存の Python は不要です。

```bash
(
  set -e
  installer="$(mktemp -t padpilot-release-install)"
  trap 'rm -f "$installer"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/kcayut/PadPilot/main/scripts/install_release.sh \
    --output "$installer"
  /bin/bash "$installer"
)
```

プレリリースを含む最新の公開版を選び、SHA-256 を照合し、DMG を読み取り専用でマウントして同梱 Python を使用します。既定の配置先は `/Applications/PadPilot.app` です。書き込めない場合は `--target "$HOME/Applications/PadPilot.app"` を指定してください。sudo は不要です。まだ公開版がなければ停止し、ソース版へ自動変更しません。

- `--bundled`：同梱 CPython を使います。Python 指定なしの `--yes` も同じです。
- `--python /absolute/path/python3`：自分の Apple Silicon CPython 3.10 以降を使い、版、アーキテクチャ、必須モジュールを検証します。
- `--tag v0.1.0-dev.1`：公開済みの版を指定します。

新規インストール後はアプリを開くとサービスが起動します。更新時はネイティブのログインサービスを登録解除してからアプリを置き換え、有効だったログイン起動と実行状態を復元します。システムで無効にされた項目や許可待ちの項目は自動で再申請しません。設定とペアリングは保持され、スクリプト更新では Python を再選択します。失敗時はアプリ・設定・サービスの復元を試みます。配置先を変える場合は、下記 CLI で元のアプリを削除し、設定を保持してください。

### 導入後の Python 切り替えと復旧

GUI、CLI、daemon、ログイン起動は共通の選択を使用し、`~/Library/Application Support/PadPilot/python-runtime.json` に保存します。アプリの署名は変更しません。PadPilot を終了してから実行してください。

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --bundled-cli runtime external --python /absolute/path/python3
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --bundled-cli runtime bundled
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" runtime status
```

最初の二つのうち、外部または同梱のどちらかを選びます。外部 Python が削除された場合も `--bundled-cli` で復旧できます。他の PadPilot.app 内の Python は選択しないでください。

**リリース版を削除するには、メニューの「終了」を選び、Applications の PadPilot.app をゴミ箱へ移します。**「終了」でディスプレイ自動化を停止します。有効なネイティブログインサービスは、ポーリングせずアプリの移動イベントを監視し、ゴミ箱への移動時に自動で登録を解除して終了します。ゴミ箱内のアプリはバックグラウンド Python を起動しません。設定・ペアリング・ログは保持され、ログイン項目の名前が消えるまで時間がかかる場合があります。

データも削除したい場合や配置先を変更する場合は、任意で次の CLI を使えます。設定とログは既定で保持し、`--purge` を追加するとゴミ箱へ移します。アプリを削除する前に実行してください。

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --bundled-cli uninstall --yes
```

### 管理者：tag の push で自動公開

以下は GitHub の remote 名を `github` としています。GitHub から直接 clone した場合は通常 `origin` です。`git remote -v` で確認して置き換えてください。Gitea への push では GitHub Actions は起動しません。

```bash
git tag v0.1.0-dev.1
git push github v0.1.0-dev.1
```

まず公開する変更を commit します。`vX.Y.Z`、`vX.Y.Z-dev.N`／`alpha.N`／`beta.N`／`rc.N` に対応します。**ローカルで tag を作るだけでは起動せず、GitHub への push が必要です。** ARM runner がソフトウェア検査、ビルド、パッケージ化、移動後の動作検査を実行し、全添付ファイルの転送後に prerelease として自動公開します。Apple 証明書や手動承認は不要です。公開済み版は上書きせず、新しい tag を使用します。失敗した下書きは再実行できます。実機での受け入れ結果は引き続き unknown です。

ローカルで同じ成果物を作るには、Python 3.12 以降と Apple のビルドツールで `python3 scripts/build_release.py --tag v0.1.0-dev.1` を実行します。出力先は `dist/<tag>/` です。CPython の取得元と SHA-256 は `scripts/python-runtime.json` に固定し、ライセンス文書を同梱します。完全な tag と build commit は成果物に記録されます。

## ソース版の導入（開発用）

以下はローカルでビルドするソース版専用の手順です。

PadPilot は **Swift/AppKit メニュー、SwiftUI ネイティブ設定画面、Python コア**で構成されます。インストーラーは `~/Applications/PadPilot.app` のビルド・インストール・起動も行います。追加の pip パッケージや Swift パッケージは不要です。

導入・削除の前に変更を保存し、PadPilot の設定・診断画面を閉じてください。開いたままの場合は停止し、再実行を案内します。

## 環境の準備

- macOS 14 以降。主な検証環境は Apple Silicon です。
- バックグラウンドコア用の Python 3.10 以降。設定画面はネイティブアプリに内蔵されています。
- ローカルビルド用の Apple Command Line Tools。Xcode 全体は不要です。
- CLI 制御が利用できる [BetterDisplay](https://github.com/waydabber/BetterDisplay)。ライセンス条件は提供元の説明に従います。
- Sidecar 対応 iPad。まず macOS の「画面ミラーリング」で手動接続できることを確認します。

先にすべて手動で導入する必要はありません。インストーラーが検出し、既存環境の使用、パス指定、導入を選べます。Sidecar はログイン済みのユーザーセッションが必要で、FileVault 解除前は PadPilot で画面を表示できません。[トラブルシューティング](TROUBLESHOOTING.ja.md#filevault)を参照してください。

## コピーしてインストール

次のブロック全体をターミナルに貼り付けます。

```bash
(
  set -e
  installer="$(mktemp -t padpilot-install)"
  trap 'rm -f "$installer"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/kcayut/PadPilot/main/scripts/bootstrap.sh \
    --output "$installer"
  /bin/bash "$installer"
)
```

**ダウンロードの条件：** [kcayut/PadPilot](https://github.com/kcayut/PadPilot) が公開され、`scripts/bootstrap.sh` が `main` で公開されている必要があります。非公開リポジトリや未公開スクリプトは 404 になるため、それまでは権限を持って取得したソースで下記の手順を実行してください。スクリプト全体を一時ファイルへダウンロードしてから実行し、ソースのアーカイブもパスとファイルの種類を検査してから展開します。

ダウンロードに Git や Python の事前導入は不要です。ソースは `~/Applications/PadPilot-source` に保存し、既存の無関係なフォルダーは上書きしません。再実行時は同じソースを使用して導入を再開し、自動更新はしません。`.padpilot-install.json` は管理対象のソースと新規導入した依存関係を記録するため、残してください。

## 依存関係の選択とローカル導入

取得済みのソースでは、プロジェクトフォルダーで `./scripts/install.sh` を実行します。上記のダウンロードを利用した場合：

```bash
cd "$HOME/Applications/PadPilot-source"
./scripts/install.sh --check
./scripts/install.sh
"$HOME/bin/padpilot-cli" status
```

`--check` は全項目を読み取り専用で確認します。Homebrew の実行、設定・ログの作成、ビルド、サービス起動、ハードウェア検索、画面変更は行いません。必須項目の不足は非ゼロで終了します。

対話型の導入では Python と BetterDisplay の検出結果を表示し、そのまま使用するか、別のパスを入力するか、不足分を導入するかを選べます。Homebrew 自体や依存関係をインストールする前に確認し、管理者パスワードが必要な場合は公式インストーラーが処理します。Apple Command Line Tools は macOS の画面で導入を完了してから PadPilot のインストーラーを再実行してください。

```bash
# 既存の環境を指定。空白を含むパスは引用符で囲みます。
./scripts/install.sh --python "/path/to/python3" --betterdisplay-path "/Applications/BetterDisplay.app"

# 非対話：既存の依存関係だけを使用。不足時は停止します。
./scripts/install.sh --yes

# Homebrew による不足分の導入を明示的に許可します。
./scripts/install.sh --yes --install-deps
```

`--python` は Python 実行ファイル、`--betterdisplay-path` は `.app` フォルダーまたは CLI 実行ファイルを指定します。`--yes` は第三者ソフトウェア導入の許可ではなく、必須依存関係の不足時は停止します。手動で導入するか `--install-deps` を指定してください。BetterDisplay CLI の help 成功だけでは、ライセンス、Sidecar、実際の画面表示は確認できません。

Homebrew ではPython 3.14 と公式の [betterdisplay cask](https://formulae.brew.sh/cask/betterdisplay) を使用します。`--yes --install-deps` でも管理者パスワードや Apple のインストール画面が必要な場合があり、完全な無人導入は保証しません。

インストーラーは `~/Applications/PadPilot.app` をビルドしてローカル署名し、設定とペアリングを保持します。初回起動時にアプリ内のログインサービスを macOS に登録します。許可が必要な場合は「システム設定 → 一般 → ログイン項目」で PadPilot を許可してください。その後はシステム側の無効設定を尊重します。更新前に登録解除し、失敗時はアプリ・設定・以前のサービス状態の復元を試みます。「終了」は現在の実行セッションのみを停止し、次回ログインはシステムの登録に従います。

選択した Python を使用する `~/bin/padpilot-cli` の作成を試みます。同名の入口が他のプログラムに使われている場合は保持し、代わりに `"$HOME/Applications/PadPilot.app/Contents/Resources/padpilot-cli"` を使用します。**選択した Python 環境とソースフォルダーを残してください。** アプリは両方を参照するため、移動後は再インストールが必要です。他のソースに属するアプリや LaunchAgent は上書きしません。ソース版のアプリには Python を同梱せず、Developer ID 署名、公証、自動更新も提供しません。

## 起動とペアリング

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

メニューの設定・ペアリング画面で、デバイスの検索、ペアリング保存、操作対象の選択ができます。ペアリング削除には確認が必要です。CLI からも操作できます。

```bash
"$HOME/bin/padpilot-cli" pair --interactive
"$HOME/bin/padpilot-cli" gui
"$HOME/bin/padpilot-cli" gui diagnostics
```

設定は `~/Library/Application Support/PadPilot/config.json` に保存され、既存のペアリングは維持されます。

主保存先への書き込みに失敗すると `/tmp/PadPilot/config.json` を使用します。daemon・CLI・GUI・メニュー・導入前確認は、両方のうち最後に書き込まれたファイルを読みます。状態スナップショットも同じ規則です。代替先は一時保存であり長期バックアップではないため、主保存先の書き込み権限を修復してください。壊れた設定は自動リセット・上書きせず、サービス起動を拒否し、GUI にエラーを表示して保存を無効にします。元のファイルをバックアップしてから JSON を修復するか、有効な設定を復元してください。

## 更新と復元

以前のソースをバックアップし、設定を保存して画面を閉じてください。ソース更新後に「事前確認 → インストール → status」を再実行すると、ネイティブアプリも再ビルドされます。GUI の「このアプリについて」に表示する `v0.1.0` は CLI・アプリと同じ `core.__version__` を使用します。同ページに GitHub リンクと、まだ有効化されていない寄付欄もあります。

設定は保持され、以前のアプリはゴミ箱へ移ります。更新の自動ダウンロード、Git タグ作成、リリース公開は行いません。ゴミ箱からアプリだけを戻しても、参照するソースまでは戻りません。

## ローカルのプライバシーと権限

設定・runtime・ログの専用ディレクトリは `0700`、設定・状態・IPC socket・ログは `0600` です。他ユーザー所有、シンボリックリンク、複数のハードリンクを持つ状態ファイルを拒否します。`/tmp/PadPilot` の代替保存先も対象です。危険なパスは勝手に削除・取得せず停止します。[安全な起動の確認](TROUBLESHOOTING.ja.md#safe-startup)を参照してください。

IPC ログには既知のコマンド名だけを記録し、ペアリングの payload は記録しません。過去のログにはデバイス情報が残る可能性があるため、共有前に伏せてください。アンインストール時も広範なプロセス名での終了や、別プロジェクトの CLI リンク削除は行いません。

## 日常操作と開発

```bash
"$HOME/bin/padpilot-cli" start            # サービスを起動し、メニューを表示
"$HOME/bin/padpilot-cli" stop             # サービスを停止し、メニューは保持
"$HOME/bin/padpilot-cli" exit             # サービスとメニューを終了
"$HOME/bin/padpilot-cli" autostart status
"$HOME/bin/padpilot-cli" autostart toggle
python3 scripts/build_app.py        # build/PadPilot.app のビルドのみ
"$HOME/bin/padpilot-cli" menu-json        # ハードウェア検索なしでメニューモデルを読む
```

テストには、3 言語のネイティブメニューデコード、サブメニュー、選択・無効状態、許可コマンドの検証が含まれます。

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
python3 scripts/check_release.py --gui
```

リリース検査では Shell、plist、バージョン整合性、ResourceWarning、現行ファイルと Git 履歴のプライバシーパターンも確認します。結果は `build/release-check.json` と `build/privacy-scan.json` に出力し、一致した値は含めません。審査済みの履歴例外は別欄に残し、新たな一致はテスト成功時でも終了コード 1 になります。デスクトップセッションがなければ `--gui` を付けず、GUI は未検証とします。実機受け入れ検証の代わりにはなりません。

## アンインストール

どのフォルダーからでも実行できます。

```bash
/bin/bash "$HOME/Applications/PadPilot-source/scripts/uninstall.sh"
```

手動で取得したソースでは、元のプロジェクトフォルダーで `./scripts/uninstall.sh` を実行します。設定・ペアリング、ログ、管理対象のソース、インストーラーが新規導入した第三者の依存関係を個別に確認し、**既定ではすべて保持**します。削除内容の一覧を最終確認してから、このプロジェクトのサービスとメニューを停止し、ログインサービスを登録解除し、アプリと CLI 統合を削除します。

| オプション | 動作 |
| --- | --- |
| `--yes` | 非対話で PadPilot 本体と統合のみ削除し、設定、ログ、ソース、第三者の依存関係を保持。 |
| `--yes --purge` | 設定・ペアリングとログ、使用済みの `/tmp/PadPilot/config.json` 代替設定も削除。 |
| `--remove-config` / `--remove-logs` | 設定またはログを個別に指定。 |
| `--remove-source` | ダウンロード管理対象の `~/Applications/PadPilot-source` も削除。手動取得したソースは自動削除しません。 |
| `--remove-dependency NAME` | receipt に新規導入と記録された Homebrew 項目を指定。複数回指定可能で、記録のない既存ソフトは自動削除しません。 |

アプリ、統合、設定、ログ、選択したソースはゴミ箱へ移し、復元可能です。第三者の依存関係は Homebrew で削除するため PadPilot のゴミ箱復元対象外で、`autoremove` と `--zap` は使いません。他の Homebrew パッケージが必要とする Python は保持します。Homebrew 本体、Apple Command Line Tools、システム Python、既存の BetterDisplay、仮想ディスプレイは一緒に削除しません。

BetterDisplay の削除は Sidecar や仮想ディスプレイを切断する可能性があるため、追加で確認します。非対話の場合は `--allow-display-disconnect` も明示する必要があります。Python やソースは PadPilot が不要になってから削除してください。ソースを保持していればインストーラーの再実行で再導入できます。
