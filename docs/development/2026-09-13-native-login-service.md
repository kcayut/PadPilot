# 原生登入服務與拖入垃圾桶移除

## 範圍

尚未公開發行，依維護者要求不實作舊版遷移，也不新增 GUI 解除安裝按鈕。此工作沒有安裝新版到 Applications、停止既有 PadPilot，或清除本機舊 LaunchAgent。舊開發安裝需由維護者自行清理；安裝器遇到殘留外部 LaunchAgent 會停止，不會接管。

## 實作

- `SMAppService.agent` 管理 `Contents/Library/LaunchAgents/com.padpilot.daemon.plist`；`BundleProgram` 指向 App 內原生執行檔，不把 Python／來源的絕對路徑寫成外部登入設定。
- 原生入口解析內建／外部 Python，使用 `execv` 讓 launchd 追蹤真正的背景程序。`KeepAlive.SuccessfulExit=false`：正常結束不重啟，異常退出重啟；登入註冊仍保留。
- App 在垃圾桶、磁碟映像或 App Translocation 路徑時不啟動背景 Python。啟動條件永久失敗時，背景入口安靜正常退出，不顯示警告視窗或反覆重試。
- 首次啟動保留預設登入註冊；用 `login_service_initialized` 避免之後因偏好仍為 true，覆蓋使用者在系統設定的停用選擇。GUI、選單與診斷讀取系統狀態；等待允許時提供開啟系統登入項目的入口。
- 同 bundle ID 的不同 App 副本查詢可得到相同的 SMAppService 狀態，因此以私有的 `login-service.json` 記錄註冊所屬 App 路徑，避免另一份安裝解除註冊或重新啟動目前服務。這是被動資料，不是另一個登入項目。
- 原始碼及 Release 安裝器在替換前解除註冊，保留原本已啟用的設定，失敗時嘗試復原。等待允許／被系統停用的項目不自動重新申請。明確啟動已註冊但停止的服務時重新註冊，也更新替換後執行檔的註冊。
- 既有 CLI／腳本解除安裝保留為可選的資料清理工具；先停止及確認解除註冊，再將 App 移到垃圾桶。解除註冊失敗會保留 App，避免留下無法解除的工作。

## 實測證據

測試環境為 Apple Silicon、macOS 26.6.2、Python 3.14。所有服務整合測試使用隨機 bundle ID 的臨時副本與無硬體操作的背景測試程式，完成後解除註冊並移除測試副本。

- ad-hoc 簽章的 App 可以註冊並啟動背景 Python，不需要為此加入 Developer ID 憑證。
- 全新服務的原生狀態實際可能是 `notFound`，不是只有 `notRegistered`；先確認內嵌檔案存在，再允許第一次註冊。
- 本機 `launchctl print` 的原生工作來源是 `submitted by smd`，並提供 `managed_by`、`parent bundle identifier` 與相對 `program identifier`，不是外部 plist 的路徑。
- 正常 SIGTERM 結束沒有自動重啟，登入註冊仍是 enabled；重新註冊能再次啟動；SIGKILL 後能自動重啟。
- 使用 macOS 原生檔案 API 將測試 App 移入真正垃圾桶，沒有清空垃圾桶。此時 SMAppService 狀態仍可能是 enabled，甚至 kickstart 可回報成功，但背景 Python 沒有再啟動。這支持保留垃圾桶路徑防護，不能聲稱系統登入項目會立即消失。
- 同時完成原始碼 App 與完整內建 Python Release App 的服務測試；完整 Release 通過搬移至含空白路徑、CLI／JSON、內建與外部 Python 切換、外部 Python 消失後復原，以及簽章完整性檢查。
- 原生 GUI 版面與三語檢查通過。軟體回歸與安裝腳本檢查的最終結果見本次 `build/release-check.json`；測試替身已改用原生狀態，避免依賴本機是否存在建置成果。

重現原生服務與垃圾桶驗證（使用已建置的 App，不會操作這份 App 本身）：

```bash
python3 scripts/check_login_service.py --app build/PadPilot.app --trash
```

需在可使用登入工作階段的 macOS 環境執行。測試需能存取垃圾桶；若系統拒絕臨時服務註冊或解除註冊，會明確失敗，解除註冊失敗時保留測試 App 供清理。

