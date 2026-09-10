# USB 事件喚醒與免配對自動偵測

**繁體中文** | [English](2026-09-10-usb-discovery.en.md) | [日本語](2026-09-10-usb-discovery.ja.md) · [開發紀錄索引](README.md)

> 歷史紀錄：下表為初版預設與行為。現行自動偵測預設啟用，且優先使用明確指定配對；以[目前架構](../ARCHITECTURE.md)為準。

已加入設定頁的「USB 與 iPad 自動偵測」卡片，沿用既有 GUI → CLI → IPC → 設定交易及狀態機。

| 開關 | 預設 | 行為 |
| --- | --- | --- |
| USB 插拔即時喚醒 | 啟用 | IOKit first-match／terminated 回呼喚醒既有評估迴圈；保留探索期、防抖、冷卻與 Watchdog。 |
| 自動偵測 iPad | 關閉 | 唯一 USB iPad，優先已存對應，否則要求唯一 Sidecar 候選；目標只存於觀察狀態。 |

控制選單顯示本次目標；自動偵測時已存配對卡片的控制停用，避免舊標籤操作另一台裝置。設定變更等待既有轉換釋放評估鎖後套用。沒有新增外部套件。

## 驗證

- `python3 -m unittest discover -s tests`：115 項通過，包含 11 項新增測試。涵蓋設定值驗證、CLI／IPC 派送、原生監聽註冊與停止／重啟、註冊失敗退回 Watchdog、事件喚醒原有迴圈、無配對唯一候選、已存對應優先、歧義與查詢失敗不連線、候選身份變更、主螢幕目標派送、手動模式及冷卻。
- `python3 scripts/check_gui_layout.py`：840px 視窗通過；兩個開關完整顯示且按鈕送出正確設定；自動偵測時已存配對控制停用。
- `git diff --check`：通過。
- 本機原生 IOKit 註冊、停止與重啟成功。08:23 重啟既有 LaunchAgent 後，日誌確認 `Native USB notifications active`，新版狀態包含 `resolved_ipad`，無偵測錯誤。
- 保留使用者「僅手動」模式、配對及 ROG PG279Q 主螢幕；沒有啟用免配對自動連線。

## 限制

唯一 USB 與唯一 Sidecar 候選是推定，不構成同一硬體身份的證明；多台 iPad 環境應指定配對。Apple Sidecar 帳號、信任與相容性限制不變。

本次未實際插拔 iPad、換另一台未配對 iPad或拔除實體螢幕冷開機，因此不宣稱已驗收這些物理情境，也不宣稱 Sidecar 可毫秒完成連線。需自動連線者仍要選擇「自動模式」或「偏好 iPad 模式」。
