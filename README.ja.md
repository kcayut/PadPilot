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
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg" alt="License: PolyForm Noncommercial 1.0.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-lightgrey.svg" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/status-early%20preview-orange.svg" alt="Status: Early Preview">
</p>

PadPilot は **Apple Sidecar と BetterDisplay** を使う macOS 向けディスプレイ自動化ツールです。主に Mac mini + iPad の利用を想定しています。物理モニターがない場合は指定した iPad への接続とメイン画面への設定を試み、モニターを接続した場合は動作モードと手動指定に従って画面の役割を調整します。

メニューバー、設定画面、CLI から接続やペアリングを管理し、現在の状態と切り替え理由を確認できます。

> [!IMPORTANT]
> **早期プレビュー版です。** 物理モニター、または利用可能なリモート接続を確保した状態で試してください。
> PadPilot はユーザーのログイン後に動作し、**FileVault のロック解除画面やログイン前の画面を iPad に表示することはできません。** インストールのために FileVault を無効にする必要はありません。モニターなしのコールドブートや各種ハードウェア構成は、実機検証が必要です。

GUI の使用説明、トラブルシューティング、診断ヘルプは、使用中の版に対応する GitHub 上の文書を表示言語に合わせて開きます。非公開リポジトリの文書にはアクセス権のある GitHub アカウントが必要です。文書リンクは版に固定され、新版の公開で内容は変わりません。

## 特長

- **物理モニター優先：** 自動モードでは物理モニターがあれば Sidecar 接続を開始しません。接続済み iPad はサブ画面として維持できます。
- **iPad のメイン・サブ画面操作：** 接続、切断、再接続、役割変更に対応します。複数のペアリングを保存し、1 台を操作対象に選べます。
- **仮想画面による代替：** BetterDisplay の仮想ディスプレイでデスクトップを維持し、iPad への切り替え後も代替画面を保持します。
- **USB イベント：** 接続・取り外しでバックグラウンド評価を起動し、探索期間、定期確認、デバウンス、失敗時のクールダウンを組み合わせます。
- **判断の可視化：** 設定画面でデバイス検索、ペアリング、状態、診断、ログを確認できます。メニューはサービスが作成する状態スナップショットを読み取ります。
- **3 言語の UI：** 繁体字中国語、英語、日本語。コアは Python 標準ライブラリを使用し、追加の pip パッケージは不要です。

## 動作の概要

新規インストールは `manual_only` が既定で、「起動時にモニターがなければ iPad に自動接続」が有効です。ログイン後、1 回 30 秒で最大 3 回（合計最大 90 秒）探索し、見つからなければ停止します。対象が見つかり物理モニターがなければ、接続を 1 サイクル試みます。その後はメニューまたはグローバルショートカットで操作します。`automatic` に切り替え、有効な手動指定がない場合：

| 現在の構成 | 想定する動作 |
| --- | --- |
| 物理モニターあり | 物理モニターをメインにし、iPad へ新規接続しません。接続済み iPad はサブ画面として維持します。 |
| 物理モニターなし、利用可能な iPad 対象あり | デバウンス後に Sidecar 接続を試み、iPad をメイン画面にします。 |
| 物理モニターも iPad 対象もなし | 設定済みの BetterDisplay 仮想画面を代替として使います。 |

`prefer_ipad` は iPad のメイン画面を優先します。手動指定は現在のハードウェア構成内で優先され、モード変更、リセット、構成変更後に再評価します。

既定値は、物理モニター切断のデバウンス **4 秒**、Sidecar 接続試行は最大 **3 回**、再試行間隔 **3 秒**、失敗後のクールダウン **30 秒**です。接続完了時間の保証ではありません。

## 必要な環境

