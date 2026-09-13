# PadPilot トラブルシューティング・FAQ

[繁體中文](TROUBLESHOOTING.md) | [English](TROUBLESHOOTING.en.md) | **日本語** · [ドキュメント](README.ja.md)

リリース版の Gatekeeper 警告、Python の切り替え・復旧、ソース版からの移行は[ビルド済み版の導入手順](INSTALLATION.ja.md)を参照してください。BetterDisplay アプリの導入と起動は必要で、独立した CLI は任意です。

macOS 上での状態警告、デバイス認識、接続エラーと対処方法をまとめています。

## 目次

- [1. FileVault とモニターなしのコールドブート](#filevault)
- [2. Sidecar セッションの前提条件](#sidecar-session)
- [3. BetterDisplay の権限と CLI](#betterdisplay)
- [4. Generic Display のプレースホルダー](#generic-display)
- [5. 切断・再試行・クールダウン](#cooldown)
- [6. ログイン時の起動](#autostart)
- [7. ログの収集](#logs)
- [8. 事前確認・危険なパス・応答確認の失敗](#safe-startup)

<a id="filevault"></a>
## 1. FileVault とモニターなしのコールドブート

> [!WARNING]
> PadPilot は FileVault のロック解除画面やログイン前の画面を iPad に表示できません。

**症状：** Mac の電源投入・再起動後、iPad が真っ暗でログイン画面が表示されません。

**原因：** PadPilot の LaunchAgent はユーザーのログイン後に起動し、そのセッション内の Sidecar を使用します。FileVault の解除とログイン前の画面は対象外です。ログイン時起動を有効にしても、この制限は変わりません。

**対処方法：**

1. 物理モニターでロック解除とログインを行い、Sidecar の手動接続を確認します。
2. ログイン後に `./bin/padpilot-cli status` でサービスの応答を確認してから、iPad への切り替えを試します。
3. モニターなしで使う前に、自分の環境でコールドブートと復旧手順を検証してください。ハードウェアの組み合わせごとに確認が必要です。

**インストールのために FileVault を無効化したり、自動ログインを有効化したりする必要はありません。** これらはデータとアカウントの安全性に関わる設定であり、Sidecar が数秒で接続する保証にもなりません。検査を通すためにシステムの安全性を下げないでください。

この2項目は、起動後に画面へ自動接続するための条件を確認します。自動ログインは有効なら緑色の「合格」、無効なら赤色の「不合格」です。FileVault は無効なら合格、有効なら不合格です。未確認または不明な場合は橙色で表示します。状態の読み取りのみを行い、設定の変更やパスワードの読み取りは行いません。合格しても Sidecar の接続を保証するものではありません。

<a id="sidecar-session"></a>
## 2. Sidecar セッションの前提条件

**症状：** USB 接続の iPad は見つかりますが、Sidecar 接続が繰り返しタイムアウト・失敗します。

確認項目：

1. Mac と iPad で同じ Apple Account を使っていること。
2. そのアカウントで 2 ファクタ認証が有効なこと。
3. USB 接続ではデータ転送対応ケーブルを使用し、ロック解除した iPad で「このコンピュータを信頼」を承認すること。
4. ワイヤレス Sidecar では Wi-Fi、Bluetooth、Handoff が必要です。対応機種と有線・無線の条件は [Apple の Sidecar ガイド](https://support.apple.com/en-us/102597)を確認してください。

<a id="betterdisplay"></a>
## 3. BetterDisplay の権限と CLI

**症状：** 診断で BetterDisplay の制御インターフェースが利用できない、または `betterdisplaycli` が見つからないと表示されます。

PadPilot は CLI を使って画面の役割と仮想ディスプレイを制御します。CLI と必要な権限が利用できなければ制御できません。

1. BetterDisplay.app を開きます。
2. インストール済みバージョンの [BetterDisplay CLI ガイド](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI)を確認します。設定名や場所はバージョンによって異なります。
3. 必要な Pro ライセンスまたは有効な試用期間と、PadPilot に設定した CLI のパスを確認します。
4. 次を実行します。

   ```bash
   betterdisplaycli get -identifiers
   ```

   正常終了し、想定するデバイスが取得できることを確認します。CLI の応答だけでは、Sidecar のペアリングや画面表示の検証にはなりません。
5. macOS がアクセシビリティや画面収録の許可を求めたら、要求元のアプリが BetterDisplay などの想定したものか確認してください。Terminal や他のアプリへ一律に許可しないでください。PadPilot のメニューはスナップショットの読み取りと CLI 呼び出しを行います。

<a id="generic-display"></a>
## 4. Generic Display のプレースホルダー

**症状：** モニターなしの起動時に `Generic Display` または `Generic` が検出され、物理モニターがあると誤判定されます。

一部の環境では実物のモニターがなくても仮の framebuffer が現れます。PadPilot は既知の名前と完全一致したものを除外しますが、これはすべての機種に通用する識別方法ではありません。

実際のモニター名も `Generic` または `Generic Display` の場合、状態を保存し、EDID・識別情報を別途収集して調査に使用してください。

```bash
./bin/padpilot-cli status --json
```

本物の物理モニターを無視リストに追加しないでください。名前による除外を広げるのではなく、識別情報を添えて報告してください。

<a id="cooldown"></a>
## 5. 切断・再試行・クールダウン

**症状：** 自動再試行の停止が表示され、最初の 30 秒間はクールダウンも適用されます。

接続試行は最大 3 回、間隔は 3 秒です。上限に達すると一度だけ通知し、物理または仮想の予備画面を維持して自動再試行を停止します。利用できない iPad が Sidecar の一覧に残っていても、30 秒後に再試行を繰り返しません。USB 通知と iPad 自動検出は有効のまま使えます。

1. 必要に応じて iPad を起こし、ロックを解除します。
2. ケーブルや接続部分を確認します。対象 iPad の USB または Sidecar 検出が「なし」から「あり」に変わると、残りのクールダウン後に回数制限付きの試行を再開します。画面を起こしても検出状態が変わらない場合は「再接続」を選びます。通常の USB 通知、更新、物理モニターの接続変更では停止を解除しません。
3. 原因を解消し、一時的な手動指定とクールダウンを解除したい場合に実行します。

   ```bash
   ./bin/padpilot-cli action reset
   ```

サービスが状態を再評価します。手動で接続する場合は「再接続」を選びます。コマンドの受付成功は接続完了を意味しません。

<a id="autostart"></a>
## 6. ログイン時の起動

**症状：** 再起動してログインしても、メニューが表示されずサービスも動作しません。

1. 起動設定とサービスの状態を確認します。

   ```bash
   ./bin/padpilot-cli autostart status
   ./bin/padpilot-cli status
   ```

2. 必要ならログイン時起動を有効にします。

   ```bash
   ./bin/padpilot-cli autostart enable
   ```

3. plist は `PadPilot.app/Contents/Library/LaunchAgents/com.padpilot.daemon.plist` に同梱され、`~/Library/LaunchAgents` には作成されません。`requiresApproval` の場合は「システム設定 → 一般 → ログイン項目」で PadPilot を許可してください。開発版の古い LaunchAgent は手動で停止・削除してください。この版では移行しません。

<a id="logs"></a>
## 7. ログの収集

解決しない場合は再現手順と関連ログをまとめてください。GitHub リポジトリは非公開のため、Issue の投稿にはアクセス権が必要です。

```bash
# 状態と診断画面を開く
./bin/padpilot-cli open-log

# ログファイルを読む
tail -n 50 ~/Library/Logs/PadPilot/padpilot.log
cat ~/Library/Logs/PadPilot/launchd.stderr.log
```

共有前に個人のパスや機密情報を確認し、伏せてください。

<a id="safe-startup"></a>
## 8. 事前確認・危険なパス・応答確認の失敗

- `FAIL: BetterDisplay CLI`：アプリのインストールだけでは CLI の動作は保証されません。CLI 機能と保存された実行パスを確認し、`./scripts/install.sh --check` を再実行します。help 成功はライセンスや実機検証の証拠ではありません。
- 設定画面が開かない：ソース更新後に `./scripts/install.sh` を再実行して、現在のバージョンに対応するアプリをビルドしてください。
- `Refusing unsafe state directory/file`：操作を止め、指定パスの所有者、シンボリックリンク、ハードリンクを確認します。`/tmp` や他人のディレクトリを再帰的に権限変更・削除・取得しないでください。自分のデータだと確認したうえでバックアップし、所有者が整理します。
- `Login service belongs to another ...`：同名アプリ・サービスが別のチェックアウトに属しています。元のソースの場所でアンインストーラーを使い、名前に padpilot を含む全プロセスを一括終了しないでください。
- `Daemon handshake failed`：このプロジェクトのサービス応答を確認できておらず、インストール成功ではありません。`~/Library/Logs/PadPilot/launchd.stderr.log` と `padpilot.log` を確認し、パス・権限・BetterDisplay の問題を解消して再試行します。`Rollback incomplete` もある場合は以前の状態の復元も未確認です。記録を保存し、連続した再インストールは避けてください。

新しい IPC ログにはコマンド名だけを残しますが、過去のログ、診断、実際のエラーにはデバイス情報が含まれることがあります。共有前にシリアル番号、UUID、アカウント、個人のパスを伏せてください。
