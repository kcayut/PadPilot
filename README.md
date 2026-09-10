# 📱 PadPilot

<p align="center">
  <b>繁體中文</b> | <a href="#-english-readme">English (coming soon)</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-lightgrey.svg" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/status-early%20preview-orange.svg" alt="Status: Early Preview">
</p>

**Mac mini + iPad 自動螢幕管理系統 (Headless Display State Manager)**

PadPilot 是一套專為 Mac mini 與透過 USB-C 連接的 iPad 所設計的智慧顯示器管理系統。系統以「**實體螢幕優先、手動操作絕對優先、狀態全透明、Headless 備援長期保留**」為核心原則，在無實體螢幕時自動將指定 iPad 轉為主要顯示器；而在接有實體螢幕時以實體為主、已連線的 iPad 為副螢幕，並透過 macOS Menu Bar 與卡片式 GUI 提供直覺、即時的控制介面。

---

## 🧭 決策邏輯 (Decision Flow)

```text
Physical display?
   │
   ├─ Yes → leave Sidecar alone (實體螢幕為主，iPad 維持一般平板或手動副螢幕)
   │
   └─ No
       ├─ USB iPad → Sidecar → Main Display (無實體螢幕，自動將 iPad 設為主螢幕)
       └─ No iPad → BetterDisplay virtual fallback (無 iPad，啟動虛擬螢幕供遠端救護)
```

---

## ⚠️ 重要系統需求與物理限制 (Requirements & Limitations)

在開始使用前，請特別留意以下系統限制：

