<p align="center">
  <img src="assets/padpilot-icon.png" width="160" height="160" alt="PadPilot 圖標：平板中的導航箭頭">
</p>

<h1 align="center">PadPilot</h1>

<p align="center">
  <b>Sidecar display automation for Mac</b><br>
  讓 iPad 接手你的 Mac 螢幕。
</p>

<p align="center">
  <b>繁體中文</b> | <a href="README.en.md">English</a> | <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version: 0.1.0">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-lightgrey.svg" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/status-early%20preview-orange.svg" alt="Status: Early Preview">
</p>

PadPilot 是搭配 **Apple Sidecar 與 BetterDisplay** 使用的 macOS 顯示器自動化工具，主要為 Mac mini + iPad 的使用情境設計。沒有實體螢幕時，它會嘗試連接指定 iPad，並將它設為主螢幕；接回實體螢幕時，則依運作模式與手動選擇調整顯示器角色。

你可以透過選單列、圖形設定視窗或命令列控制連線、管理配對，以及查看目前狀態與切換原因。

> [!IMPORTANT]
> **目前為早期預覽版本。** 請先在保留實體螢幕或可用遠端連線的環境中測試。
> PadPilot 在使用者登入後運作，**無法讓 iPad 顯示 FileVault 解鎖或登入前畫面**。安裝不需要關閉 FileVault；無實體螢幕冷開機與不同硬體組合仍需實機驗證。

## 功能特色

- **實體螢幕優先**：自動模式下，有實體螢幕時不主動建立 Sidecar；已連線的 iPad 可保留為副螢幕。
- **iPad 主／副螢幕控制**：手動連線、斷線、重新連線及切換角色，支援儲存多台配對並指定一台控制目標。
- **虛擬螢幕備援**：透過 BetterDisplay 的虛擬螢幕保留無頭桌面；iPad 接管後仍保留備援顯示器。
- **USB 事件喚醒**：插拔事件喚醒背景評估，搭配探索期、定期檢查、防抖與失敗冷卻。
- **可查看的決策**：設定視窗提供裝置搜尋、配對管理、狀態、診斷與日誌；選單列讀取背景服務產生的狀態快照。
- **三種介面語言**：繁體中文、English、日本語。核心程式使用 Python 標準函式庫，沒有額外 pip 套件需求。

## 如何運作

在預設的 `automatic` 模式、沒有有效手動覆寫時：

| 目前情境 | 預期行為 |
| --- | --- |
| 有實體螢幕 | 使用實體主螢幕；不主動連接 iPad，已連線的 iPad 保留為副螢幕。 |
| 沒有實體螢幕，有可用的 iPad 目標 | 等待防抖後，嘗試連接 Sidecar 並將 iPad 設為主螢幕。 |
| 沒有實體螢幕，也沒有可用的 iPad 目標 | 使用已配置的 BetterDisplay 虛擬螢幕作為備援。 |

另外提供 `manual_only`（暫停自動切換，保留手動控制）與 `prefer_ipad`（優先嘗試使用 iPad 主螢幕）模式。手動選擇在目前硬體拓撲內優先；切換模式、重設或拓撲改變後會重新評估。

預設的實體螢幕斷線防抖為 **4 秒**，Sidecar 連線最多嘗試 **3 次**，重試間隔 **3 秒**，失敗後冷卻 **30 秒**。這些是控制時序，並非連線完成時間的保證。

## 使用需求

