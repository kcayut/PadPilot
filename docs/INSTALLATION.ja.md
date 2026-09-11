# PadPilot インストールガイド

[繁體中文](INSTALLATION.md) | [English](INSTALLATION.en.md) | **日本語** · [ドキュメント](README.ja.md)

PadPilot は **Swift/AppKit のメニューバーアプリ、Python コア、Tk 設定画面**で構成されます。インストーラーは `~/Applications/PadPilot.app` のビルド・インストール・起動も行います。追加の pip パッケージや Swift パッケージは不要です。

## 環境の準備

- macOS 14 以降。主な検証環境は Apple Silicon です。
- Python 3.10 以降。設定画面には同じ Python 環境の `tkinter` が必要です。インストーラーは Python/Tk をインストールしません。pip で追加するパッケージはありません。
- ローカルビルド用の Apple Command Line Tools。Xcode 全体は不要です。
- CLI 制御が利用できる [BetterDisplay](https://github.com/waydabber/BetterDisplay)。ライセンス条件は提供元の説明をご確認ください。
- Sidecar 対応 iPad。まず macOS の「画面ミラーリング」で手動接続できることを確認します。

```bash
xcode-select --install
python3 --version
python3 -c "import tkinter"
xcrun --find swiftc
```

Tk がない場合は警告を表示します。daemon、CLI、ネイティブメニューはインストールできますが、設定画面を開く操作は無効になります。使用する Python に対応した Tk を追加し、異なる Python 環境を混在させないでください。Sidecar にはログイン済みのユーザーセッションが必要です。FileVault のロック解除前は PadPilot で画面を表示できません。[トラブルシューティング](TROUBLESHOOTING.ja.md#filevault)を参照してください。

## インストール・アップグレード

プロジェクトフォルダーで実行します。

```bash
./scripts/install.sh --check
./scripts/install.sh
./bin/padpilot-cli status

# BetterDisplay がない場合の Homebrew インストールに自動同意する場合：
./scripts/install.sh --yes
```

`--check` は読み取り専用です。Homebrew の実行、設定・ログの作成、ビルド、サービス起動、ハードウェア検索、画面変更は行いません。必須項目が不足すると非ゼロで終了し、Tk の不足は警告にとどまります。BetterDisplay CLI の help 成功だけでは、ライセンスや Sidecar の動作は確認できません。GitHub リポジトリは非公開でアクセス権が必要ですが、取得済みのソースフォルダーも利用できます。

インストーラーの処理：

1. macOS 14 以降、Python 3.10 以降、Tk の有無、Swift コンパイラー、BetterDisplay と CLI の応答を確認します。BetterDisplay がなければ Homebrew での導入を提案します。同意しない場合、導入失敗、CLI が使えない場合は成功と表示せず停止します。
2. アプリをビルドしてローカル署名し、`~/Applications/PadPilot.app` への配置を準備します。
3. 停止前に LaunchAgent とサービスの実行状態を記録します。共通 CLI で以前のサービスとメニューを停止してアプリを置き換え、設定とペアリングを保持します。
4. このチェックアウトに属する旧統合リンクを整理します。削除対象はゴミ箱へ移し、他のアプリは変更しません。
5. ログイン時起動の設定を保持し、`padpilot-cli start` から共通 autostart 処理を使って Python サービスとメニューを起動します。初回はログイン時起動が有効です。このプロジェクトの daemon から構造化された socket 応答を受信して初めて成功とします。失敗時は以前のアプリ・LaunchAgent・導入前のサービス実行状態の復元を試み、復元失敗も明示します。単独起動に失敗した場合は、その操作で作成した子プロセスを終了します。
6. `~/bin` が存在し、同名の項目がなければ CLI ショートカットを作成します。

アプリには Python とソースのパスが記録されます。**その Python 環境とプロジェクトフォルダーを残してください。** Python は同梱されていません。移動後は再インストールが必要です。別のチェックアウトに属する同名アプリや LaunchAgent は上書きしないため、移動前に元の場所でアンインストールしてください。Developer ID 署名、公証、自動更新は含まれていません。

## 起動とペアリング

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

メニューの設定・ペアリング画面で、デバイスの検索、ペアリング保存、操作対象の選択ができます。ペアリング削除には確認が必要です。CLI からも操作できます。

```bash
./bin/padpilot-cli pair --interactive
./bin/padpilot-cli gui
./bin/padpilot-cli gui diagnostics
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
./bin/padpilot-cli start            # サービスを起動し、メニューを表示
./bin/padpilot-cli stop             # サービスを停止し、メニューは保持
./bin/padpilot-cli exit             # サービスとメニューを終了
./bin/padpilot-cli autostart status
./bin/padpilot-cli autostart toggle
python3 scripts/build_app.py        # build/PadPilot.app のビルドのみ
./bin/padpilot-cli menu-json        # ハードウェア検索なしでメニューモデルを読む
```

テストには、3 言語のネイティブメニューデコード、サブメニュー、選択・無効状態、許可コマンドの検証が含まれます。

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
python3 scripts/check_release.py --gui
```

リリース検査では Shell、plist、バージョン整合性、ResourceWarning、現行ファイルと Git 履歴のプライバシーパターンも確認します。結果は `build/release-check.json` と `build/privacy-scan.json` に出力し、一致した値は含めません。審査済みの履歴例外は別欄に残し、新たな一致はテスト成功時でも終了コード 1 になります。デスクトップセッションがなければ `--gui` を付けず、GUI は未検証とします。[実機受け入れ検証](development/2026-09-11-release-readiness.ja.md)の代わりにはなりません。

## アンインストール

```bash
./scripts/uninstall.sh
./scripts/uninstall.sh --purge
```

通常は、このプロジェクトのサービスとメニューを停止し、アプリ、LaunchAgent、CLI リンクをゴミ箱へ移して状態スナップショットを消去します。設定とログは保持し、`--purge` 指定時は両方と使用済みの `/tmp/PadPilot/config.json` 代替設定もゴミ箱へ移します。復元可能です。ソース、BetterDisplay、他のアプリ、仮想ディスプレイは削除しません。
