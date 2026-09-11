<p align="center">
  <img src="assets/padpilot-icon.png" width="160" height="160" alt="PadPilot アイコン：タブレット内のナビゲーション矢印">
</p>

<h1 align="center">PadPilot</h1>

<p align="center">
  <b>Sidecar display automation for Mac</b><br>
  iPad を、Mac の画面に。
</p>

<p align="center">
  <a href="README.md">繁體中文</a> | <a href="README.en.md">English</a> | <b>日本語</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version: 0.1.0">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-lightgrey.svg" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/status-early%20preview-orange.svg" alt="Status: Early Preview">
</p>

PadPilot は **Apple Sidecar と BetterDisplay** を使う macOS 向けディスプレイ自動化ツールです。主に Mac mini + iPad の利用を想定しています。物理モニターがない場合は指定した iPad への接続とメイン画面への設定を試み、モニターを接続した場合は動作モードと手動指定に従って画面の役割を調整します。

メニューバー、設定画面、CLI から接続やペアリングを管理し、現在の状態と切り替え理由を確認できます。

> [!IMPORTANT]
> **早期プレビュー版です。** 物理モニター、または利用可能なリモート接続を確保した状態で試してください。
> PadPilot はユーザーのログイン後に動作し、**FileVault のロック解除画面やログイン前の画面を iPad に表示することはできません。** インストールのために FileVault を無効にする必要はありません。モニターなしのコールドブートや各種ハードウェア構成は、実機検証が必要です。

## 特長

- **物理モニター優先：** 自動モードでは物理モニターがあれば Sidecar 接続を開始しません。接続済み iPad はサブ画面として維持できます。
- **iPad のメイン・サブ画面操作：** 接続、切断、再接続、役割変更に対応します。複数のペアリングを保存し、1 台を操作対象に選べます。
- **仮想画面による代替：** BetterDisplay の仮想ディスプレイでデスクトップを維持し、iPad への切り替え後も代替画面を保持します。
- **USB イベント：** 接続・取り外しでバックグラウンド評価を起動し、探索期間、定期確認、デバウンス、失敗時のクールダウンを組み合わせます。
- **判断の可視化：** 設定画面でデバイス検索、ペアリング、状態、診断、ログを確認できます。メニューはサービスが作成する状態スナップショットを読み取ります。
- **3 言語の UI：** 繁体字中国語、英語、日本語。コアは Python 標準ライブラリを使用し、追加の pip パッケージは不要です。

## 動作の概要

既定の `automatic` モードで、有効な手動指定がない場合：

| 現在の構成 | 想定する動作 |
| --- | --- |
| 物理モニターあり | 物理モニターをメインにし、iPad へ新規接続しません。接続済み iPad はサブ画面として維持します。 |
| 物理モニターなし、利用可能な iPad 対象あり | デバウンス後に Sidecar 接続を試み、iPad をメイン画面にします。 |
| 物理モニターも iPad 対象もなし | 設定済みの BetterDisplay 仮想画面を代替として使います。 |

`manual_only` は自動切り替えを停止し、手動操作を残します。`prefer_ipad` は iPad のメイン画面を優先します。手動指定は現在のハードウェア構成内で優先され、モード変更、リセット、構成変更後に再評価します。

既定値は、物理モニター切断のデバウンス **4 秒**、Sidecar 接続試行は最大 **3 回**、再試行間隔 **3 秒**、失敗後のクールダウン **30 秒**です。接続完了時間の保証ではありません。

## 必要な環境

