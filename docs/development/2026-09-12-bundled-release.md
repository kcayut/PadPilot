# Apple Silicon 封裝發行與 GUI 修正

## 實作範圍

- Release 的 Swift 主程式預先編譯；CPython 3.14.7、標準函式庫及 Python 核心放在 App 資源內，不依賴建置電腦的絕對路徑。上游來源與 SHA-256 固定在 `scripts/python-runtime.json`，授權文件保留。
- 原生 GUI、CLI 與 LaunchAgent 共用 Python 選擇；預設內建版本，也可明確指定 Apple Silicon CPython 3.10+。偏好位於 App 外；`--bundled-cli` 可在外部 Python 遺失時復原。GUI 與 Python 共用 HOME 的判定。
- DMG 可拖入 Applications；腳本使用同一個 DMG，不要求先安裝 Python。既有原始碼安裝流程保留。移轉不同安裝位置時，先由舊版解除安裝並保留設定；不接管無法驗證來源的 LaunchAgent。
- BetterDisplay App 必須安裝與執行，獨立 CLI 可省略。共用偵測涵蓋標準位置與 LaunchServices，自訂路徑優先。
- 推送受支援的 tag 後，自動檢查、編譯、建立 DMG／ZIP／校驗碼，附件全部上傳後公開 prerelease。已公開版本不覆寫。僅 ad-hoc 簽章，沒有 Developer ID 或 Apple 公證。
- GUI 側邊欄固定 200px，沒有收合或拖曳分隔控制；視窗標題固定為 PadPilot。展開選項加上外框並擴大整個按鈕的點擊範圍，選取式下拉選單使用有外框的原生樣式。保留原有設定交易。

## 本機證據

2026-09-12，Apple Silicon／macOS 26.6.2；建置 Python 3.14.6，內建 CPython 3.14.7：

- `python3 scripts/check_release.py --gui`：212 項測試通過，原生版面及三語檢查通過。
- 三語各 7 個頁面，共 21 頁，840px 最小視窗下的內容、展開按鈕及既有互動檢查通過。
- 隱私掃描：目前檔案 0 項、未接受的歷史項目 0 項、既有明確接受的歷史項目 6 項。
- 發行建置與搬移檢查：內建 Python、外部 Python、外部路徑遺失後復原、CLI／JSON、系統 Framework 載入及 App 簽章均通過。
- 產物檢查：SHA-256 核對、DMG 唯讀掛載與 Applications 連結、ZIP 解壓，以及兩種下載格式中的 App 簽章與 CLI 版本均通過。
- 新增回歸涵蓋可搬移路徑與 LaunchAgent 身分、Python 偏好檔案邊界、安裝失敗還原、tag 與腳本參數驗證。

本機 `v0.1.0-dev.1` 僅是產物命名測試，建置資訊的 `dirty: true` 表示含尚未提交的修改；不代表已建立、推送 tag 或公開 GitHub Release。GitHub workflow 已配置，但尚未在遠端執行。

## 尚未完成的驗收

macOS 14 與最低外部 Python 3.10 的實機執行、從網路下載觸發 Gatekeeper 的實際流程、Sidecar 冷開機、USB 插拔、睡眠喚醒及多裝置組合仍為 `unknown`。本次沒有安裝到目前使用者的 Applications，也沒有重啟現有 daemon 或控制實體螢幕。軟體與搬移檢查不代表這些實機情境已通過，穩定版驗收仍未完成。

## 後續版面調整

依使用者後續回饋，恢復原本可調整寬度、可收合的原生側邊欄，移除側邊欄頂端的 PadPilot 字樣；視窗標題與按鈕外框保留。上方固定 200px 的描述及驗證結果代表先前版本。

雙擊 App 時立即開啟控制 GUI 與選單列；重開會重用既有視窗，也能恢復已關閉或最小化的視窗。背景啟動改用 `--menu-only` 與不開啟視窗的 URL 通知，避免登入、CLI 啟動或既有 App 收到背景請求時跳出 GUI。原有服務啟動與設定交易不變。

後續驗證：`check_release.py` 的 213 項測試與其他檢查通過；`check_gui_languages.py` 的三語共 21 頁及互動檢查通過。新增原生 AppDelegate 啟動測試使用隔離 HOME 與替代 CLI，確認一般／背景啟動、GUI 關閉與最小化後重開、背景 URL 不開啟視窗，且重開不重複呼叫服務啟動。

本機 `build/PadPilot.app` 與 `dist/v0.1.0-dev.1` 的 App／DMG／ZIP 已重新建置，搬移、內建／外部 Python 與復原檢查通過；仍未安裝或公開發行。

後續快速預覽：依使用者要求再次取消側邊欄縮放與收合，固定為原本理想寬度 200px，保留清單樣式、內容間距與半透明背景。此次僅編譯 `build/PadPilot.app`，不執行測試、不更新發行包；前述測試結果不涵蓋這次版面調整。

## 後續 CI 解除安裝測試修正

GitHub Actions `34625480754` 的 Python 3.10 作業在檢查垃圾桶中的 CLI 捷徑時失敗；Python 3.14 與隱私作業通過。捷徑已成功移走，失敗原因是 Python 3.10 的含固定檔名 `Path.glob()` 不列出目標不存在的符號連結，並非解除安裝無法找到原路徑。

審查後未採用改寫捷徑歸屬判斷的補丁，保留既有解除安裝邏輯；測試改為列出垃圾桶子目錄，再以 `is_symlink()` 與 `readlink()` 確認捷徑及原目標。自身、原始碼與其他捷徑的區分，以及使用者設定保留的斷言均保留。本次只提交修正，不建立 tag 或發行版本。

本機在 Python 3.10.20 重現舊查詢漏掉斷鏈，修正後解除安裝測試通過；Python 3.10.20 與 3.14.6 各自的 `check_release.py` 均通過 213 項測試及其他軟體檢查。這次未重跑 GUI 或實機驗收。