1. **macOS 專用**：針對 Apple Silicon (M1/M2/M3/M4) 架構之 Mac mini、Mac Studio 等設備設計。
2. **Sidecar 必須處於使用者登入會話中 (Logged-in User Session)**：
   > [!WARNING]
   > **PadPilot cannot turn the iPad into a FileVault / pre-login display.**  
   > （PadPilot 無法讓 iPad 成為 FileVault 開機解鎖或登入前的畫面）。  
   > Apple 的 Sidecar 是系統使用者層級服務。如果您的 Mac 開啟了 FileVault 全磁碟加密，開機尚未輸入密碼前無法自動連線 iPad。若您希望達成外出「無螢幕冷開機、插上 iPad 直接進入系統」，**請關閉 FileVault 並開啟 macOS 自動登入**（詳細說明請見 [疑難排解手冊 - FileVault](docs/TROUBLESHOOTING.md#filevault)）。
3. **輔助工具依賴**：
   - **[SwiftBar](https://github.com/swiftbar/SwiftBar)**：用於 macOS Menu Bar 選單與動態圖示整合。
   - **[BetterDisplay](https://github.com/waydabber/BetterDisplay)**：提供底層 Sidecar 調度與無頭虛擬螢幕（Virtual Screen）備援。
4. **Apple 原生 Sidecar 先決條件**：Mac 與 iPad 需登入相同 Apple Account，且雙方之 Wi-Fi 與藍牙必須維持開啟。初次以傳輸線連接時，請在 iPad 點擊「信任這部電腦」。

---

## 🌟 核心特性 (Key Features)

- **自動情境接管**：
  - **外出 / Headless 模式**：Mac mini 未連接任何實體螢幕時，自動建立 Sidecar 連線並將指定 iPad 設為主要顯示器（Main Display）。
  - **桌機日常模式**：接有 HDMI / DP / USB-C 實體螢幕時，自動化保持靜默，不擅自啟動 Sidecar。
- **手動操作絕對優先 (User Override)**：
  - 使用者隨時可從 Menu Bar 選擇「作為副螢幕」或「設為主螢幕」。
  - 導入 **Topology Generation（拓撲世代碼）** 機制：手動決策會綁定當前硬體世代，只要實體線路未發生實質插拔改變，自動化絕不推翻使用者的決定。
- **單飛行狀態轉換鎖 (Single-Flight Transition Lock)**：
  - 防止 USB 插入、螢幕喚醒、定時輪詢併發觸發多次 Sidecar 連線，保障連線不發生 Race Condition。
- **連線防抖與冷卻保護**：
  - **4 秒瞬斷防抖 (Debounce)**：實體螢幕切換訊號源或瞬斷時啟動防抖，恢復後取消切換，避免誤觸連線。
  - **重試與冷卻 (Cooldown)**：Sidecar 連線失敗自動重試最多 3 次（間隔 3 秒）；全數失敗則進入 30 秒冷卻保護期，避免連線風暴。
- **Headless Fallback 虛擬螢幕**：
  - 整合 BetterDisplay 虛擬螢幕（預設 `PadPilotVirtual`）。無實體螢幕且 Sidecar 異常時，虛擬螢幕提供穩定的 Framebuffer 供 Screen Sharing / VNC / SSH 救援。
- **極致輕量 Menu Bar (< 5ms)**：
  - SwiftBar 外掛純讀取由背景 Daemon 原子寫入的 `status.json`，杜絕高頻硬體輪詢，CPU 佔用率近乎 0.0%。

---

## ⚡ 快速安裝 (Quick Start)

```bash
git clone https://github.com/kcayut/PadPilot.git
cd PadPilot
./scripts/install.sh
```
*(可帶 `--yes` 自動確認 Homebrew 依賴安裝)*

> 📖 **詳細安裝、相依性與手動配置說明，請參閱 [完整安裝手冊 (docs/INSTALLATION.md)](docs/INSTALLATION.md)**。

---

## 📱 配對您的 iPad

將 iPad 透過 USB-C 連接線插上 Mac，確保兩部設備登入相同 Apple Account，並執行配對精靈：

```bash
./bin/padpilot-cli pair --interactive
```

或開啟圖形化管理面板進行配對：
```bash
./bin/padpilot-cli gui
```

啟動 SwiftBar 即可在頂端選單列看到 PadPilot：
```bash
open -a SwiftBar
```

---

## USB 即時喚醒與免配對自動偵測

位置：**選單列 → 設定與配對 → 運作與偏好 → 進階選項（點擊展開） → USB 與 iPad 自動偵測**。

- **USB 插拔即時喚醒**：預設啟用。原生 IOKit 通知喚醒既有狀態機，不需新增套件。保留 30 秒 Watchdog；啟動與 USB 事件後有最多 30 秒、每 2 秒的探索期，等待 Continuity 裝置出現。實體螢幕防抖與 Sidecar 冷卻仍有效，事件通知不等於毫秒內完成連線。註冊失敗會在診斷中顯示並保留 Watchdog；停用再啟用可重試。
- **自動偵測 iPad（免 PadPilot 配對）**：預設啟用。啟用後需唯一一台可讀取序號的 USB iPad；有已存 USB／Sidecar 對應時優先使用，否則需唯一 Sidecar 候選。查詢失敗、候選未出現或有歧義時不發起 iPad 連線，保留實體／虛擬備援。
- 偵測結果只作為本次執行目標，不新增或改寫配對。**唯一候選是推定，不代表已驗證 USB 與 Sidecar 是同一台裝置**；附近可能有其他 iPad 時，請停用此功能並明確配對。Apple 的帳號、信任及 Sidecar 相容性要求仍適用。
- 本次目標顯示於設定頁及選單列「iPad 控制」；自動偵測啟用時，已存配對卡片的控制按鈕停用，請由選單列操作。拔線後不主動建立無線備援連線。

更新程式後需重啟背景服務一次以載入新版；之後兩個開關可即時套用。若設定頁已開啟，請關閉並重新開啟。

---

## 📊 Menu Bar 狀態與圖示

Menu Bar 外觀會隨系統現況呈現對應圖示：
- `🖥️`：實體螢幕使用中
- `📱`：iPad Sidecar 使用中
- `◻️`：Virtual Display / Headless 備援狀態
- `⚠️`：錯誤、連線中斷或處於冷卻保護期
- `⏸️`：Manual Only 暫停狀態

```text
🖥️ PadPilot
──────────────────────────────
主螢幕：ROG PG279Q
模式：自動｜運作中
──────────────────────────────
螢幕與裝置                  ▶
  目前可用
    ROG PG279Q — 主螢幕      ▶
    iPad — 偵測到 Sidecar 目標 ▶
  ────────────────────────────
  已配對至 PadPilot
    ✓ iPad — 目前控制目標   ▶
  ────────────────────────────
  虛擬備援
    PadPilotVirtual — 已連接
iPad 控制                   ▶
運作模式                    ▶
背景服務                    ▶
設定與配對（開啟 GUI）
狀態與診斷（開啟 GUI）
重新整理螢幕狀態
──────────────────────────────
Exit
```

---

## ⌨️ CLI 命令列使用手冊

PadPilot 提供完整的命令列工具 `padpilot-cli`：

```bash
# 查看當前狀態
padpilot-cli status
padpilot-cli status --json

# 切換工作模式
padpilot-cli set-mode automatic
padpilot-cli set-mode manual_only
padpilot-cli set-mode prefer_ipad

# 觸發手動操作
padpilot-cli action use_ipad_secondary  # 將 iPad 作為副螢幕
padpilot-cli action use_ipad_main       # 將 iPad 設為主要顯示器
padpilot-cli action disconnect_ipad     # 斷開 Sidecar
padpilot-cli action reconnect_sidecar   # 重新連線 Sidecar
padpilot-cli action refresh             # 立即重新掃描拓撲
padpilot-cli action reset               # 清除暫時覆寫與冷卻保護狀態

# 背景服務管理
padpilot-cli stop                      # 停止 daemon
padpilot-cli start                     # 啟動 daemon
padpilot-cli exit                      # 停止 daemon 並移除 Menu Bar 項目
padpilot-cli autostart status          # 查看登入自啟狀態
padpilot-cli autostart toggle          # 切換登入自啟開關

# 查看版本與日誌
padpilot-cli --version
padpilot-cli open-log
```

---

## 📚 延伸說明文件 (Documentation)

- [🛠️ 安裝與相依性指南 (docs/INSTALLATION.md)](docs/INSTALLATION.md)
- [🩺 疑難排解與常見問答 FAQ (docs/TROUBLESHOOTING.md)](docs/TROUBLESHOOTING.md)
- [🏛️ 系統架構與設計原理 (docs/ARCHITECTURE.md)](docs/ARCHITECTURE.md)
- [📜 開發歷程與技術評估紀錄 (docs/development/)](docs/development/)

---

## 🤝 參與貢獻 (Contributing)

歡迎提交 Issue 與 Pull Request！
請在貢獻前閱讀 [貢獻指南 (CONTRIBUTING.md)](CONTRIBUTING.md) 以瞭解環境建立與測試規範。

如欲回報安全相關漏洞，請參閱 [安全政策 (SECURITY.md)](SECURITY.md)。

---

## 📄 授權條款 (License)

本專案基於 [MIT License](LICENSE) 授權開源。
Copyright (c) 2026 kcayut.

### 介面語言

在「設定與配對 → 運作與偏好 → 語言」選擇 **中文（繁體）／English／日本語**。選擇會儲存，GUI 與選單列同步切換；舊設定預設保留繁體中文。裝置名稱、識別碼與原始日誌保留原文。更新程式後，請重新開啟設定視窗；已在執行的舊版背景服務需重新啟動一次，才能接收新的語言設定命令。
