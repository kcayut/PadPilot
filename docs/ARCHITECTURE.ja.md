# PadPilot のアーキテクチャと設計

[繁體中文](ARCHITECTURE.md) | [English](ARCHITECTURE.en.md) | **日本語** · [ドキュメント](README.ja.md)

PadPilot は、モニターなしの Mac mini + iPad 環境を想定した、規則に基づくディスプレイ状態管理システムです。

## 設計原則

1. **物理モニター優先：** 自動モードで有効な手動指定がない場合、物理モニターを優先し、Sidecar 接続を開始しません。他のモードはそれぞれの方針で判断し、即時切り替えは保証しません。
2. **手動操作優先：** iPad をサブ画面にするなどの指定は、現在のハードウェア構成内で優先されます。モード変更、リセット、構成変更で再評価します。
3. **状態の可視化：** 判断と観測した状態をアトミックに保存します。メニューと GUI はスナップショットを読み、メニュー読み取り時に重い検索を行いません。
4. **失敗からの復旧：** デバウンス、再試行回数の制限、クールダウンで連続接続要求を抑えます。外部サービスが常に正常に動作する保証ではありません。

## 構成

```text
Swift / AppKit + SwiftUI PadPilot.app
  ├─ SwiftUI settings → shared CLI/config transactions
  ├─ menu-json → core/menu.py → config.json + atomic status.json + daemon liveness
  └─ CLI argument arrays → padpilot-cli → Unix socket → padpilotd
                                                       ├─ Detector / IOKit / CoreGraphics
                                                       └─ StateEngine → BetterDisplay CLI
```

メニューは 1 秒ごとにスナップショットの変更を確認し、変更がある場合、または前回読み取りから 5 秒経過した場合に `menu-json` を呼びます。メニューの読み取りではハードウェアを検索しません。CLI 子プロセスは AppKit のメインスレッドをブロックせず、メニュー展開中は再構築せずに閉じた後で更新します。操作は引数配列と許可リストを使い、デバイス名を shell コマンドへ埋め込みません。ログイン後に LaunchAgent が Python を起動し、ネイティブアプリを開きます。ロックでメニューの重複起動を防ぎます。サービス停止ではメニューを残し、終了操作では両方を閉じます。

## 主な仕組み

### 1. ハードウェア構成の世代管理

物理モニターがない状態で iPad をサブ画面に指定しても、定期評価が直後にメインへ戻してはいけません。手動指定を構成の世代に関連付け、通常の評価では維持します。構成変更、モード変更、リセットで無効になります。物理モニターがある場合、iPad 接続の消失によってメイン・サブ指定が解除されることもあります。

### 2. 状態遷移の直列化

USB、画面イベント、30 秒ごとの watchdog が同時に到着しても、共通ロックで評価と設定トランザクションを直列化し、重複した通知をまとめます。PadPilot 自身の競合を防ぐ仕組みであり、他のアプリによる同時制御は起こり得ます。

### 3. デバウンスとクールダウン

- 物理モニターが消失すると 4 秒の待機を開始し、その間に復帰すれば切り替えを中止します。一時的な信号変化による不要な iPad 起動を抑えますが、すべての画面障害を防ぐものではありません。
- Sidecar 接続は最大 3 回、間隔 3 秒で試行し、失敗後は 30 秒のクールダウンに入ります。メニューには警告を表示します。

### 4. 仮想ディスプレイによる代替

物理モニターがない場合は、設定済みの BetterDisplay 仮想画面（通常は `PadPilotVirtual`）でデスクトップを維持し、iPad がメインになった後も保持します。Screen Sharing/VNC や SSH による復旧は事前に自分で設定してください。PadPilot はリモートアクセスを有効化せず、SSH 自体は仮想ディスプレイを必要としません。

### 5. アトミックな状態保存

- daemon は実際の状態、目標状態、判断理由を一時ファイルへ書き、`os.replace` で `~/Library/Application Support/PadPilot/runtime/status.json` をアトミックに置き換えます。
- `core/menu.py` と GUI が読み取ります。設定リビジョンの不一致や古いデータでは関連操作を無効にし、不明な状態を保持します。メニューの更新操作だけが CLI 経由でハードウェア状態の更新を要求します。

## USB イベントと一時的な操作対象

`core/usb_events.py` は ctypes で IOKit の `IOUSBHostDevice` first-match/terminated 通知を登録します。コールバックは iterator の内容を処理・解放した後、起動イベントを設定するだけです。daemon の共通ループが通知、起動時探索、watchdog を処理し、既存の `StateEngine.evaluate` を呼びます。ネイティブコールバック内で BetterDisplay を実行しません。停止時は RunLoop source、iterator、notification port を解放します。登録失敗時も watchdog は継続し、診断を出します。

`usb_event_wakeup` と `auto_detect_ipad` の既定値は true です。既存の設定トランザクションで保存・即時反映し、最初は折りたたまれた詳細設定内に両スイッチを配置します。保存済みの無効設定は保持します。設定変更と状態遷移は評価ロックを共有し、処理中に対象が置き換わることを防ぎます。

自動検出は Sidecar UUID を持つ明示的なペアリングを優先します。その場合 USB 接続は必須ではなく、候補一覧から一時的に消えても別の対象へ変えません。有効な指定がない場合だけ、単一の USB 候補から推定します。結果は `ActualState.resolved_ipad` に置き、接続、切断、再接続、メイン画面操作で共有します。USB シリアルと Sidecar UUID は構成の識別に含め、デバイス変更時に手動指定を無効化します。

推定では Config やペアリング一覧を書き換えません。照会が不完全、または候補が曖昧なら接続を開始しません。保存済み USB/Sidecar 対応を優先し、なければ単一候補を推定しますが、同一機器である証明にはなりません。GUI とメニューは今回の対象を表示し、指定済みペアリングの操作は送信前に再確認します。他のペアリングは先に操作対象へ設定する必要があります。

通知 API の参照先：[Apple IOServiceAddMatchingNotification](https://developer.apple.com/documentation/iokit/1514362-ioserviceaddmatchingnotification) とローカル macOS SDK の `IOKitLib.h`。即時なのは通知と評価の起動であり、Sidecar 接続完了は探索、実行中の操作、再試行、デバウンスにも左右されます。

## 設定の整合性と不明な状態

主設定・状態ファイルと `/tmp/PadPilot` の代替先は、最終書き込み時刻による選択規則を共用し、読み取り前に所有者とファイル種別を確認します。無効な設定では既定値を適用せず起動を拒否し、GUI は保存を無効化して原本を保持します。GUI 取引は `expected_revision` を送り、名前の下書きは編集開始時の版を保持します。競合後は再確認して保存します。

検出器は確認済みの Sidecar session UUID と display UUID の対応を実行中だけ保持します。探索候補が消失しても対応を使い、対象変更または切断確認時に消去します。`ActualState.sidecar_display_id` をメイン画面選択と充足判定で共用します。接続中でも画面を識別できない場合は不明として現在の表示を維持します。同じ観測内で後の identifiers 照会が成功しても、先の失敗は消去しません。
