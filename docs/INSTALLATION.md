# PadPilot 安裝指南

**繁體中文** | [English](INSTALLATION.en.md) | [日本語](INSTALLATION.ja.md) · [文件索引](README.md)

PadPilot 提供 **Swift／AppKit 選單列＋SwiftUI 原生設定視窗＋Python 核心**。安裝腳本會一併編譯、安裝及啟動 `~/Applications/PadPilot.app`；沒有額外 pip 或 Swift 套件依賴。

安裝或解除安裝前，請先儲存並關閉 PadPilot 的設定／診斷視窗；若視窗仍開啟，安裝器會停止並提示重跑。

## 準備環境

- macOS 14+，目前以 Apple Silicon 為主要驗證環境。
- Python 3.10+，供背景核心使用。設定視窗內建於原生 App。
- Apple Command Line Tools，供本機編譯 App；完整 Xcode 不是必要條件。
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) 與可用的 CLI 控制能力。授權條件以 BetterDisplay 說明為準。
- 支援 Sidecar 的 iPad，先確認 macOS「螢幕鏡像輸出」可以手動連線。

不必先逐項手動安裝：安裝器會先偵測，再詢問沿用、指定路徑或安裝。Sidecar 需要已登入的使用者工作階段；FileVault 解鎖前無法由 PadPilot 接管，參閱[疑難排解](TROUBLESHOOTING.md#filevault)。

## 複製貼上安裝

在「終端機」貼上整段：

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

**公開發布條件：** [kcayut/PadPilot](https://github.com/kcayut/PadPilot) 必須設為公開，且本次腳本已推送至 `main`。尚未公開或腳本不存在會回傳 404；可先使用有權限取得的原始碼與下方本機安裝方式。這段指令會先完整下載腳本至暫存檔，下載成功才執行；來源壓縮檔也會先檢查路徑與檔案類型才解壓。

下載不需先有 Git 或 Python。原始碼固定存於 `~/Applications/PadPilot-source`，不會覆蓋同名的非管理資料夾；重跑會沿用這份原始碼繼續安裝，不下載更新。`.padpilot-install.json` 記錄受管理的來源與本次新增依賴，供解除安裝辨識；請保留它。

## 依賴選擇與本機安裝

已有原始碼時，在其專案目錄執行 `./scripts/install.sh`。使用上述下載方式者可執行：

```bash
cd "$HOME/Applications/PadPilot-source"
./scripts/install.sh --check
./scripts/install.sh
"$HOME/bin/padpilot-cli" status
```

`--check` 是不修改系統的完整預檢：不呼叫 Homebrew、不建立設定或日誌、不編譯、不啟動服務，也不掃描或改動螢幕。必要項目缺失回傳非零結束碼。

互動安裝會顯示找到的 Python 與 BetterDisplay 路徑，讓你沿用、輸入其他路徑或安裝缺少的依賴。安裝 Homebrew 或透過 Homebrew 安裝依賴前都會詢問；需要管理員密碼時由官方安裝流程處理。Apple Command Line Tools 必須在 macOS 對話框完成安裝，再重跑安裝器。

```bash
# 明確指定現有環境；路徑含空白時保留雙引號。
./scripts/install.sh --python "/path/to/python3" --betterdisplay-path "/Applications/BetterDisplay.app"

# 非互動：只沿用現有依賴；缺少必要依賴即停止。
./scripts/install.sh --yes

# 明確允許安裝缺少的 Homebrew 依賴。
./scripts/install.sh --yes --install-deps
```

`--python` 接受 Python 執行檔；`--betterdisplay-path` 接受 `.app` 資料夾或 CLI 執行檔。`--yes` 不等於同意安裝第三方軟體；缺少必要依賴時會停止，需手動安裝或加 `--install-deps`。BetterDisplay CLI help 成功不代表授權、Sidecar 或實際顯示可用。

Homebrew 自動安裝使用 Python 3.14，BetterDisplay 來自官方 [betterdisplay cask](https://formulae.brew.sh/cask/betterdisplay)。`--yes --install-deps` 仍可能需要管理員密碼或 Apple 安裝視窗，並非保證完全無人值守。

安裝器會編譯並本機簽署 `~/Applications/PadPilot.app`，保留設定、配對與登入啟動偏好；首次安裝預設啟用登入啟動：之後重新開機並登入 macOS，背景服務與選單列會自動啟動，不需再次執行安裝腳本。替換前記錄 LaunchAgent 與服務狀態，透過既有 CLI 停止服務與選單。新的 daemon 必須回覆結構化握手才算成功；啟動失敗會嘗試還原舊 App、LaunchAgent 與服務執行狀態，回復失敗會明確報錯。

安裝器會嘗試建立 `~/bin/padpilot-cli`，並記錄選定的 Python；已被其他程式占用的同名入口會保留，此時使用 `"$HOME/Applications/PadPilot.app/Contents/Resources/padpilot-cli"`。**請保留所選 Python 環境與原始碼資料夾。** App 引用兩者，搬移後需重新安裝；另一個來源路徑的同名 App／LaunchAgent 不會被接管。這版尚未內含 Python、Developer ID 簽署、公證或自動更新。

## 開啟與配對

```bash
open -a BetterDisplay
open "$HOME/Applications/PadPilot.app"
```

選單「設定與配對」開啟設定視窗，可搜尋、儲存配對並指定控制目標；刪除配對需確認。也能使用：

```bash
"$HOME/bin/padpilot-cli" pair --interactive
"$HOME/bin/padpilot-cli" gui
"$HOME/bin/padpilot-cli" gui diagnostics
```

設定儲存於 `~/Library/Application Support/PadPilot/config.json`，既有配對不需重建。

若主位置寫入失敗，會使用 `/tmp/PadPilot/config.json`。daemon、CLI、GUI、選單與安裝預檢均選擇兩個位置中最後寫入的檔案；狀態快照採相同規則。備援位於暫存目錄，請修復主位置的寫入問題，勿把它當作長期備份。損壞的設定不會自動重設或覆寫：服務拒絕啟動，GUI 顯示錯誤並停用儲存；請先備份原檔，再修復 JSON 或還原已知有效設定。

## 更新與回復

先保留原始碼備份，儲存並關閉設定視窗。更新原始碼後再跑「預檢 → 安裝 → status」三步，原生二進位也會重新編譯。GUI「關於」顯示 `v0.1.0`，與 CLI／App 版本共用 `core.__version__`；此頁另有 GitHub 連結與尚未開放的贊助入口。

安裝器保留設定，舊 App 移到垃圾桶；它不會自動下載更新、建立 Git tag 或發布。App 引用原始碼，僅取回垃圾桶中的 App 不能完整回復程式版本。

## 本機隱私與權限

PadPilot 專用設定、runtime、日誌目錄為 `0700`；設定、狀態、IPC socket 與日誌為 `0600`。拒絕其他使用者擁有的路徑、符號連結與有多個硬連結的狀態檔，包含 `/tmp/PadPilot` 備援路徑。遇到不安全路徑會停止，不自動刪除或接管他人檔案。請見[路徑與啟動失敗排解](TROUBLESHOOTING.md#safe-startup)。

IPC 僅記錄已知命令名稱，不記錄配對 payload。既有日誌仍可能含裝置資訊；匯出前自行遮蔽。解除安裝不會使用廣泛的程序名稱終止指令，也不移除他人的同名 CLI 連結。

## 日常操作與開發

```bash
"$HOME/bin/padpilot-cli" start            # 啟動服務並顯示選單
"$HOME/bin/padpilot-cli" stop             # 停止服務、保留選單
"$HOME/bin/padpilot-cli" exit             # 停止服務並關閉選單
"$HOME/bin/padpilot-cli" autostart status
"$HOME/bin/padpilot-cli" autostart toggle
python3 scripts/build_app.py        # 僅建置 build/PadPilot.app，不安裝或啟動
"$HOME/bin/padpilot-cli" menu-json        # 只讀原生選單模型，不掃描硬體
```

單元測試包含原生選單三語資料解碼、子選單、勾選／停用狀態及命令白名單：

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
python3 scripts/check_release.py --gui
```

本機發布檢查另含 Shell、plist、版本一致性、ResourceWarning 與目前原始碼／Git 歷史的隱私模式掃描；輸出在 `build/release-check.json`、`build/privacy-scan.json`，匹配值不寫進掃描報告。已審核的歷史例外獨立列出；新匹配仍使結束碼為 1，即使程式測試全數通過。無桌面工作階段時不要加 `--gui`，GUI 會標為未驗證。這不取代實機測試，詳見[發布驗收表](development/2026-09-11-release-readiness.md)。

## 解除安裝

從任何目錄複製執行：

```bash
/bin/bash "$HOME/Applications/PadPilot-source/scripts/uninstall.sh"
```

手動取得原始碼者在其原始專案目錄執行 `./scripts/uninstall.sh`。互動流程會逐項詢問設定與配對、日誌、受管理的原始碼、以及安裝器新增的每項第三方依賴，**預設全部保留**。最後顯示完整移除摘要並確認，才停止此專案的服務與選單、移除 App、LaunchAgent 與 CLI 整合。

| 選項 | 行為 |
| --- | --- |
| `--yes` | 免互動移除 PadPilot App 與整合，保留設定、日誌、原始碼與第三方依賴。 |
| `--yes --purge` | 另清除設定／配對與日誌，包含曾使用的 `/tmp/PadPilot/config.json` 備援。 |
| `--remove-config`／`--remove-logs` | 單獨選擇設定或日誌。 |
| `--remove-source` | 另移除由下載安裝器管理的 `~/Applications/PadPilot-source`；手動取得的來源不自動刪除。 |
| `--remove-dependency NAME` | 選擇 receipt 記錄由安裝器新裝的 Homebrew 項目，可重複指定；無紀錄的既有軟體不自動卸除。 |

App、整合、設定、日誌與選定的來源會移到垃圾桶，可復原。第三方依賴交由 Homebrew 解除安裝，不在 PadPilot 的垃圾桶回復範圍內，也不執行 `autoremove` 或 `--zap`。有其他 Homebrew 套件依賴的 Python 會保留；Homebrew 本身、Apple Command Line Tools、系統 Python、既有 BetterDisplay 與虛擬螢幕不一併清除。

移除 BetterDisplay 可能中斷目前的 Sidecar／虛擬螢幕，會再次要求確認；非互動時需另外明確加 `--allow-display-disconnect`。移除 Python 或來源前請先確認不再需要 PadPilot；若保留來源，可重跑安裝器復原安裝。
