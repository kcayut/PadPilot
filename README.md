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
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg" alt="License: PolyForm Noncommercial 1.0.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-lightgrey.svg" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/status-early%20preview-orange.svg" alt="Status: Early Preview">
</p>

PadPilot 是搭配 **Apple Sidecar 與 BetterDisplay** 使用的 macOS 顯示器自動化工具，主要為 Mac mini + iPad 的使用情境設計。沒有實體螢幕時，它會嘗試連接指定 iPad，並將它設為主螢幕；接回實體螢幕時，則依運作模式與手動選擇調整顯示器角色。

你可以透過選單列、圖形設定視窗或命令列控制連線、管理配對，以及查看目前狀態與切換原因。

GUI 的「使用說明」、「疑難排解」與診斷說明會在 GitHub 開啟對應版本的文件，並跟隨介面語言。私人倉庫的文件需要登入有存取權限的 GitHub 帳號；文件連結固定版本，不會隨新版發布而改變內容。

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
| Python | Python 3.10+；圖形設定視窗另外需要此 Python 環境可匯入 `tkinter`。安裝器會偵測，並提供沿用、手動路徑或安裝選項。 |
| [BetterDisplay](https://github.com/waydabber/BetterDisplay) | 提供 Sidecar 與顯示器控制。請選擇相容於 macOS 的版本，並確認 CLI 可用；命令列控制依上游授權需要 Pro 或有效試用。 |
| Apple Command Line Tools | 編譯 Swift／AppKit 原生選單列；首次安裝執行 `xcode-select --install`。 |
| 連線 | 初次設定建議使用可傳輸資料的 USB 線，並在 iPad 上信任 Mac。無線 Sidecar 另需 Wi-Fi、藍牙與 Handoff。 |

裝置相容性及有線／無線條件請參閱 [Apple Sidecar 說明](https://support.apple.com/en-us/102597)。BetterDisplay 的功能與授權以[上游說明](https://github.com/waydabber/BetterDisplay#key-features)為準；PadPilot 的授權不包含第三方軟體授權。

## 快速開始

### 1. 安裝

先確認可以在 macOS「螢幕鏡像輸出」中手動使用 Sidecar，再複製整段至「終端機」：

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

**下載入口須待 [kcayut/PadPilot](https://github.com/kcayut/PadPilot) 公開，且本次安裝腳本已發布至 `main` 後才能使用。** 私人倉庫或尚未發布的腳本會回傳 404；下載失敗不會執行安裝器。已有原始碼者可直接在專案目錄執行 `./scripts/install.sh`。

安裝器先偵測 Python／Tk、BetterDisplay 與 Apple 編譯工具，再讓你選擇沿用、手動指定路徑或安裝缺少的依賴。透過 Homebrew 安裝前會詢問；沒有 Homebrew 時也會先徵求同意。Apple Command Line Tools 由 macOS 的安裝視窗處理，完成後重跑同一段指令即可。

安裝或解除安裝前，請先儲存並關閉 PadPilot 的設定／診斷視窗；若視窗仍開啟，安裝器會停止並提示重跑。

來源保存在 `~/Applications/PadPilot-source`；重跑會沿用此資料夾、繼續安裝，不覆蓋原始碼或自動更新。App 安裝至 `~/Applications/PadPilot.app`，保留既有配對、模式與登入啟動偏好。首次安裝預設啟用登入啟動；收到背景服務的握手回應後才報告成功，啟動失敗會嘗試還原舊 App 與服務狀態。

```bash
"$HOME/bin/padpilot-cli" status
open "$HOME/Applications/PadPilot.app"
```

CLI 快捷入口會使用安裝時選定的 Python。若 `~/bin/padpilot-cli` 已被其他程式占用，請使用 `"$HOME/Applications/PadPilot.app/Contents/Resources/padpilot-cli"`。**請保留 Python 環境與原始碼資料夾**；這版仍是本機編譯、引用原始碼的 App。依賴檢查、手動路徑、無 GUI 安裝及非互動選項見[完整安裝指南](docs/INSTALLATION.md)。BetterDisplay CLI 回應不等於授權、Sidecar 配對或實際顯示已通過驗證。

### 2. 指定 iPad

在終端機執行互動式配對，選取要控制的 iPad：

```bash
"$HOME/bin/padpilot-cli" pair --interactive
```

也可開啟圖形設定視窗，搜尋裝置、儲存配對並選定控制目標：

```bash
"$HOME/bin/padpilot-cli" gui
```

PadPilot 配對只記錄裝置對應，不會取代 Apple Account 或「信任這部電腦」設定。雖然可以儲存多台 iPad，目前一次管理一台控制目標。

### 3. 確認備援與狀態

若要使用無實體螢幕情境，請確認 BetterDisplay 中存在名為 `PadPilotVirtual` 的虛擬螢幕，或在 PadPilot 設定中選擇既有的虛擬螢幕。若版本不支援自動建立，請先在 BetterDisplay 中手動建立一次。

```bash
"$HOME/bin/padpilot-cli" status
"$HOME/bin/padpilot-cli" open-log
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

以下指令可從任何目錄執行。若 `~/bin` 位於 PATH，也可直接使用 `padpilot-cli`。安裝、更新及開發腳本仍須在原始碼目錄執行。

```bash
# 狀態與設定
"$HOME/bin/padpilot-cli" status --json
"$HOME/bin/padpilot-cli" gui
"$HOME/bin/padpilot-cli" set-language zh-Hant   # 亦可使用 en 或 ja

# 運作模式：擇一設定
"$HOME/bin/padpilot-cli" set-mode automatic
"$HOME/bin/padpilot-cli" set-mode manual_only
"$HOME/bin/padpilot-cli" set-mode prefer_ipad

# 手動操作：依需要選擇
"$HOME/bin/padpilot-cli" action use_ipad_secondary
"$HOME/bin/padpilot-cli" action use_ipad_main
"$HOME/bin/padpilot-cli" action disconnect_ipad
"$HOME/bin/padpilot-cli" action reconnect_sidecar
"$HOME/bin/padpilot-cli" action refresh
"$HOME/bin/padpilot-cli" action reset           # 清除暫時覆寫與冷卻狀態

# 背景服務與登入自動啟動
"$HOME/bin/padpilot-cli" stop
"$HOME/bin/padpilot-cli" start
"$HOME/bin/padpilot-cli" exit                  # 停止服務並隱藏 PadPilot 選單
"$HOME/bin/padpilot-cli" autostart status
"$HOME/bin/padpilot-cli" autostart toggle

# 版本與完整指令說明
"$HOME/bin/padpilot-cli" --version
"$HOME/bin/padpilot-cli" --help
```

更新原始碼前請保留原版本備份，並先儲存、關閉設定視窗。更新後重新執行 `./scripts/install.sh --check`、`./scripts/install.sh`、`"$HOME/bin/padpilot-cli" status`，同時重建原生 App。GUI「關於」、CLI `--version` 與 App 使用同一版本來源；「關於」另提供 GitHub 入口與贊助區，收款連結未設定前按鈕停用。若需降回相容舊版，回復原始碼後重新安裝；安裝器保留配對設定，舊 App 在垃圾桶，但單獨取回 App 不會還原其引用的原始碼。

## 限制與疑難排解

- **Sidecar 是必要條件**：PadPilot 不會讓原本不相容的 Mac／iPad 支援 Sidecar，也不控制 Universal Control 的鍵盤滑鼠跨裝置行為。
- **連線時間取決於系統與裝置**：USB 通知、4 秒防抖或命令送出成功，都不等於 iPad 已完成顯示。冷卻期間會優先維持備援。
- **無頭環境仍需驗證**：冷開機、睡眠喚醒、集線器與多裝置組合尚未全面驗收；使用者登入前不提供 iPad 畫面。不要把關閉 FileVault／開啟自動登入當成保證可用的安裝步驟。
- **第三方控制可能互相影響**：若另有工具持續更改主螢幕或 Sidecar，請先切至 `manual_only`，再檢查切換原因與日誌。

設定與執行狀態預設位於 `~/Library/Application Support/PadPilot/`，日誌位於 `~/Library/Logs/PadPilot/`。回報問題時請附上版本、連線方式、重現步驟與相關日誌，並先遮蔽裝置序號、UUID、帳號及個人路徑。

私人目錄使用 `0700`，設定、狀態、socket 與日誌使用 `0600`；不接受其他使用者擁有或符號連結的狀態路徑。新的 IPC 日誌不記錄配對 payload，但歷史日誌不會自動清除。已測環境與仍為 `unknown` 的硬體情境見[發布驗收表](docs/development/2026-09-11-release-readiness.md)。

## 解除安裝

複製至終端機，即可逐項選擇要移除的內容：

```bash
/bin/bash "$HOME/Applications/PadPilot-source/scripts/uninstall.sh"
```

解除安裝會先顯示移除摘要並確認，再停止本專案服務與選單，將 App、LaunchAgent 與屬於此專案的 CLI 入口移到垃圾桶。設定／配對、日誌、下載的原始碼，以及由安裝器新增的第三方依賴會分別詢問；預設保留。既有 Python、BetterDisplay、Homebrew、Apple 工具與虛擬螢幕不會一併刪除。

免互動只移除 PadPilot 主體：加 `--yes`。同時清理設定與日誌：加 `--yes --purge`；仍保留原始碼與第三方依賴。手動取得原始碼者在其專案目錄執行 `./scripts/uninstall.sh`。詳見[解除安裝選項](docs/INSTALLATION.md#解除安裝)。

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

本專案採用 [PolyForm Noncommercial License 1.0.0](LICENSE)。作者：**kcayut**，Copyright (c) 2026 kcayut。

- 允許非商業用途的使用、修改與散佈；授權未允許的商業用途須另取得作者授權。
- 散佈原始碼、執行檔或修改版本時，必須附上授權條款或其官方網址，並保留 [NOTICE](NOTICE) 中所有 `Required Notice:` 作者與專案來源聲明。建置出的 App 已內附 `LICENSE` 與 `NOTICE`。
- 授權另明文允許慈善、教育、公共研究、公共安全或衛生、環保及政府機構使用，不因資金來源而受限；完整範圍以授權原文為準。

這是可取得原始碼的非商業授權，並非 OSI 定義的開源授權。本次變更適用於附帶此授權提供的版本；不撤回先前已依 MIT 授權取得之版本的權利。

感謝 [BetterDisplay](https://github.com/waydabber/BetterDisplay) 提供顯示器控制能力。PadPilot 是獨立專案，未隸屬於 Apple 或 BetterDisplay，也不代表其官方支援。
