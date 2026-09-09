# 🛠️ PadPilot 安裝與完整設定手冊 (Installation Guide)

本文件詳細說明 PadPilot 的系統需求、依賴項目配置、自動與手動安裝流程，以及初次配對與解除安裝。

---

## 📋 系統需求 (System Requirements)

- **Mac 機型**：建議配備 Apple Silicon 晶片之 Mac（如 Mac mini M1/M2/M4、Mac Studio、MacBook 等）。
- **作業系統**：macOS 14 (Sonoma) 或更高版本。
- **Python**：Python 3.10+（系統自帶或 Homebrew 安裝之 Python 3 均可）。
- **iPad 裝置**：支援 Apple 原生 Sidecar 之 iPad，需登入相同之 Apple Account 並開啟 Wi-Fi / 藍牙 / 接力（Handoff）。
- **實體連線（強烈建議）**：透過原廠或高品質 USB-C / Thunderbolt 傳輸線連接 Mac 與 iPad，提供最低延遲與最高連線穩定度。

> [!IMPORTANT]
> **Sidecar 核心先決條件**：
> macOS 的 Sidecar 機制必須在**使用者已登入系統的階段**才能建立。如果您的 Mac 啟用了 FileVault 全磁碟加密，重開機後在尚未輸入密碼登入前，系統底層服務尚未啟動，無法自動連線 iPad。若您希望達到純無頭（Headless）冷開機自動進入系統，請參閱 [疑難排解手冊 - FileVault 與自動登入](TROUBLESHOOTING.md#filevault)。

---

## 📦 依賴項目安裝 (Dependencies)

PadPilot 的架構設計高度精簡，主控程式（Daemon）、CLI 與 GUI 均基於純 Python 標準庫（ctypes、tkinter 等），無額外 pip 套件需求。

但為了達成 Menu Bar 整合與顯示器控制，需要以下輔助工具：

### 1. SwiftBar（Menu Bar 整合）
用於在 macOS 頂端選單列呈現動態圖示、即時連線狀態與快捷操作選單。
- **透過 Homebrew 安裝**：
  ```bash
  brew install --cask swiftbar
  ```
- **或手動下載**：至 [SwiftBar 官方釋出頁面](https://github.com/swiftbar/SwiftBar/releases) 下載並移入 `/Applications`。

### 2. BetterDisplay（顯示器控制與虛擬螢幕備援）
提供 Sidecar 連線命令列介面，並在無螢幕、無 iPad 時提供虛擬螢幕（Framebuffer）供遠端桌面救護。
- **透過 Homebrew 安裝**：
  ```bash
  brew install --cask betterdisplay
  ```
- **或手動下載**：至 [BetterDisplay 官方釋出頁面](https://github.com/waydabber/BetterDisplay/releases) 下載並移入 `/Applications`。
- **啟用 CLI 控制介面**：開啟 BetterDisplay 設定 -> 勾選啟用 Command Line Interface (CLI) 支援。

---

## ⚡ 快速安裝（推薦）

PadPilot 提供非侵入式的一鍵安裝腳本，會自動探測環境依賴、建立 LaunchAgent、連結 SwiftBar 外掛與命令列工具：

```bash
git clone https://github.com/kcayut/PadPilot.git
cd PadPilot
./scripts/install.sh
```

*(若希望自動同意 Homebrew 安裝相依項目，可帶 `--yes` 參數：`./scripts/install.sh --yes`)*

安裝流程包含：
1. 探測並提示安裝 BetterDisplay 與 SwiftBar。
2. 將 `swiftbar/padpilot.30s.py` 符號連結至 SwiftBar 外掛目錄。
3. 依據本機 Python 與專案路徑，安全產生 `~/Library/LaunchAgents/com.padpilot.daemon.plist` 並載入背景守護行程。
4. 在 `~/bin/padpilot-cli` 建立快捷命令列連結（若 `~/bin` 存在）。

---

## 📱 配對您的 iPad (First-Time Pairing)

初次安裝後，需讓 PadPilot 辨識並綁定欲控制的指定 iPad：

### 方式 A：透過互動式 CLI 精靈（推薦）
1. 將 iPad 透過傳輸線插上 Mac，並在 iPad 上信任該部電腦。
2. 於終端機執行：
   ```bash
   ./bin/padpilot-cli pair --interactive
   ```
3. 程式會掃描當前 IOKit USB 匯流排與 Sidecar 目標，引導您選取欲綁定的 iPad。

### 方式 B：透過 GUI 設定介面配對
1. 執行 `./bin/padpilot-cli gui` 或由 Menu Bar 點選「設定與配對」。
2. 切換至側邊欄「🔍 搜尋新裝置」分頁。
3. 系統會列出當前偵測到的 USB 裝置與 Sidecar 目標，點擊「儲存為配對裝置」即可。

配對完成後，iPad 識別碼會安全寫入：
`~/Library/Application Support/PadPilot/config.json`

---

## ⚙️ 啟動與日常使用

1. **啟動 SwiftBar**：
   ```bash
   open -a SwiftBar
   ```
   macOS 頂端選單列即會顯示 PadPilot 圖示（`🖥️`、`📱`、`◻️` 等）。
2. **管理開機自動登入啟動**：
   ```bash
   # 查看當前開機登入自啟狀態
   ./bin/padpilot-cli autostart status

   # 切換開啟 / 關閉
   ./bin/padpilot-cli autostart toggle
   ```

---

## 🗑️ 解除安裝 (Uninstallation)

PadPilot 提供完整的卸載腳本：

```bash
# 標準卸載：停止背景服務、卸載 LaunchAgent、移除 SwiftBar 外掛連結
# （預設保留個人設定檔、日誌與已建立之虛擬螢幕）
./scripts/uninstall.sh

# 徹底清除：完全刪除設定檔、歷史日誌與執行狀態
./scripts/uninstall.sh --purge
```
