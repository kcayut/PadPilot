# PadPilot インストールガイド

[繁體中文](INSTALLATION.md) | [English](INSTALLATION.en.md) | **日本語** · [ドキュメント](README.ja.md)

PadPilot は **Swift/AppKit のメニューバーアプリ、Python コア、Tk 設定画面**で構成されます。インストーラーは `~/Applications/PadPilot.app` のビルド・インストール・起動も行います。追加の pip パッケージや Swift パッケージは不要です。

導入・削除の前に変更を保存し、PadPilot の設定・診断画面を閉じてください。開いたままの場合は停止し、再実行を案内します。

## 環境の準備

- macOS 14 以降。主な検証環境は Apple Silicon です。
- Python 3.10 以降。設定画面には同じ Python 環境の `tkinter` が必要です。追加の pip パッケージはありません。
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

**公開の前提条件：** [kcayut/PadPilot](https://github.com/kcayut/PadPilot) が公開され、今回のスクリプトが `main` に配置されている必要があります。非公開リポジトリや未公開スクリプトは 404 になるため、それまでは権限を持って取得したソースで下記の手順を実行してください。スクリプト全体を一時ファイルへダウンロードしてから実行し、ソースのアーカイブもパスとファイルの種類を検査してから展開します。

ダウンロードに Git や Python の事前導入は不要です。ソースは `~/Applications/PadPilot-source` に保存し、既存の無関係なフォルダーは上書きしません。再実行時は同じソースを使用して導入を再開し、自動更新はしません。`.padpilot-install.json` は管理対象のソースと新規導入した依存関係を記録するため、残してください。

## 依存関係の選択とローカル導入

取得済みのソースでは、プロジェクトフォルダーで `./scripts/install.sh` を実行します。上記のダウンロードを利用した場合：

```bash
cd "$HOME/Applications/PadPilot-source"
./scripts/install.sh --check
./scripts/install.sh
"$HOME/bin/padpilot-cli" status
```

`--check` は全項目を読み取り専用で確認します。Homebrew の実行、設定・ログの作成、ビルド、サービス起動、ハードウェア検索、画面変更は行いません。必須項目の不足は非ゼロで終了し、Tk の不足は警告にとどまります。

対話型の導入では Python/Tk と BetterDisplay の検出結果を表示し、そのまま使用するか、別のパスを入力するか、不足分を導入するかを選べます。Python と Tk は同じ環境である必要があります。Homebrew 自体や依存関係をインストールする前に確認し、管理者パスワードが必要な場合は公式インストーラーが処理します。Apple Command Line Tools は macOS の画面で導入を完了してから PadPilot のインストーラーを再実行してください。

```bash
# 既存の環境を指定。空白を含むパスは引用符で囲みます。
./scripts/install.sh --python "/path/to/python3" --betterdisplay-path "/Applications/BetterDisplay.app"

# 非対話：既存の依存関係だけを使用。不足時は停止します。
./scripts/install.sh --yes

# Homebrew による不足分の導入を明示的に許可します。
./scripts/install.sh --yes --install-deps

# Tk 設定画面なしで続行。daemon、CLI、ネイティブメニューは使用可能です。
./scripts/install.sh --headless
```

`--python` は Python 実行ファイル、`--betterdisplay-path` は `.app` フォルダーまたは CLI 実行ファイルを指定します。`--yes` は第三者ソフトウェア導入の許可ではなく、Tk 不足時は停止します。対応する Tk を追加するか、`--install-deps` または明示的に `--headless` を指定してください。`--check` では Tk 不足は警告だけです。BetterDisplay CLI の help 成功だけでは、ライセンス、Sidecar、実際の画面表示は確認できません。

Homebrew では対応する Python 3.14 と [python-tk@3.14](https://formulae.brew.sh/formula/python-tk@3.14)、公式の [betterdisplay cask](https://formulae.brew.sh/cask/betterdisplay) を使用します。`--yes --install-deps` でも管理者パスワードや Apple のインストール画面が必要な場合があり、完全な無人導入は保証しません。

`~/Applications/PadPilot.app` をビルドしてローカル署名し、設定、ペアリング、ログイン時起動の設定を保持します。初回はログイン時起動が有効です。旧サービスとメニューを共通 CLI で停止する前に LaunchAgent と実行状態を記録し、新しい daemon の構造化された応答を確認して初めて成功とします。起動失敗時は旧アプリ、LaunchAgent、実行状態の復元を試み、復元失敗も明示します。

選択した Python を使用する `~/bin/padpilot-cli` の作成を試みます。同名の入口が他のプログラムに使われている場合は保持し、代わりに `"$HOME/Applications/PadPilot.app/Contents/Resources/padpilot-cli"` を使用します。**選択した Python 環境とソースフォルダーを残してください。** アプリは両方を参照するため、移動後は再インストールが必要です。他のソースに属するアプリや LaunchAgent は上書きしません。Python 同梱、Developer ID 署名、公証、自動更新は含まれません。

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

設定は保持され、以前のアプリはゴミ箱へ移ります。更新の自動ダウンロード、Git タグ作成、リリース公開は行いません。互換性のある旧版に戻すには、そのソースを復元して再インストールします。ゴミ箱からアプリだけを戻しても、参照するソースまでは戻りません。

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

リリース検査では Shell、plist、バージョン整合性、ResourceWarning、現行ファイルと Git 履歴のプライバシーパターンも確認します。結果は `build/release-check.json` と `build/privacy-scan.json` に出力し、一致した値は含めません。審査済みの履歴例外は別欄に残し、新たな一致はテスト成功時でも終了コード 1 になります。デスクトップセッションがなければ `--gui` を付けず、GUI は未検証とします。[実機受け入れ検証](development/2026-09-11-release-readiness.ja.md)の代わりにはなりません。

## アンインストール

どのフォルダーからでも実行できます。

```bash
/bin/bash "$HOME/Applications/PadPilot-source/scripts/uninstall.sh"
```

手動で取得したソースでは、元のプロジェクトフォルダーで `./scripts/uninstall.sh` を実行します。設定・ペアリング、ログ、管理対象のソース、インストーラーが新規導入した第三者の依存関係を個別に確認し、**既定ではすべて保持**します。削除内容の一覧を最終確認してから、このプロジェクトのサービスとメニューを停止し、アプリ、LaunchAgent、CLI 統合を削除します。

| オプション | 動作 |
| --- | --- |
| `--yes` | 非対話で PadPilot 本体と統合のみ削除し、設定、ログ、ソース、第三者の依存関係を保持。 |
| `--yes --purge` | 設定・ペアリングとログ、使用済みの `/tmp/PadPilot/config.json` 代替設定も削除。 |
| `--remove-config` / `--remove-logs` | 設定またはログを個別に指定。 |
| `--remove-source` | ダウンロード管理対象の `~/Applications/PadPilot-source` も削除。手動取得したソースは自動削除しません。 |
| `--remove-dependency NAME` | receipt に新規導入と記録された Homebrew 項目を指定。複数回指定可能で、記録のない既存ソフトは自動削除しません。 |

アプリ、統合、設定、ログ、選択したソースはゴミ箱へ移し、復元可能です。第三者の依存関係は Homebrew で削除するため PadPilot のゴミ箱復元対象外で、`autoremove` と `--zap` は使いません。他の Homebrew パッケージが必要とする Python/Tk は保持します。Homebrew 本体、Apple Command Line Tools、システム Python、既存の BetterDisplay、仮想ディスプレイは一緒に削除しません。

BetterDisplay の削除は Sidecar や仮想ディスプレイを切断する可能性があるため、追加で確認します。非対話の場合は `--allow-display-disconnect` も明示する必要があります。Python やソースは PadPilot が不要になってから削除してください。ソースを保持していればインストーラーの再実行で再導入できます。
