# SidecarSwitch 安裝指南

**繁體中文** | [English](INSTALLATION.en.md) | [日本語](INSTALLATION.ja.md) · [文件索引](README.md)

## 下載已編譯版本（建議）

支援 Apple Silicon、macOS 14+，不提供 Intel 版本。從 [GitHub Releases](https://github.com/kcayut/SidecarSwitch/releases) 下載 `.dmg`，將 `SidecarSwitch.app` 拖入 Applications 後開啟。也提供 `.zip`、`SHA256SUMS` 與 `build-info.json`；App 內含 Swift 執行檔、CPython、標準函式庫與 SidecarSwitch 核心，使用者無需編譯或安裝 pip 套件。

雙擊已安裝的 App 會直接開啟控制 GUI 與選單列圖示。關閉視窗後，選單列仍會保留；再次雙擊可重開 GUI。登入或背景啟動只顯示選單列。

新安裝預設「僅手動模式」，並勾選「開機無螢幕時自動連線 iPad」。啟用登入自動啟動後，每次開機登入後最多偵測 3 輪，每輪 30 秒（合計最多 90 秒）；三輪都找不到目標便停止。找到目標且無實體螢幕時最多發起一輪連線（最多 3 次）；之後只接受選單或全域快速鍵的明確要求，斷線不自行重連。同次開機重開 App 不會重試。更新保留既有模式與快速鍵；此選項不保證 iPad 一定可連線，詳見[連線規則](ARCHITECTURE.md#全域連線快速鍵)。

**開發預覽版沒有 Developer ID 簽章與 Apple 公證，只有 ad-hoc 簽章。** 遇到無法驗證開發者／無法檢查惡意軟體時，確認來源後依 [Apple 說明](https://support.apple.com/en-us/102445) 使用「隱私權與安全性 → 仍要打開」。若顯示損毀，請重新下載並核對 SHA-256；不要關閉整體 Gatekeeper，也不要把所有損毀警告視為誤報。

BetterDisplay App 仍須另行安裝並開啟；SidecarSwitch 目前的功能可搭配免費版使用，不要求 Pro 或試用資格。獨立 `betterdisplaycli` 可選；App 內建 CLI 已足夠。自動偵測涵蓋 `/Applications`、`~/Applications` 與 LaunchServices 登記的位置；也可在進階選項手動指定 App／CLI。

### 腳本安裝與 Python 選擇

先儲存並關閉 SidecarSwitch 設定視窗。下載官方腳本後執行，無需先安裝 Python：

```bash
(
  set -e
  installer="$(mktemp -t sidecarswitch-release-install)"
  trap 'rm -f "$installer"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/kcayut/SidecarSwitch/main/scripts/install_release.sh \
    --output "$installer"
  /bin/bash "$installer"
)
```

腳本包含預覽版在內選取最新公開發行包，核對 SHA-256，唯讀掛載 DMG，再使用包內 Python 安裝。預設目的地為 `/Applications/SidecarSwitch.app`；若沒有寫入權限，可加 `--target "$HOME/Applications/SidecarSwitch.app"`，不需要 sudo。若找不到可下載的發行包就會停止，不會改用原始碼版本。

- `--bundled`：使用內建 CPython；`--yes` 未指定 Python 時也採此選項。
- `--python /absolute/path/python3`：選擇自己的 Apple Silicon CPython 3.10+，會先驗證版本、架構及必要模組。
- `--tag v0.1.0-dev.1`：指定已存在的發行版本，而非最新版本。

首次安裝完成後，開啟 App 才啟動背景服務。更新器會先解除原生登入服務註冊，再替換 App，恢復原本已啟用的登入啟動及執行狀態；已被系統停用／等待允許的項目不會自動重新申請。設定、配對與 Python 選擇檔保留；腳本更新仍會再次選擇 Python。安裝失敗會嘗試還原 App、設定與服務。變更安裝位置前，可用下方 CLI 移除原安裝並保留設定。

### 安裝後切換或復原 Python

GUI、CLI、daemon 與登入啟動均使用同一選擇，記錄在 `~/Library/Application Support/SidecarSwitch/python-runtime.json`，不修改 App 簽章。先離開 SidecarSwitch，再執行：

```bash
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" --bundled-cli runtime external --python /absolute/path/python3
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" --bundled-cli runtime bundled
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" runtime status
```

兩個切換指令擇一；第一個選外部 Python，第二個切回內建。外部 Python 被刪除時也可使用 `--bundled-cli` 復原。不要把外部 Python 指向另一份 SidecarSwitch.app 內的 Python。

**移除 Release：先從選單選擇「結束」，再將 Applications 裡的 SidecarSwitch.app 拖進垃圾桶即可。**「結束」會停止顯示自動化，已啟用的原生登入服務會保留一個不輪詢的 App 搬移監看；拖進垃圾桶時自動解除登入註冊並結束。垃圾桶內的程式不會啟動背景 Python。設定、配對與日誌保留，系統登入項目的名稱可能稍後才消失。

可選的 CLI 清理方式（例如需要一併清除資料，或變更安裝位置）：預設保留設定與日誌；加 `--purge` 則一併移到垃圾桶。請在移除 App 前執行：

```bash
"/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli" --bundled-cli uninstall --yes
```

### 維護者：推送 tag 自動發行

以下假設 GitHub 遠端名為 `github`；若直接從 GitHub clone，通常是 `origin`，請以 `git remote -v` 確認。推送到 Gitea 不會觸發 GitHub Actions。

```bash
git tag v0.1.0-dev.1
git push github v0.1.0-dev.1
```

先將程式變更提交到要發行的 commit。支援 `vX.Y.Z` 或 `vX.Y.Z-dev.N`／`alpha.N`／`beta.N`／`rc.N`。**本機打 tag 不會觸發，推送至 GitHub 才會觸發。** workflow 在 ARM runner 執行軟體檢查、編譯、封裝與搬移測試，完成所有附件後自動公開為 prerelease，不需要 Apple 憑證或人工核准。已公開版本不覆寫，修正請推新 tag；失敗的草稿可重跑。獨立硬體驗收仍標記 unknown。

本機建立相同產物：需 Python 3.12+ 與 Apple 編譯工具，先在建置用虛擬環境執行 `python3 -m pip install -r scripts/dmg-requirements.txt`，再執行 `python3 scripts/build_release.py --tag v0.1.0-dev.1`；輸出在 `dist/<tag>/`。DMG 排版套件僅用於建置，不會加入 App 執行環境；`--no-dmg` 可略過 DMG 與這項依賴。CPython 來源與 SHA-256 固定在 `scripts/python-runtime.json`，授權文件隨 Python 一起保留。版本完整 tag 與建置 commit 記在產物中。

<a id="source-installation"></a>
## 原始碼安裝（開發用）

以下步驟只適用於本機編譯的原始碼版本。

SidecarSwitch 提供 **Swift／AppKit 選單列＋SwiftUI 原生設定視窗＋Python 核心**。安裝腳本會一併編譯、安裝及啟動 `~/Applications/SidecarSwitch.app`；沒有額外 pip 或 Swift 套件依賴。

安裝或解除安裝前，請先儲存並關閉 SidecarSwitch 的設定／診斷視窗；若視窗仍開啟，安裝器會停止並提示重跑。

## 準備環境

- macOS 14+，目前以 Apple Silicon 為主要驗證環境。
- Python 3.10+，供背景核心使用。設定視窗內建於原生 App。
- Apple Command Line Tools，供本機編譯 App；完整 Xcode 不是必要條件。
- [BetterDisplay](https://github.com/waydabber/BetterDisplay) 與可用的 CLI 控制能力。授權條件以 BetterDisplay 說明為準。
- 支援 Sidecar 的 iPad，先確認 macOS「螢幕鏡像輸出」可以手動連線。

不必先逐項手動安裝：安裝器會先偵測，再詢問沿用、指定路徑或安裝。Sidecar 需要已登入的使用者工作階段；FileVault 解鎖前無法由 SidecarSwitch 接管，參閱[疑難排解](TROUBLESHOOTING.md#filevault)。

## 複製貼上安裝

在「終端機」貼上整段：

```bash
(
  set -e
  installer="$(mktemp -t sidecarswitch-install)"
  trap 'rm -f "$installer"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/kcayut/SidecarSwitch/main/scripts/bootstrap.sh \
    --output "$installer"
  /bin/bash "$installer"
)
```

**下載方式：** 腳本會從 [SidecarSwitch](https://github.com/kcayut/SidecarSwitch) 的 `main` 下載。若出現 404，請確認網址或改用 [Releases](https://github.com/kcayut/SidecarSwitch/releases) 的 DMG。指令會先完整下載腳本至暫存檔，下載成功才執行；來源壓縮檔也會先檢查路徑與檔案類型才解壓。

下載不需先有 Git 或 Python。原始碼固定存於 `~/Applications/SidecarSwitch-source`，不會覆蓋同名的非管理資料夾；重跑會沿用這份原始碼繼續安裝，不下載更新。`.sidecarswitch-install.json` 記錄受管理的來源與安裝器新增的依賴，供解除安裝辨識；請保留它。

## 依賴選擇與本機安裝

已有原始碼時，在其專案目錄執行 `./scripts/install.sh`。使用上述下載方式者可執行：

```bash
cd "$HOME/Applications/SidecarSwitch-source"
./scripts/install.sh --check
./scripts/install.sh
"$HOME/bin/sidecarswitch-cli" status
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

`--python` 接受 Python 執行檔；`--betterdisplay-path` 接受 `.app` 資料夾或 CLI 執行檔。`--yes` 不等於同意安裝第三方軟體；缺少必要依賴時會停止，需手動安裝或加 `--install-deps`。BetterDisplay CLI help 成功不代表 Sidecar 或實際顯示可用。

Homebrew 自動安裝使用 Python 3.14，BetterDisplay 來自官方 [betterdisplay cask](https://formulae.brew.sh/cask/betterdisplay)。`--yes --install-deps` 仍可能需要管理員密碼或 Apple 安裝視窗，並非保證完全無人值守。

安裝器會編譯並本機簽署 `~/Applications/SidecarSwitch.app`，保留設定與配對。首次啟動會向 macOS 註冊 App 內的登入服務；若系統要求允許，請到「系統設定 → 一般 → 登入項目」啟用 SidecarSwitch。之後會尊重系統的停用選擇，不因重新開 App 自動開回。替換 App 前解除註冊，失敗時嘗試還原 App、偏好及原本的服務狀態。一般「結束」僅停止目前的執行階段，下次登入仍依系統註冊啟動。

安裝器會嘗試建立 `~/bin/sidecarswitch-cli`，並記錄選定的 Python；已被其他程式占用的同名入口會保留，此時使用 `"$HOME/Applications/SidecarSwitch.app/Contents/Resources/sidecarswitch-cli"`。**請保留所選 Python 環境與原始碼資料夾。** App 引用兩者，搬移後需重新安裝；另一個來源路徑的同名 App／LaunchAgent 不會被接管。原始碼安裝的 App 不內含 Python，亦不提供 Developer ID 簽署、公證或自動更新。

## 開啟與配對

```bash
open -a BetterDisplay
open "$HOME/Applications/SidecarSwitch.app"
```

選單「設定與配對」開啟設定視窗，可搜尋、儲存配對並指定控制目標；刪除配對需確認。也能使用：

```bash
"$HOME/bin/sidecarswitch-cli" pair --interactive
"$HOME/bin/sidecarswitch-cli" gui
"$HOME/bin/sidecarswitch-cli" gui diagnostics
```

設定儲存於 `~/Library/Application Support/SidecarSwitch/config.json`，既有配對不需重建。

若主位置寫入失敗，會使用 `/tmp/SidecarSwitch/config.json`。daemon、CLI、GUI、選單與安裝預檢均選擇兩個位置中最後寫入的檔案；狀態快照採相同規則。備援位於暫存目錄，請修復主位置的寫入問題，勿把它當作長期備份。損壞的設定不會自動重設或覆寫：服務拒絕啟動，GUI 顯示錯誤並停用儲存；請先備份原檔，再修復 JSON 或還原已知有效設定。

## 更新與回復

先保留原始碼備份，儲存並關閉設定視窗。更新原始碼後再跑「預檢 → 安裝 → status」三步，原生二進位也會重新編譯。GUI「關於」顯示 `v0.1.0`，與 CLI／App 版本共用 `core.__version__`；此頁另有 GitHub 連結與尚未開放的贊助入口。

安裝器保留設定，舊 App 移到垃圾桶；它不會自動下載更新、建立 Git tag 或發布。App 引用原始碼，僅取回垃圾桶中的 App 不能完整回復程式版本。

## 本機隱私與權限

SidecarSwitch 專用設定、runtime、日誌目錄為 `0700`；設定、狀態、IPC socket 與日誌為 `0600`。拒絕其他使用者擁有的路徑、符號連結與有多個硬連結的狀態檔，包含 `/tmp/SidecarSwitch` 備援路徑。遇到不安全路徑會停止，不自動刪除或接管他人檔案。請見[路徑與啟動失敗排解](TROUBLESHOOTING.md#safe-startup)。

IPC 僅記錄已知命令名稱，不記錄配對 payload。既有日誌仍可能含裝置資訊；匯出前自行遮蔽。解除安裝不會使用廣泛的程序名稱終止指令，也不移除他人的同名 CLI 連結。

## 日常操作與開發

```bash
"$HOME/bin/sidecarswitch-cli" start            # 啟動服務並顯示選單
"$HOME/bin/sidecarswitch-cli" stop             # 停止服務、保留選單
"$HOME/bin/sidecarswitch-cli" exit             # 停止服務並關閉選單
"$HOME/bin/sidecarswitch-cli" autostart status
"$HOME/bin/sidecarswitch-cli" autostart toggle
python3 scripts/build_app.py        # 僅建置 build/SidecarSwitch.app，不安裝或啟動
"$HOME/bin/sidecarswitch-cli" menu-json        # 只讀原生選單模型，不掃描硬體
```

單元測試包含原生選單三語資料解碼、子選單、勾選／停用狀態及命令白名單：

```bash
python3 -m unittest discover -s tests
python3 scripts/check_gui_layout.py
python3 scripts/check_release.py --gui
```

本機發布檢查另含 Shell、plist、版本一致性、ResourceWarning 與目前原始碼／Git 歷史的隱私模式掃描；輸出在 `build/release-check.json`、`build/privacy-scan.json`，匹配值不寫進掃描報告。已審核的歷史例外獨立列出；新匹配仍使結束碼為 1，即使程式測試全數通過。無桌面工作階段時不要加 `--gui`，GUI 會標為未驗證。這不取代實機測試。

## 解除安裝

從任何目錄複製執行：

```bash
/bin/bash "$HOME/Applications/SidecarSwitch-source/scripts/uninstall.sh"
```

手動取得原始碼者在其原始專案目錄執行 `./scripts/uninstall.sh`。互動流程會逐項詢問設定與配對、日誌、受管理的原始碼、以及安裝器新增的每項第三方依賴，**預設全部保留**。最後顯示完整移除摘要並確認，才停止此專案的服務與選單、解除登入服務註冊，並移除 App 與 CLI 整合。

| 選項 | 行為 |
| --- | --- |
| `--yes` | 免互動移除 SidecarSwitch App 與整合，保留設定、日誌、原始碼與第三方依賴。 |
| `--yes --purge` | 另清除設定／配對與日誌，包含曾使用的 `/tmp/SidecarSwitch/config.json` 備援。 |
| `--remove-config`／`--remove-logs` | 單獨選擇設定或日誌。 |
| `--remove-source` | 另移除由下載安裝器管理的 `~/Applications/SidecarSwitch-source`；手動取得的來源不自動刪除。 |
| `--remove-dependency NAME` | 選擇 receipt 記錄由安裝器新裝的 Homebrew 項目，可重複指定；無紀錄的既有軟體不自動卸除。 |

App、整合、設定、日誌與選定的來源會移到垃圾桶，可復原。第三方依賴交由 Homebrew 解除安裝，不在 SidecarSwitch 的垃圾桶回復範圍內，也不執行 `autoremove` 或 `--zap`。有其他 Homebrew 套件依賴的 Python 會保留；Homebrew 本身、Apple Command Line Tools、系統 Python、既有 BetterDisplay 與虛擬螢幕不一併清除。

移除 BetterDisplay 可能中斷目前的 Sidecar／虛擬螢幕，會再次要求確認；非互動時需另外明確加 `--allow-display-disconnect`。移除 Python 或來源前請先確認不再需要 SidecarSwitch；若保留來源，可重跑安裝器復原安裝。