| 項目 | 条件 |
| --- | --- |
| Mac | Apple Silicon（arm64）、macOS 14 以降。Intel Mac は非対応です。実機構成ごとの検証が必要です。 |
| iPad | Sidecar 対応機種で、Mac と同じ Apple Account を使用し、2 ファクタ認証が有効なこと。 |
| Python | リリースには CPython を同梱。外部 Python は Apple Silicon 用 3.10 以降が必要です。 |
| [BetterDisplay](https://github.com/waydabber/BetterDisplay) | Sidecar と画面を制御します。macOS と互換性のある版を使用し、CLI が動作することを確認してください。CLI 制御には提供元の条件に従った Pro または有効な試用が必要です。 |
| Apple Command Line Tools | ソースビルドとリリース作成時のみ必要です。リリースの利用には不要です。 |
| 接続 | 初回はデータ転送対応 USB ケーブルを推奨し、iPad で Mac を信頼します。ワイヤレス Sidecar には Wi-Fi、Bluetooth、Handoff も必要です。 |

対応機種と接続条件は [Apple の Sidecar ガイド](https://support.apple.com/en-us/102597)を参照してください。BetterDisplay の機能とライセンスは[提供元の説明](https://github.com/waydabber/BetterDisplay#key-features)に従います。PadPilot のライセンスに第三者ソフトウェアのライセンスは含まれません。

## クイックスタート

### 1. インストール

まず macOS の「画面ミラーリング」で Sidecar を手動利用できることを確認してください。[GitHub Releases](https://github.com/kcayut/PadPilot/releases) から Apple Silicon 用 `.dmg` をダウンロードし、**PadPilot.app を Applications にドラッグ**して、インストールしたアプリを開きます。Swift と CPython を同梱しており、別の Python、Homebrew、Apple のビルドツールは不要です。GUI、CLI、daemon、USB 検出、ログイン時起動は同じコアを使用します。

現在は **ad-hoc 署名のみの開発プレビューで、Developer ID 署名と Apple の公証はありません**。開発元や悪意あるソフトウェアを確認できないという警告が出る場合があります。取得元を確認してから、[Apple の手順](https://support.apple.com/en-us/102445)に従い「システム設定 → プライバシーとセキュリティ → このまま開く」を使用してください。破損の警告では再ダウンロードして `SHA256SUMS` を確認し、すべてを誤警告と決めつけないでください。

Python を選びたい場合は[リリース用インストーラー](https://raw.githubusercontent.com/kcayut/PadPilot/main/scripts/install_release.sh)を保存して実行するか、ソースのフォルダーで次を実行します。

```bash
bash scripts/install.sh --release
```

公開済みの最新リリース（プレリリースを含む）を取得し、同梱 CPython または自分の Apple Silicon Python 3.10 以降を選べます。`--tag v0.1.0-dev.1`、`--bundled`、`--python /absolute/path/python3` も指定できます。管理者が tag を push してリリースを公開するまでは明確に停止します。ダウンロードを検証して設定を保持したままインストールし、完了後にアプリを開きます。

BetterDisplay **アプリのインストールと起動が必要**で、`betterdisplaycli` だけでは不十分です。独立した CLI は任意です。アプリ内蔵の制御機能を使い、Applications、ユーザーの Applications、macOS に登録された任意の場所を検出します。手動指定のパスが優先されます。

導入、更新、Python の切り替え前に設定を保存して PadPilot を終了してください。設定とペアリングはアプリ外に保存します。ソース版からの移行や導入先の変更では旧版を先に削除し、設定を残します。詳細は[インストールガイド](docs/INSTALLATION.ja.md)を参照してください。開発者は引き続き `bash scripts/install.sh` でローカルビルドできますが、この場合はソースと選択した Python を保持する必要があります。

以下の CLI 例は `/Applications/PadPilot.app` を使用します。別の場所に導入した場合は実際のパスに置き換えてください。

### 2. iPad を指定

対話型ウィザードで操作対象を選びます。

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" pair --interactive
```

設定画面でもデバイス検索、ペアリング保存、操作対象の選択ができます。

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" gui
```

PadPilot のペアリングはデバイスの対応関係を記録するもので、Apple Account や「このコンピュータを信頼」の設定に代わるものではありません。複数台を保存できますが、同時に管理する操作対象は 1 台です。

### 3. 代替画面と状態を確認

モニターなしで使う場合、BetterDisplay に `PadPilotVirtual` という仮想画面があるか、設定画面で既存の仮想画面を選んでください。自動作成に対応しないバージョンでは、BetterDisplay で一度手動作成します。

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" status
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" open-log
```

`open-log` は状態・診断画面を開き、`open-log --raw` は生ログを開きます。リモート復旧が必要なら Screen Sharing/VNC または SSH を事前に設定してください。PadPilot はリモートアクセスを有効にせず、SSH 自体は仮想ディスプレイを必要としません。

`status` はサービスからの応答有無も表示します。無応答時の保存済みスナップショットは現在の状態を保証しません。`status --json` には `daemon_responding` とバージョンが含まれ、スナップショットがなければ画面状態は不明のままです。

## USB イベントと自動検出

メニューの設定・ペアリング → 動作と環境設定 → 詳細設定 → USB と iPad の自動検出で設定します。

- **USB イベントによる評価：** 既定で有効です。IOKit 通知で評価を起動し、30 秒ごとの定期確認も残します。通常の起動時と USB イベント後は最大 30 秒、2 秒間隔で探索します。手動モードで起動時接続を有効にすると、起動時の探索は最大 3 回まで続きます。通知登録に失敗すると診断に表示し、定期確認を継続します。
- **iPad の自動検出：** 既定で有効です。Sidecar UUID を持つ指定済みペアリングを優先し、なければ単一の USB iPad と Sidecar 候補から推定します。保存済みの対応関係を優先し、照会失敗、候補不足、曖昧さがある場合は接続しません。
- **複数台の環境では明示的なペアリングを推奨：** 単一候補は推定にすぎず、USB と Sidecar が同じ機器である証明ではありません。周囲に他の iPad がある場合は自動検出を無効にして対象を指定してください。推定で保存済みペアリングを追加・変更しません。
- **有線と無線：** 指定済みペアリングは USB を外しても Sidecar の利用可否に応じて処理できます。USB だけで推定した未ペアリング対象では、取り外し後に無線接続を新規開始しません。

今回の対象は設定画面とメニューに表示されます。両スイッチは即時反映され、保存済みの無効設定は維持されます。

## メニューバーと表示言語

メニューバーには **18 × 18 pt、Retina 対応の単色アイコン**を使い、macOS のライト・ダーク表示に合わせます。ポインターを合わせると PadPilot の名前、メニューを開くとメイン画面、動作モード、デバイス、診断が表示されます。

<p align="center">
  <img src="assets/menu-icons/preview.png" width="630" alt="PadPilot メニューアイコン：Sidecar、物理画面、仮想画面、手動のみ、サービス停止、警告、処理中">
</p>

順に Sidecar、物理画面、仮想画面、手動のみ、サービス停止、警告、処理中を表します。指のアイコン（`manual.png`）はバックグラウンドサービスが「手動のみ」モードで動作中であることを示し、iPad が接続されていても表示されます。一時停止アイコン（`paused.png`）はバックグラウンドサービスの停止を示します。エラー時は警告を優先し、設定の適用中や画面の切り替え中は処理中アイコンを表示して、完了後に対応する状態アイコンへ戻ります。画像は同梱されており、デザイン変更時には `swift scripts/build_menu_icons.swift` で再生成できます。

初回設定では macOS の言語から選択し、中国語・日本語以外では英語を使用します。メニューの Language、GUI の言語選択、`set-language` で変更できます。GUI の使い方、トラブルシューティング、診断ヘルプは選択言語のローカル文書を開きます。デバイス名、識別子、生ログは原文を維持します。

## よく使うコマンド

どのフォルダーからでも実行できます。`~/bin` が PATH にあれば `padpilot-cli` だけでも実行できます。導入・更新・開発用スクリプトはソースフォルダーで実行してください。

```bash
# 状態と設定
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" status --json
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" gui
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-language ja        # zh-Hant または en も使用可能

# 動作モード：いずれかを選択
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-mode automatic
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-mode manual_only
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" set-mode prefer_ipad

# 手動操作：必要に応じて実行
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action use_ipad_secondary
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action use_ipad_main
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action disconnect_ipad
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action reconnect_sidecar
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action refresh
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" action reset           # 一時指定とクールダウンを解除

# サービスとログイン時起動
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" stop
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" start
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" exit                  # サービスを停止し、メニューを閉じる
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" autostart status
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" autostart toggle

# バージョンとヘルプ
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --version
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --help
```

リリースの更新：PadPilot を終了し、同じ場所のアプリを新版に置き換えるか、リリース用スクリプトを再実行します。設定を保持し、スクリプトでは Python を選択します。場所を変更する場合は旧版を先に削除して設定を残します。以下の再ビルド手順はソース版のみが対象です。

更新前に旧ソースをバックアップし、設定を保存して画面を閉じます。更新後は `./scripts/install.sh --check`、`./scripts/install.sh`、`"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" status` を再実行し、アプリも再ビルドします。GUI の「このアプリについて」、CLI `--version`、アプリは同じバージョン定義を使います。同ページには GitHub と寄付欄もあり、受取先 URL が設定されるまで寄付ボタンは無効です。設定は保持され、旧アプリはゴミ箱にありますが、アプリだけを戻しても参照するソースは戻りません。

## 制限とトラブルシューティング

- **Sidecar は前提条件：** 非対応機種を対応させるものではなく、Universal Control のキーボード・ポインター移動も制御しません。
- **接続時間は環境に依存：** USB 通知、4 秒の待機、コマンド成功は画面表示完了を意味しません。クールダウン中は代替画面を優先します。
- **モニターなしの環境は要検証：** コールドブート、スリープ復帰、ハブ、複数デバイス構成は網羅的に検証していません。ログイン前の iPad 表示には対応せず、FileVault 無効化・自動ログインは動作を保証する手順ではありません。
- **他の画面制御ツールとの競合：** 別ツールがメイン画面や Sidecar を繰り返し変更する場合、`manual_only` にして判断理由とログを確認してください。

設定と状態は通常 `~/Library/Application Support/PadPilot/`、ログは `~/Library/Logs/PadPilot/` にあります。問題報告にはバージョン、接続方式、再現手順、関連ログを添え、シリアル番号、UUID、アカウント、個人のパスは伏せてください。

専用ディレクトリは `0700`、設定・状態・socket・ログは `0600` です。他ユーザー所有やリンクされた状態パスを拒否します。新しい IPC ログにペアリング payload は記録しませんが、過去のログは自動消去しません。検証済み環境と `unknown` の実機項目は[リリース受け入れ表（繁体字中国語）](docs/development/2026-09-11-release-readiness.md)を参照してください。

## アンインストール

リリース版では設定を保存して画面を閉じ、次を実行します。アプリとログイン時起動の項目をゴミ箱へ移し、設定・ペアリング・ログは保持します。`--purge` を追加するとこれらもゴミ箱へ移します。

```bash
"/Applications/PadPilot.app/Contents/Resources/padpilot-cli" --bundled-cli uninstall --yes
```

**ソース版**：ターミナルに貼り付けて、削除する項目を選択します。

```bash
/bin/bash "$HOME/Applications/PadPilot-source/scripts/uninstall.sh"
```

削除内容を確認してから、このプロジェクトのサービスとメニューを停止し、アプリ、LaunchAgent、CLI 入口をゴミ箱へ移します。設定・ペアリング、ログ、ダウンロードしたソース、インストーラーが新規導入した第三者の依存関係は個別に選択し、既定では保持します。既存の Python、BetterDisplay、Homebrew、Apple のツール、仮想ディスプレイは一緒に削除しません。

非対話で PadPilot 本体だけを削除するには `--yes`、設定とログも削除するには `--yes --purge` を追加します。ソースと第三者の依存関係は保持します。手動で取得したソースでは、そのフォルダーで `./scripts/uninstall.sh` を実行してください。[削除オプション](docs/INSTALLATION.ja.md#アンインストール)を参照してください。

## ドキュメントと貢献

- [インストールガイド](docs/INSTALLATION.ja.md)
- [トラブルシューティング・FAQ](docs/TROUBLESHOOTING.ja.md)
- [アーキテクチャ](docs/ARCHITECTURE.ja.md)
- [文書一覧と言語版](docs/README.ja.md)
- [開発記録（繁体字中国語）](docs/development/README.md) — 保守用の履歴
- [変更履歴](CHANGELOG.md)
- [貢献ガイド](CONTRIBUTING.md)と[セキュリティ方針](SECURITY.md)

README と `docs/` 内のユーザー向けガイドは繁体字中国語、英語、日本語で読めます。開発記録は繁体字中国語のみで管理します。問題報告、翻訳改善、互換性情報、Pull Request を歓迎します。コード変更後は `python3 -m unittest discover -s tests -v` を実行し、GUI 変更時は貢献ガイドのレイアウト確認も行ってください。自動テストは実際のコールドブートや抜き差し検証の代わりにはなりません。

## ライセンスと謝辞

[PolyForm Noncommercial License 1.0.0](LICENSE) を採用しています。作者：**kcayut**。Copyright (c) 2026 kcayut.

- 非商用目的での使用、変更、再配布を許可します。ライセンスの許可範囲外の商用利用には、作者から別途許諾を得る必要があります。
- ソースコード、実行ファイル、変更版を配布する際は、ライセンス本文または公式 URL を添え、[NOTICE](NOTICE) の `Required Notice:` で始まる作者・プロジェクト出典の表示をすべて保持してください。ビルドした App には `LICENSE` と `NOTICE` が同梱されます。
- 慈善団体、教育機関、公的研究機関、公共安全・保健機関、環境保護団体、政府機関による使用も、資金源にかかわらず明示的に許可されています。詳細はライセンス原文に従います。

ソースを入手できる非商用ライセンスであり、OSI の定義によるオープンソースライセンスではありません。この変更は本ライセンスを添えて提供する版に適用され、以前に MIT で取得した版の権利を取り消しません。

画面制御機能を提供する [BetterDisplay](https://github.com/waydabber/BetterDisplay) に感謝します。PadPilot は独立したプロジェクトであり、Apple や BetterDisplay との提携・公式サポートを示すものではありません。
