# 貢獻指南 (Contributing to PadPilot)

感謝您對 PadPilot 專案感興趣！我們非常歡迎社群的各項建議、錯誤回報與代碼貢獻。

---

## 🛠️ 開發環境準備 (Development Setup)

### 系統需求
- **作業系統**：macOS 14 (Sonoma) 或更高版本（支援 Apple Silicon M 系列）。
- **Python**：Python 3.10+（系統自帶或 Homebrew Python 均可）。
- **依賴工具**：
  - [BetterDisplay](https://github.com/waydabber/BetterDisplay)（建議已安裝並啟用 CLI 工具）
  - [SwiftBar](https://github.com/swiftbar/SwiftBar)（用於 Menu Bar 介面開發）

### 複製專案與檢查
```bash
git clone https://github.com/kcayut/PadPilot.git
cd PadPilot
```

---

## 🧪 測試與驗證 (Testing & Validation)

在提交任何 Pull Request 之前，請務必確保本機通過所有測試套件：

### 1. 執行單元測試
```bash
python3 -m unittest discover -s tests -v
```
*所有測試必須通過（exit code == 0）。*

### 2. 驗證 GUI 視窗佈局
PadPilot 堅持使用無第三方依賴的 Tkinter 原生 Card UI。請確保視窗在 `840x500` 最小尺寸下各項按鈕與元件對齊良好：
```bash
python3 scripts/check_gui_layout.py
```

### 3. 機敏資訊與路徑掃描
切勿將個人的 Home 目錄、區域網路 IP、真實 iPad 序號或金鑰提交至 Git：
```bash
git grep -nE '/Users/|kcayut@|192\.168\.|10\.[0-9]+\.[0-9]+\.[0-9]+'
```

---

## 📐 程式碼風格與架構原則

1. **零重量外部套件依賴**：`core/` 模組原則上僅依賴 Python 標準庫以及系統自帶的 `ctypes`、`subprocess`、`tkinter`。
2. **非侵入式與狀態自癒**：任何背景操作失敗時，必須遵循 Cooldown 與 Fallback 機制，不可引發無窮迴圈或癱瘓系統顯示器。
3. **原子性狀態寫入**：狀態必須透過原子寫入更新至 `status.json`，供 SwiftBar 毫秒級讀取，嚴禁在 Menu Bar 觸發高成本硬體掃描。

---

## 🚀 Pull Request 流程

1. Fork 專案至您的個人帳號。
2. 從 `main` 分支建立特性分支（例如 `feature/awesome-idea` 或 `fix/sidecar-timeout`）。
3. 撰寫清晰且具備說明性的 Git Commit Message。
4. 建立 Pull Request，並依據 `.github/pull_request_template.md` 勾選相應的檢查清單。