| 項目 | 条件 |
| --- | --- |
| Mac | macOS 14 以降を対象とし、主な用途は Apple Silicon Mac mini です。他機種・OS の組み合わせは網羅的に検証していません。 |
| iPad | Sidecar 対応機種で、Mac と同じ Apple Account を使用し、2 ファクタ認証が有効なこと。 |
| Python | Python 3.10 以降。設定画面には同じ Python 環境で `tkinter` を読み込めることが必要です。インストーラーは Python/Tk を導入しません。 |
| [BetterDisplay](https://github.com/waydabber/BetterDisplay) | Sidecar と画面を制御します。macOS と互換性のある版を使用し、CLI が動作することを確認してください。CLI 制御には提供元の条件に従った Pro または有効な試用が必要です。 |
| Apple Command Line Tools | Swift/AppKit アプリのビルドに使用します。`xcode-select --install` で導入します。 |
| 接続 | 初回はデータ転送対応 USB ケーブルを推奨し、iPad で Mac を信頼します。ワイヤレス Sidecar には Wi-Fi、Bluetooth、Handoff も必要です。 |

対応機種と接続条件は [Apple の Sidecar ガイド](https://support.apple.com/en-us/102597)を参照してください。BetterDisplay の機能とライセンスは[提供元の説明](https://github.com/waydabber/BetterDisplay#key-features)に従います。PadPilot の MIT ライセンスに第三者ソフトウェアのライセンスは含まれません。

## クイックスタート

### 1. インストール

まず macOS の「画面ミラーリング」で Sidecar を手動利用できることを確認してください。

```bash
# ソースを取得した後、PadPilot フォルダーで実行：
./scripts/install.sh --check
./scripts/install.sh
./bin/padpilot-cli status
```

[kcayut/PadPilot](https://github.com/kcayut/PadPilot) は現在非公開で、アクセス権のあるアカウントだけが利用できます。正式な Release はまだありません。`--check` は依存関係の確認だけを行い、インストール、ユーザー設定の書き込み、サービス起動、画面変更はしません。Tk 不足は警告となり、設定画面への操作は無効になりますが、daemon、CLI、メニューは利用できます。同じ Python に対応する Tk を追加してください。

インストーラーは macOS、Python バージョン、Swift コンパイラー、BetterDisplay と CLI 応答を検査します。Homebrew があれば確認後に BetterDisplay を導入できます（`--yes` で同意）。必須項目不足や CLI 検査失敗時は停止します。その後 `~/Applications/PadPilot.app` をビルド・インストールし、ペアリング、動作モード、ログイン時起動の設定を保持して、**サービスとメニューを再起動**します。初回はログイン時起動が有効です。daemon の応答を確認して初めて成功とし、起動失敗時は以前のアプリ・LaunchAgent・導入前のサービス実行状態の復元を試み、復元失敗も明示します。

CLI 応答だけでは、Pro ライセンス、Sidecar ペアリング、権限、実際の画面表示は検証できません。下記の設定と実機確認を行ってください。

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

アプリはローカルの Python とソースを参照します。**Python 環境とプロジェクトフォルダーは残してください。** 移動後は再インストールが必要です。現在はローカルビルド版で、Python 同梱・公証済みの独立配布パッケージではありません。

### 2. iPad を指定

対話型ウィザードで操作対象を選びます。

```bash
./bin/padpilot-cli pair --interactive
```

設定画面でもデバイス検索、ペアリング保存、操作対象の選択ができます。

```bash
./bin/padpilot-cli gui
```

PadPilot のペアリングはデバイスの対応関係を記録するもので、Apple Account や「このコンピュータを信頼」の設定に代わるものではありません。複数台を保存できますが、同時に管理する操作対象は 1 台です。

### 3. 代替画面と状態を確認

モニターなしで使う場合、BetterDisplay に `PadPilotVirtual` という仮想画面があるか、設定画面で既存の仮想画面を選んでください。自動作成に対応しないバージョンでは、BetterDisplay で一度手動作成します。

```bash
./bin/padpilot-cli status
./bin/padpilot-cli open-log
```

`open-log` は状態・診断画面を開き、`open-log --raw` は生ログを開きます。リモート復旧が必要なら Screen Sharing/VNC または SSH を事前に設定してください。PadPilot はリモートアクセスを有効にせず、SSH 自体は仮想ディスプレイを必要としません。

`status` はサービスからの応答有無も表示します。無応答時の保存済みスナップショットは現在の状態を保証しません。`status --json` には `daemon_responding` とバージョンが含まれ、スナップショットがなければ画面状態は不明のままです。

## USB イベントと自動検出

メニューの設定・ペアリング → 動作と環境設定 → 詳細設定 → USB と iPad の自動検出で設定します。

- **USB イベントによる評価：** 既定で有効です。IOKit 通知で評価を起動し、30 秒ごとの定期確認も残します。起動時と USB イベント後は最大 30 秒、2 秒間隔で探索します。通知登録に失敗すると診断に表示し、定期確認を継続します。
- **iPad の自動検出：** 既定で有効です。Sidecar UUID を持つ指定済みペアリングを優先し、なければ単一の USB iPad と Sidecar 候補から推定します。保存済みの対応関係を優先し、照会失敗、候補不足、曖昧さがある場合は接続しません。
- **複数台の環境では明示的なペアリングを推奨：** 単一候補は推定にすぎず、USB と Sidecar が同じ機器である証明ではありません。周囲に他の iPad がある場合は自動検出を無効にして対象を指定してください。推定で保存済みペアリングを追加・変更しません。
- **有線と無線：** 指定済みペアリングは USB を外しても Sidecar の利用可否に応じて処理できます。USB だけで推定した未ペアリング対象では、取り外し後に無線接続を新規開始しません。

今回の対象は設定画面とメニューに表示されます。両スイッチは即時反映され、保存済みの無効設定は維持されます。

## メニューバーと表示言語

メニューバーには **18 × 18 pt、Retina 対応の単色アイコン**を使い、macOS のライト・ダーク表示に合わせます。ポインターを合わせると PadPilot の名前、メニューを開くとメイン画面、動作モード、デバイス、診断が表示されます。

<p align="center">
  <img src="assets/menu-icons/preview.png" width="540" alt="PadPilot メニューアイコン：Sidecar、物理画面、仮想画面、一時停止、警告、処理中">
</p>

順に Sidecar、物理画面、仮想画面、一時停止、警告、処理中を表します。画像は同梱されており、デザイン変更時には `swift scripts/build_menu_icons.swift` で再生成できます。

初回設定では macOS の言語から選択し、中国語・日本語以外では英語を使用します。メニューの Language、GUI の言語選択、`set-language` で変更できます。GUI の使い方、トラブルシューティング、診断ヘルプは選択言語のローカル文書を開きます。デバイス名、識別子、生ログは原文を維持します。

## よく使うコマンド

プロジェクトフォルダーで実行します。導入時に `~/bin/padpilot-cli` が作成され、`~/bin` が PATH にあれば `padpilot-cli` だけでも実行できます。

```bash
# 状態と設定
./bin/padpilot-cli status --json
./bin/padpilot-cli gui
./bin/padpilot-cli set-language ja        # zh-Hant または en も使用可能

# 動作モード：いずれかを選択
./bin/padpilot-cli set-mode automatic
./bin/padpilot-cli set-mode manual_only
./bin/padpilot-cli set-mode prefer_ipad

# 手動操作：必要に応じて実行
./bin/padpilot-cli action use_ipad_secondary
./bin/padpilot-cli action use_ipad_main
./bin/padpilot-cli action disconnect_ipad
./bin/padpilot-cli action reconnect_sidecar
./bin/padpilot-cli action refresh
./bin/padpilot-cli action reset           # 一時指定とクールダウンを解除

# サービスとログイン時起動
./bin/padpilot-cli stop
./bin/padpilot-cli start
./bin/padpilot-cli exit                  # サービスを停止し、メニューを閉じる
./bin/padpilot-cli autostart status
./bin/padpilot-cli autostart toggle

# バージョンとヘルプ
./bin/padpilot-cli --version
./bin/padpilot-cli --help
```

更新前に旧ソースをバックアップし、設定を保存して画面を閉じます。更新後は `./scripts/install.sh --check`、`./scripts/install.sh`、`./bin/padpilot-cli status` を再実行し、アプリも再ビルドします。GUI の「このアプリについて」、CLI `--version`、アプリは同じバージョン定義を使います。同ページには GitHub と寄付欄もあり、受取先 URL が設定されるまで寄付ボタンは無効です。互換性のある旧版へ戻すにはソースを復元して再インストールしてください。設定は保持され、旧アプリはゴミ箱にありますが、アプリだけを戻しても参照するソースは戻りません。

## 制限とトラブルシューティング

- **Sidecar は前提条件：** 非対応機種を対応させるものではなく、Universal Control のキーボード・ポインター移動も制御しません。
- **接続時間は環境に依存：** USB 通知、4 秒の待機、コマンド成功は画面表示完了を意味しません。クールダウン中は代替画面を優先します。
- **モニターなしの環境は要検証：** コールドブート、スリープ復帰、ハブ、複数デバイス構成は網羅的に検証していません。ログイン前の iPad 表示には対応せず、FileVault 無効化・自動ログインは動作を保証する手順ではありません。
- **他の画面制御ツールとの競合：** 別ツールがメイン画面や Sidecar を繰り返し変更する場合、`manual_only` にして判断理由とログを確認してください。

設定と状態は通常 `~/Library/Application Support/PadPilot/`、ログは `~/Library/Logs/PadPilot/` にあります。問題報告にはバージョン、接続方式、再現手順、関連ログを添え、シリアル番号、UUID、アカウント、個人のパスは伏せてください。

専用ディレクトリは `0700`、設定・状態・socket・ログは `0600` です。他ユーザー所有やリンクされた状態パスを拒否します。新しい IPC ログにペアリング payload は記録しませんが、過去のログは自動消去しません。検証済み環境と `unknown` の実機項目は[リリース受け入れ表](docs/development/2026-09-11-release-readiness.ja.md)を参照してください。

## アンインストール

```bash
./scripts/uninstall.sh
```

サービスとメニューを停止し、このプロジェクトのアプリ、LaunchAgent、CLI ショートカットをゴミ箱へ移して状態スナップショットを消去します。設定、ログ、ソース、BetterDisplay、仮想画面は保持します。`./scripts/uninstall.sh --purge` は設定（使用済みの `/tmp/PadPilot/config.json` 代替設定を含む）とログもゴミ箱へ移し、復元可能です。

## ドキュメントと貢献

- [インストールガイド](docs/INSTALLATION.ja.md)
- [トラブルシューティング・FAQ](docs/TROUBLESHOOTING.ja.md)
- [アーキテクチャ](docs/ARCHITECTURE.ja.md)
- [文書一覧と言語版](docs/README.ja.md)
- [開発記録](docs/development/README.ja.md) — 保守用の履歴であり、導入手順ではありません
- [変更履歴](CHANGELOG.md)
- [貢献ガイド](CONTRIBUTING.md)と[セキュリティ方針](SECURITY.md)

README と `docs/` 内の文書は繁体字中国語、英語、日本語で読めます。問題報告、翻訳改善、互換性情報、Pull Request を歓迎します。コード変更後は `python3 -m unittest discover -s tests -v` を実行し、GUI 変更時は貢献ガイドのレイアウト確認も行ってください。自動テストは実際のコールドブートや抜き差し検証の代わりにはなりません。

## ライセンスと謝辞

[MIT License](LICENSE)。Copyright (c) 2026 kcayut.

画面制御機能を提供する [BetterDisplay](https://github.com/waydabber/BetterDisplay) に感謝します。PadPilot は独立したプロジェクトであり、Apple や BetterDisplay との提携・公式サポートを示すものではありません。