| 項目 | 說明 |
| --- | --- |
| Mac | 專案目標為 macOS 14+，主要使用情境是 Apple Silicon Mac mini；其他機型與版本組合尚未全面驗證。 |
| iPad | 支援 Sidecar 的 iPad，與 Mac 登入相同 Apple Account 並啟用雙重認證。 |
| Python | Python 3.10+；圖形設定視窗另外需要此 Python 環境可匯入 `tkinter`。安裝腳本不會安裝 Python／Tk。 |
| [BetterDisplay](https://github.com/waydabber/BetterDisplay) | 提供 Sidecar 與顯示器控制。請選擇相容於 macOS 的版本，並確認 CLI 可用；命令列控制依上游授權需要 Pro 或有效試用。 |
| Apple Command Line Tools | 編譯 Swift／AppKit 原生選單列；首次安裝執行 `xcode-select --install`。 |
| 連線 | 初次設定建議使用可傳輸資料的 USB 線，並在 iPad 上信任 Mac。無線 Sidecar 另需 Wi-Fi、藍牙與 Handoff。 |

裝置相容性及有線／無線條件請參閱 [Apple Sidecar 說明](https://support.apple.com/en-us/102597)。BetterDisplay 的功能與授權以[上游說明](https://github.com/waydabber/BetterDisplay#key-features)為準；PadPilot 的 MIT 授權不包含第三方軟體授權。

## 快速開始

### 1. 安裝

先確認可以在 macOS「螢幕鏡像輸出」中手動使用 Sidecar，再設定 PadPilot。

```bash
# 取得原始碼後，在 PadPilot 專案資料夾執行：
./scripts/install.sh --check
./scripts/install.sh
./bin/padpilot-cli status
```

GitHub 倉庫為 [kcayut/PadPilot](https://github.com/kcayut/PadPilot)，目前是私人倉庫，僅受邀帳號可存取，尚無正式 Release。`--check` 只檢查依賴，不安裝、不寫入使用者設定、不啟動服務或切換螢幕。Tk 缺失是警告：daemon、CLI 與原生選單仍可使用，設定視窗入口會停用；請補上同一個 Python 的 Tk 支援。

安裝腳本會驗證 macOS、Python 版本、Swift 編譯器、BetterDisplay app 及 CLI 回應；若有 Homebrew，可依提示安裝 BetterDisplay，加上 `--yes` 可自動同意。缺少必要依賴或 CLI 檢查失敗會停止。接著編譯並安裝 `~/Applications/PadPilot.app`，保留配對、模式與登入啟動偏好，並**重新啟動背景服務與原生選單**。首次安裝預設啟用使用者登入時啟動；服務握手成功後才回報安裝完成，啟動失敗會嘗試還原舊 App、LaunchAgent 與安裝前的服務執行狀態，回復失敗也會明確報錯。

CLI 可回應不代表 Pro 授權、Sidecar 配對、權限或實際顯示已驗證；仍需完成下方配對與實機確認。

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

App 目前引用本機 Python 與專案路徑，**請保留 Python 環境與專案資料夾**；搬移後需重新安裝。這是本機編譯版本，尚非內含 Python、經公證的獨立發行包。

### 2. 指定 iPad

在專案目錄執行互動式配對，選取要控制的 iPad：

```bash
./bin/padpilot-cli pair --interactive
```

也可開啟圖形設定視窗，搜尋裝置、儲存配對並選定控制目標：

```bash
./bin/padpilot-cli gui
```

PadPilot 配對只記錄裝置對應，不會取代 Apple Account 或「信任這部電腦」設定。雖然可以儲存多台 iPad，目前一次管理一台控制目標。

### 3. 確認備援與狀態

若要使用無實體螢幕情境，請確認 BetterDisplay 中存在名為 `PadPilotVirtual` 的虛擬螢幕，或在 PadPilot 設定中選擇既有的虛擬螢幕。若版本不支援自動建立，請先在 BetterDisplay 中手動建立一次。

```bash
./bin/padpilot-cli status
./bin/padpilot-cli open-log
```

`open-log` 會開啟狀態與診斷視窗；`open-log --raw` 可開啟原始日誌。遠端救援需自行事先設定 Screen Sharing／VNC 或 SSH；PadPilot 不會替你啟用遠端存取，SSH 本身也不依賴虛擬螢幕。

`status` 會另外顯示是否收到服務握手；無回應時顯示的是已儲存快照，不能當成即時狀態。`status --json` 提供 `daemon_responding` 與版本資訊，沒有快照時螢幕狀態仍為未知。

## USB 喚醒與自動偵測

設定位置：**選單列 → 設定與配對 → 運作與偏好 → 進階選項 → USB 與 iPad 自動偵測**。

- **USB 插拔即時喚醒**：預設啟用。使用 IOKit 通知喚醒背景評估，並保留 30 秒定期檢查。啟動與 USB 事件後有最長 30 秒、每 2 秒的探索期；通知註冊失敗時會顯示診斷並退回定期檢查。
- **自動偵測 iPad**：預設啟用。優先使用已指定且具有 Sidecar UUID 的配對；沒有有效指定配對時，才依唯一 USB iPad 與 Sidecar 候選推定目標。有已儲存的裝置對應時優先使用；查詢失敗、候選未出現或有歧義時，不發起 iPad 連線。
- **明確配對適合多裝置環境**：唯一候選只是推定，不能證明 USB 與 Sidecar 身分屬於同一台 iPad。附近可能有其他 iPad 時，請停用自動偵測並明確配對。推定結果不會新增或改寫已儲存配對。
- **有線與無線目標**：指定配對可以在 USB 拔除後繼續依 Sidecar 可用性處理；僅靠 USB 推定的未配對目標，拔線後不會主動建立無線備援連線。

本次控制目標會顯示在設定頁與選單列。兩個開關可即時套用；已儲存的停用設定會保留。

## 選單列與介面語言

選單列使用 **18 × 18 pt、支援 Retina 的單色圖示**，隨 macOS 深淺色外觀調整。滑鼠停留可見 PadPilot 名稱，展開後可查看主螢幕、運作模式、裝置與診斷。

<p align="center">
  <img src="assets/menu-icons/preview.png" width="540" alt="PadPilot 選單列圖示：Sidecar、實體螢幕、虛擬備援、暫停、警告與處理中">
</p>

圖示依序表示 Sidecar、實體螢幕、虛擬備援、暫停、警告與處理中。圖檔隨專案提供；修改設計時可執行 `swift scripts/build_menu_icons.swift` 重建。

首次建立設定會依 macOS 語言選擇介面，非中文／日文系統預設為 English。之後可從選單列的 Language 選單、GUI 右上角的語言選單，或 `set-language` 指令切換。GUI 的使用說明、疑難排解與診斷說明連結會開啟對應語言的本機文件；裝置名稱、識別碼與原始日誌保留原文。

## 常用指令

以下指令在專案目錄執行。若安裝時已建立 `~/bin/padpilot-cli` 連結，且 `~/bin` 位於 PATH，也可直接使用 `padpilot-cli`。

```bash
# 狀態與設定
./bin/padpilot-cli status --json
./bin/padpilot-cli gui
./bin/padpilot-cli set-language zh-Hant   # 亦可使用 en 或 ja

# 運作模式：擇一設定
./bin/padpilot-cli set-mode automatic
./bin/padpilot-cli set-mode manual_only
./bin/padpilot-cli set-mode prefer_ipad

# 手動操作：依需要選擇
./bin/padpilot-cli action use_ipad_secondary
./bin/padpilot-cli action use_ipad_main
./bin/padpilot-cli action disconnect_ipad
./bin/padpilot-cli action reconnect_sidecar
./bin/padpilot-cli action refresh
./bin/padpilot-cli action reset           # 清除暫時覆寫與冷卻狀態

# 背景服務與登入自動啟動
./bin/padpilot-cli stop
./bin/padpilot-cli start
./bin/padpilot-cli exit                  # 停止服務並隱藏 PadPilot 選單
./bin/padpilot-cli autostart status
./bin/padpilot-cli autostart toggle

# 版本與完整指令說明
./bin/padpilot-cli --version
./bin/padpilot-cli --help
```

更新原始碼前請保留原版本備份，並先儲存、關閉設定視窗。更新後重新執行 `./scripts/install.sh --check`、`./scripts/install.sh`、`./bin/padpilot-cli status`，同時重建原生 App。GUI「關於」、CLI `--version` 與 App 使用同一版本來源；「關於」另提供 GitHub 入口與贊助區，收款連結未設定前按鈕停用。若需降回相容舊版，回復原始碼後重新安裝；安裝器保留配對設定，舊 App 在垃圾桶，但單獨取回 App 不會還原其引用的原始碼。

## 限制與疑難排解

- **Sidecar 是必要條件**：PadPilot 不會讓原本不相容的 Mac／iPad 支援 Sidecar，也不控制 Universal Control 的鍵盤滑鼠跨裝置行為。
- **連線時間取決於系統與裝置**：USB 通知、4 秒防抖或命令送出成功，都不等於 iPad 已完成顯示。冷卻期間會優先維持備援。
- **無頭環境仍需驗證**：冷開機、睡眠喚醒、集線器與多裝置組合尚未全面驗收；使用者登入前不提供 iPad 畫面。不要把關閉 FileVault／開啟自動登入當成保證可用的安裝步驟。
- **第三方控制可能互相影響**：若另有工具持續更改主螢幕或 Sidecar，請先切至 `manual_only`，再檢查切換原因與日誌。

設定與執行狀態預設位於 `~/Library/Application Support/PadPilot/`，日誌位於 `~/Library/Logs/PadPilot/`。回報問題時請附上版本、連線方式、重現步驟與相關日誌，並先遮蔽裝置序號、UUID、帳號及個人路徑。

私人目錄使用 `0700`，設定、狀態、socket 與日誌使用 `0600`；不接受其他使用者擁有或符號連結的狀態路徑。新的 IPC 日誌不記錄配對 payload，但歷史日誌不會自動清除。已測環境與仍為 `unknown` 的硬體情境見[發布驗收表](docs/development/2026-09-11-release-readiness.md)。

## 解除安裝

```bash
./scripts/uninstall.sh
```

預設會停止背景服務與原生選單，將此專案的 App、LaunchAgent 與 CLI 快捷連結移到垃圾桶，清除狀態快照；保留設定、日誌、專案及 BetterDisplay／虛擬螢幕。`./scripts/uninstall.sh --purge` 會另外將設定（包含曾使用的 `/tmp/PadPilot/config.json` 備援）與日誌移到垃圾桶，可復原。

## 文件與貢獻

- [完整安裝手冊](docs/INSTALLATION.md)
- [疑難排解與常見問答](docs/TROUBLESHOOTING.md)
- [系統架構](docs/ARCHITECTURE.md)
- [文件索引與語言版本](docs/README.md)
- [開發紀錄](docs/development/README.md)（供維護者追溯歷史，不是安裝步驟）
- [更新紀錄](CHANGELOG.md)
- [貢獻指南](CONTRIBUTING.md)與[安全政策](SECURITY.md)

歡迎回報問題、改善翻譯、補充硬體相容性紀錄或提交 Pull Request。修改程式後，可執行 `python3 -m unittest discover -s tests -v`；涉及 GUI 時另依貢獻指南檢查佈局。自動測試通過不代表已完成實機冷開機或插拔驗收。

## 授權與致謝

本專案採用 [MIT License](LICENSE)。Copyright (c) 2026 kcayut.

感謝 [BetterDisplay](https://github.com/waydabber/BetterDisplay) 提供顯示器控制能力。PadPilot 是獨立專案，未隸屬於 Apple 或 BetterDisplay，也不代表其官方支援。