## 尚未驗證

沒有重開或登出維護者的電腦，也尚未在 macOS 14／15 驗證真正的登出、登入與重新開機。上述隔離測試不能替代這些驗收；系統登入項目紀錄的清理時間仍由 macOS 決定。設定、配對與日誌預設保留，無需為了移除登入啟動而刪除它們。

## 參考

- [Apple：SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice)
- [Apple：更新安裝器以採用 Service Management](https://developer.apple.com/documentation/servicemanagement/updating-your-app-package-installer-to-use-the-new-service-management-api)
- 本機 SDK 的 `SMAppService.h` 與 `launchd.plist` 手冊；API 文件另以 Context7 查證。

## 後續實機診斷：2026-09-13

維護者自行清除舊安裝並回報 iPad 無法連線後，檢查結果如下；這些是後續觀察，不屬於上方隔離測試的驗收結果。

- `/Applications/PadPilot.app`、`~/Applications/PadPilot.app`、`~/bin/padpilot-cli` 與外部 `~/Library/LaunchAgents/com.padpilot.daemon.plist` 均不存在；使用者及系統 LaunchAgents／LaunchDaemons 目錄未發現 PadPilot 項目。原生登入服務指向專案 `build/PadPilot.app`，Python 背景程序及 IPC 握手正常。
- 設定中的 Sidecar 目標與即時探索 UUID 一致。無線與後來接上的 USB 都能探索同一台 iPad，但建立 Sidecar 工作階段失敗。USB 嘗試的系統紀錄顯示 `Direct` 傳輸，而不是只看 USB 偵測推測傳輸方式。
- 脫離 PadPilot 背景程序直接執行相同 BetterDisplay 命令，仍失敗。將單次命令等待上限延長到 55 秒後，BetterDisplay 仍自行於約 10.11 秒回傳結束碼 1；macOS 對應紀錄為 `SidecarErrorDomain (-201)`。不能將此錯誤碼自行解讀成特定硬體或權限故障。
- macOS 顯示器設定也未能建立 iPad 顯示器；重啟 BetterDisplay 後仍失敗。目前證據不足以認定為 SMAppService 回歸，也尚未證明 iPad 連線已恢復；繼續以停止 PadPilot 的原生連線及 iPad 重開機交叉驗證。

後續結果：維護者重新啟動 iPad、接上 USB 並解鎖後，01:28 的原生 Sidecar 連線成功，系統出現 iPad 顯示器。恢復同一份 `build/PadPilot.app` 的 SMAppService 服務後，再由 PadPilot 的 `reconnect_sidecar` 流程完成已確認的斷線、連線及外接螢幕主畫面設定；約 1 秒內 BetterDisplay 連線命令成功，USB 與 Sidecar 均顯示 Connected。此次未修改連線實作；結果較支持暫時的 Sidecar 工作階段問題，不能僅依錯誤碼判定精確原因，也未追加無線或下一次重新開機驗收。

### 再次重新開機後的啟動失敗與修正

維護者再次重開 Mac 後，01:32:28 出現 `Daemon handshake failed`。此輪的證據與前一次不同：BetterDisplay 的 `help`、`get -identifiers`、`get -sidecarList` 全部逾時，程序列表只有短暫的 CLI 執行個體，沒有 BetterDisplay GUI 主程式。daemon 直到 01:32:29 才開始監聽 IPC，晚於啟動驗證期限。

根因是 `ensure_betterdisplay_running()` 以 `pgrep -f BetterDisplay` 判斷主程式是否執行；登入時其他 PadPilot 查詢會啟動同名 CLI 執行個體，造成誤判。另外，原本在初始化及 IPC 啟動前等待外部能力探測與虛擬顯示器查詢，將依賴的延遲誤報為 daemon 啟動失敗。

- 精準比對所選 BetterDisplay 執行檔「沒有 CLI 參數」的 GUI 程序；存在時沿用，不存在時以 `open -g -n -a` 建立 GUI 執行個體。保留使用者設定的 App 路徑。實機發現僅移除原判斷並改成 `open -g -a` 仍會讓 LaunchServices 沿用正在等待的 CLI 執行個體，因此需要在確認 GUI 不存在後使用 `-n`。
- daemon 建構時不探測 BetterDisplay 能力；先提供真實 IPC 握手，再開啟依賴及查詢硬體。握手只確認服務與所屬專案，Sidecar 是否完成仍須工作階段與實際顯示器同時上線。
- 增加真實 Unix socket 回歸測試：阻塞 BetterDisplay 能力探測時，daemon 仍能完成握手；原有自訂 App 路徑測試加入 CLI 執行個體不能阻止主程式啟動的檢查。

本輪在不重開 iPad 的情況下，正常開啟 BetterDisplay 後，原服務已完成無線 Sidecar 連線，`sidecar_connected` 與 `sidecar_display_online` 同為 true，且無硬體查詢錯誤。這補足上一段「無線尚未驗收」的限制；不能將上一次恢復直接視為下一次開機已通過。

最終修正以真實程序重現同一競態：先斷開 iPad、停止 PadPilot、結束 BetterDisplay，確認 GUI 不存在後保留一個正在等待的 CLI 查詢，再啟動原生登入服務。握手於約 0.44 秒完成，GUI 即使在 CLI 存在時仍成功啟動，新查詢成功，PadPilot 完成無線重連。最終即時狀態為握手成功、`sidecar_connected=true`、`sidecar_display_online=true`、`discovery_errors={}`，登入註冊仍 enabled。原始碼 App 已載入修正版 Python；不將這個程序啟動實測宣稱為修正後的完整 Mac 重新開機驗收。

## Release 拖拉移除驗收與後續修正

維護者後續已確認：Mac 重新開機、沒有實體螢幕時，手動模式的開機連線能使用無線 Sidecar，並將 iPad 設為主螢幕。這是維護者回報的實機驗收，補充前述尚未重新開機的限制。

以真正含 Python 的 Release 封裝重新檢查移除時，發現僅檢查垃圾桶路徑並不足以主動解除註冊。原版測試只驗證 Python 沒有重啟；提高檢查至服務註冊消失後可重現失敗。嘗試在垃圾桶內的原生入口取消註冊仍不足：launchd 可能在入口執行前就以 EX_CONFIG 拒絕啟動，不能假設下次登入會執行 App 的清理程式。

因此調整原生登入服務：以子程序啟動 Python，並使用系統檔案事件監看 App 本身，取代此文件初版的 `execv`。Python 正常結束後不重啟，原生監看仍保留，沒有輪詢或硬體操作；Python 異常結束時由既有 launchd 規則重啟。App 移入垃圾桶或被刪除時，停止子程序並解除 SMAppService 註冊，原生服務隨之結束。解除註冊從背景佇列進行，避免等待自身終止時阻塞 SIGTERM 處理。

驗收包含：

- 原始碼 App 及含 Python 的 Release App 使用隔離 bundle ID／服務名稱，均通過註冊、正常結束不重啟、重新啟動、異常恢復，以及不呼叫額外清理指令的垃圾桶移除。
- 移入垃圾桶後 `launchctl print` 回傳工作不存在、SMAppService 回報 `notRegistered`，且原工作無法再 kickstart。
- 另從 Finder 將隔離 Release 測試 App 移到垃圾桶：沒有因原生監看而阻止移除，登入註冊與測試 Python 都自動結束。測試資料已清理，未清空使用者垃圾桶。
- 空白設定的 Release App 使用自身內建 Python，預設為 `manual_only`、`connect_on_boot=true`、`autostart_on_login=true`。
- 完整封裝通過搬移至含空白路徑、CLI／GUI 資料、內建及外部 Python 選擇、遺失 Python 復原及簽章驗證。本機既有服務與測試 App 共享標準 Label，須在測試期間暫時解除本機註冊，完成後已恢復 enabled 與握手；不是放寬正式版的安裝所屬檢查。
- 232 項軟體測試，以及 install／uninstall／release install／bootstrap 腳本、plist、diff 檢查均通過。

系統設定中的歷史名稱仍可能由 macOS 延後清理，這與服務已取消註冊不同。上述測試不涉及發布 Release，也沒有重開維護者電腦來重新驗收調整後的原生父子程序啟動。

開發機原地重建 ad-hoc App 時，仍執行舊二進位的選單可能使系統保留舊啟動簽章要求。本次結束舊選單並重新註冊後恢復；正式安裝／移除腳本仍應先停止舊程序與解除註冊再替換 App。
