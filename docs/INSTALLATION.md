# PadPilot 安裝指南

目前架構是 **Swift／AppKit 原生選單列＋Python 核心＋Tk 設定視窗**，不需要 SwiftBar。沒有 pip 或 Swift 套件依賴。

## 準備環境

- macOS 14+，目前以 Apple Silicon 為主要驗證環境。
- Python 3.10+，且同一個 Python 能匯入 `tkinter`；安裝器不代裝 Python／Tk。
- Apple Command Line Tools，供本機編譯 App；完整 Xcode 不是必要條件。
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) 與可用的 CLI 控制能力。授權條件請以 BetterDisplay 說明為準。
- 支援 Sidecar 的 iPad，先確認 macOS「螢幕鏡像輸出」可以手動連線。

```bash
xcode-select --install
python3 --version
python3 -c "import tkinter"
xcrun --find swiftc
```

若缺少 Tk，請為正在使用的 Python 安裝對應 Tk 支援，不要混用不同 Python 的套件。Sidecar 需要使用者已登入；FileVault 登入前無法由 PadPilot 接管。參閱[疑難排解](TROUBLESHOOTING.md#filevault)。

## 安裝或從舊版升級

在專案目錄執行：

```bash
./scripts/install.sh
# 僅自動同意透過 Homebrew 安裝缺少的 BetterDisplay：
./scripts/install.sh --yes
```

安裝器會：

1. 檢查 Python／Tk、Swift 編譯器及 BetterDisplay。
2. 編譯並本機簽署 App，安裝至 `~/Applications/PadPilot.app`。
3. 透過既有 CLI 停止舊服務，關閉舊原生選單，保留設定與配對。
4. 將指向此專案的舊 PadPilot SwiftBar 外掛連結移到垃圾桶。檢查預設及已儲存的自訂外掛目錄；自行複製或修改的外掛只提示，不擅自刪除。SwiftBar 與其他外掛都保留。
5. 按原本登入啟動偏好更新 LaunchAgent，再啟動 Python 服務與原生選單。首次安裝預設開啟登入啟動。
6. 若 `~/bin` 存在且名稱未被占用，建立 CLI 快捷連結。

App 記錄這次使用的 Python 及專案路徑。**請保留該 Python 環境與專案資料夾**；這版不是內含 Python 的獨立發行包。搬移後需重新安裝；安裝器會拒絕覆蓋屬於另一個專案路徑的同名 App／LaunchAgent，請先在原路徑解除安裝再搬移。正式公開的 Developer ID 簽署、公證與自動更新尚未包含。

## 開啟與配對

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

選單「設定與配對」開啟原本的 Tk 視窗，可搜尋、儲存配對並指定控制目標；刪除配對仍有確認步驟。也能使用：

```bash
./bin/padpilot-cli pair --interactive
./bin/padpilot-cli gui
./bin/padpilot-cli gui diagnostics
```

設定儲存於 `~/Library/Application Support/PadPilot/config.json`，既有配對不需重建。

## 日常操作與開發

```bash
./bin/padpilot-cli start            # 啟動服務並顯示選單
./bin/padpilot-cli stop             # 停止服務、保留選單
./bin/padpilot-cli exit             # 停止服務並關閉選單
./bin/padpilot-cli autostart status
./bin/padpilot-cli autostart toggle
python3 scripts/build_app.py        # 僅建置 build/PadPilot.app，不安裝或啟動
./bin/padpilot-cli menu-json        # 只讀原生選單模型，不掃描硬體
```

單元測試包含原生選單三語資料解碼、子選單、勾選／停用狀態及命令白名單：

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
```

## 解除安裝

```bash
./scripts/uninstall.sh
./scripts/uninstall.sh --purge
```

標準解除安裝停止本專案服務與選單，將 App、LaunchAgent 和屬於此專案的 CLI 連結移到垃圾桶，清除狀態快照。設定與日誌保留；`--purge` 另將兩者移到垃圾桶，可復原。原始碼、BetterDisplay、SwiftBar、其他外掛及虛擬螢幕均不刪除。
