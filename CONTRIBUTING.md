# 貢獻指南 (Contributing to PadPilot)

感謝您對 PadPilot 專案感興趣！我們非常歡迎社群的各項建議、錯誤回報與代碼貢獻。

---

## 🛠️ 開發環境準備 (Development Setup)

### 系統需求

- **作業系統**：macOS 14 (Sonoma) 或更高版本（支援 Apple Silicon M 系列）。
- **Python**：Python 3.10+；GUI 測試另需同一環境的 Tk。不要假設 macOS 預裝的 Python 符合版本。
- **依賴工具**：
  - [BetterDisplay](https://github.com/waydabber/BetterDisplay)（建議已安裝並啟用 CLI 工具）
  - Apple Command Line Tools（`xcode-select --install`；編譯 Swift/AppKit 選單）

### 複製專案與檢查

GitHub 倉庫目前為私人。具有存取權限的帳號可先複製，再執行唯讀預檢；已取得原始碼者直接執行最後一步：

```bash
git clone https://github.com/kcayut/PadPilot.git
cd PadPilot
./scripts/install.sh --check
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

### 3. 建置原生選單

```bash
python3 scripts/build_app.py
open build/PadPilot.app
```

單元測試包含實際編譯 AppKit 選單與三種語言資料契約，不會控制顯示器。開啟 App 會啟動既有 Python 服務；完整設定視窗仍使用 Tk。

### 4. 機敏資訊與路徑掃描

切勿將個人的 Home 目錄、區域網路 IP、真實 iPad 序號或金鑰提交至 Git：

```bash
python3 scripts/check_release.py --scan-only
```

會掃描目前非忽略文字檔與所有本機分支的歷史差異；`build/privacy-scan.json` 僅列類型與位置，不列出匹配值。維護者已接受的 6 筆歷史路徑，依完整 commit、檔案與類型列於 `scripts/check_release.py`，報告保留於 `accepted_history`。例外不適用於目前檔案、新提交、其他檔案或憑證。這是有限模式掃描，不是「完全沒有機密」的保證，仍需人工複核。不要直接公開原始掃描日誌或改寫共享歷史。

有桌面工作階段時，可執行 `python3 scripts/check_release.py --gui` 一次跑完單元、Shell、plist、版本、GUI 與隱私關卡；歷史仍有待審匹配時會以非零結束，報告可區分軟體測試成功與公開尚未就緒。最低 Python／macOS 與真實無頭情境需另行驗證，不能由目前機器推定。

GitHub Actions 將 macOS 的 Python 3.10／3.14 軟體檢查與 Linux 的完整歷史隱私檢查分開顯示。`--software-only` 只決定軟體測試結果，仍保留隱私待審資訊，不是發布許可；獨立的 `Release privacy gate` 會阻擋未審核匹配。GUI 真實版面與物理硬體仍是本機手動發布關卡。CI 不安裝 BetterDisplay、不啟動 PadPilot，不建立 tag／Release。

---

## 📐 程式碼風格與架構原則

「關於」頁的贊助收款網址由維護者在 `core/gui.py` 的 `DONATION_URLS` 填入；空字串代表尚未開放，按鈕停用且不開啟外部網站。僅填入已確認屬於專案維護者的 HTTPS 收款連結；這是外部連結入口，不在 App 內收集付款資料或串接付款 API。

1. **零重量外部套件依賴**：`core/` 模組原則上僅依賴 Python 標準庫以及系統自帶的 `ctypes`、`subprocess`、`tkinter`。
2. **非侵入式與狀態自癒**：任何背景操作失敗時，必須遵循 Cooldown 與 Fallback 機制，不可引發無窮迴圈或癱瘓系統顯示器。
3. **原子性狀態寫入**：狀態必須透過原子寫入更新至 `status.json`，供原生選單與 GUI 讀取，嚴禁在 Menu Bar 觸發高成本硬體掃描。

---

## 🚀 Pull Request 流程

目前私人倉庫需要存取權限；Pull Request 不代表正式發布。公開前仍需完成隱私與實機驗收。

1. Fork 專案至您的個人帳號。
2. 從 `main` 分支建立特性分支（例如 `feature/awesome-idea` 或 `fix/sidecar-timeout`）。
3. 撰寫清晰且具備說明性的 Git Commit Message。
4. 建立 Pull Request，並依據 `.github/pull_request_template.md` 勾選相應的檢查清單。
