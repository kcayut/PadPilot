# PadPilot 安裝指南

目前架構是 **Swift／AppKit 原生選單列＋Python 核心＋Tk 設定視窗**，不需要 SwiftBar。沒有 pip 或 Swift 套件依賴。

## 準備環境

- macOS 14+，目前以 Apple Silicon 為主要驗證環境。
- Python 3.10+；設定視窗另外需要同一個 Python 能匯入 `tkinter`。安裝器不代裝 Python／Tk；沒有 pip 套件需要安裝。
- Apple Command Line Tools，供本機編譯 App；完整 Xcode 不是必要條件。
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) 與可用的 CLI 控制能力。授權條件請以 BetterDisplay 說明為準。
- 支援 Sidecar 的 iPad，先確認 macOS「螢幕鏡像輸出」可以手動連線。

```bash
xcode-select --install
python3 --version
python3 -c "import tkinter"
xcrun --find swiftc
```

若缺少 Tk，安裝器會警告，daemon／CLI／原生選單仍可安裝，但設定視窗入口停用。請為正在使用的 Python 安裝對應 Tk 支援，不要混用不同 Python 的套件。Sidecar 需要使用者已登入；FileVault 登入前無法由 PadPilot 接管。參閱[疑難排解](TROUBLESHOOTING.md#filevault)。

## 安裝或從舊版升級

在專案目錄執行：

```bash
./scripts/install.sh --check
./scripts/install.sh
./bin/padpilot-cli status

# 僅自動同意透過 Homebrew 安裝缺少的 BetterDisplay：
./scripts/install.sh --yes
```

`--check` 是不修改系統的預檢：不呼叫 Homebrew、不建立設定或日誌、不編譯、不啟動服務，也不掃描或改動螢幕。必要項目缺失回傳非零結束碼；Tk 缺失僅警告。BetterDisplay CLI 的 help 成功不代表授權或 Sidecar 可用，兩者需另行確認。GitHub 倉庫目前是私人，需有存取權限；也可直接使用現有原始碼資料夾。

安裝器會：

1. 驗證 macOS 14+、Python 3.10+、Tk 是否可用、Swift 編譯器、BetterDisplay app 和 CLI 回應。若 BetterDisplay 缺失可詢問透過 Homebrew 安裝；拒絕、安裝失敗或 CLI 不可用就停止，不印出完成。
2. 編譯並本機簽署 App，安裝至 `~/Applications/PadPilot.app`。
3. 透過既有 CLI 停止舊服務，關閉舊原生選單，保留設定與配對。
4. 將指向此專案的舊 PadPilot SwiftBar 外掛連結移到垃圾桶。檢查預設及已儲存的自訂外掛目錄；自行複製或修改的外掛只提示，不擅自刪除。SwiftBar 與其他外掛都保留。
5. 按原本登入啟動偏好，呼叫共享的 `padpilot-cli autostart enable`，再啟動 Python 服務與原生選單。首次安裝預設開啟登入啟動。必須收到此專案 daemon 的結構化 socket 回應才成功；失敗會嘗試回復原 LaunchAgent 與設定，若回復也失敗則明確報錯，不假裝完成。獨立啟動失敗會終止本次建立的子程序。
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

## 更新與回復

先保留原始碼備份，儲存並關閉設定視窗。更新原始碼後再跑「預檢 → 安裝 → status」三步，原生二進位也會重新編譯。GUI 左上角顯示 `v0.1.0`，與 CLI／App 版本共用 `core.__version__`。

安裝器保留設定，舊 App 移到垃圾桶；它不會自動下載更新、建立 Git tag 或發布。若需降回相容舊版，回復原始碼後重新安裝。App 引用原始碼，僅取回垃圾桶中的 App 不能完整回復程式版本。

## 本機隱私與權限

PadPilot 專用設定、runtime、日誌目錄為 `0700`；設定、狀態、IPC socket 與日誌為 `0600`。拒絕其他使用者擁有的路徑、符號連結與有多個硬連結的狀態檔，包含 `/tmp/PadPilot` 備援路徑。遇到不安全路徑會停止，不自動刪除或接管他人檔案。請見[路徑與啟動失敗排解](TROUBLESHOOTING.md#safe-startup)。

IPC 僅記錄已知命令名稱，不記錄配對 payload。既有日誌仍可能含裝置資訊；匯出前自行遮蔽。解除安裝不會使用廣泛的程序名稱終止指令，也不移除他人的同名 CLI 連結。

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
python3 scripts/check_release.py --gui
```

本機發布檢查另含 Shell、plist、版本一致性、ResourceWarning 與目前原始碼／Git 歷史的隱私模式掃描；輸出在 `build/release-check.json`、`build/privacy-scan.json`，匹配值不寫進掃描報告。若隱私仍待人工檢視，結束碼為 1，即使程式測試全數通過。無桌面工作階段時不要加 `--gui`，GUI 會標為未驗證。這不取代實機測試，詳見[發布驗收表](development/2026-09-11-release-readiness.md)。

## 解除安裝

```bash
./scripts/uninstall.sh
./scripts/uninstall.sh --purge
```

標準解除安裝停止本專案服務與選單，將 App、LaunchAgent 和屬於此專案的 CLI 連結移到垃圾桶，清除狀態快照。設定與日誌保留；`--purge` 另將兩者移到垃圾桶，可復原。原始碼、BetterDisplay、SwiftBar、其他外掛及虛擬螢幕均不刪除。
