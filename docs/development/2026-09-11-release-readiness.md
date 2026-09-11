# 0.1.0 Early Preview：P0／P1 驗收

[開發紀錄索引](README.md)

日期：2026-09-11。範圍為 GUI 版本、安裝可靠性、本機安全與文件；GitHub 建倉、Actions、remote、分支保護、tag、Release 及公開安全通報管道依要求略過。版本仍為 `0.1.0`，不宣稱 stable。

後續更新：維護者已建立私人 GitHub 倉庫，原始碼與 CI 已上傳；原 `origin` 保留，另設 `github` 遠端。`.github/workflows/ci.yml` 分開執行 macOS/Python 3.10、3.14 軟體測試及 Linux 完整歷史隱私關卡。[首次修正後的 CI](https://github.com/kcayut/PadPilot/actions/runs/34508708985) 兩個 Python 工作均通過，包含原生 App 建置；當時為 163 項測試。3.10 的失效連結測試已改為直接檢查連結與指向。該次隱私報告為 tree=0、history=6；維護者隨後接受這 6 筆低風險歷史路徑，精確例外與新匹配的界線見下方。後續結果以 [GitHub Actions](https://github.com/kcayut/PadPilot/actions/workflows/ci.yml) 為準。

以下「GitHub 略過」描述保留原輪次範圍，不代表倉庫現在仍不存在。目前方案的私人倉庫分支保護由 GitHub 回覆需升級 Pro；未升級或改成公開。公開安全通報、tag／Release 尚未設定。

## 清單狀態

| 項目 | 狀態 | 結果／剩餘條件 |
| --- | --- | --- |
| GUI 版本 | 已實作 | 「關於」頁讀取 `core.__version__`，與 CLI、App 建置共用；三語與 840px 版面檢查。 |
| P0-1 安裝路徑 | 已實作 | 唯讀 `--check`、Tk 可選、必要依賴失敗停止、共享 autostart、握手與失敗回復。 |
| P0-2 本機安全 | fixed | 私人權限、IPC payload 不入日誌、安全 fallback 讀寫／清理、只停止已驗證的自身工作與程序。 |
| P0-3 發布關卡 | 本機與 CI 已實作 | 單元／Shell／plist／版本／GUI、ResourceWarning、tree／history 隱私掃描；Python 3.10／3.14 CI 通過，macOS 14 與實機仍待驗。 |
| P0-4 實機無頭驗收 | unknown | 下方所有物理情境仍需操作與證據，不以模擬測試代替。 |
| P1 文件 | 已同步 | 三語 README 與 docs、語言導覽、GUI 對應文件、安裝／更新／回復／解除安裝、限制與驗收表。 |

`scripts/check_release.py --gui` 產生 `build/release-check.json` 與各項檢查日誌；`--scan-only` 只做隱私模式掃描。報告不含匹配值。任何軟體關卡失敗或隱私匹配尚待複核，均回傳非零結束碼；真實硬體與最低版本未驗收時 `stable_ready` 一律為 false。

## 最初驗證紀錄

本輪 162 項單元測試全數通過，未出現 ResourceWarning；三語 GUI、840px 版面與焦點／草稿／捲動保留、原生選單契約、Shell、plist、版本一致性及 `git diff --check` 均通過。結果記於本機 `build/release-check.json`；總關卡因歷史隱私待審而回傳 1，並非程式測試失敗。

本機實際安裝與重複安裝均成功：一個 daemon、一個原生 App，已驗證載入的自身 LaunchAgent、socket 握手、安裝 App 的簽署與版本。重複安裝前後主設定檔 SHA-256 相同，配對與偏好未變。設定／runtime／日誌目錄為 `0700`，設定、狀態、socket 與三個使用中日誌檔為 `0600`。舊 App 移到垃圾桶可復原。這是現有開發機驗證，不是乾淨新機或無頭冷開機驗證。

| 環境／情境 | 證據狀態 |
| --- | --- |
| Apple Silicon arm64、macOS 26.6.2、Python 3.14.6、Tk 9.0 | 本輪開發／GUI／編譯環境；不是完整無頭硬體相容認證。 |
| Python 3.10 最低執行環境 | 已納入 macOS 15 arm64 CI，最新軟體結果見 Actions；GUI 真實版面與實機仍未驗收。 |
| macOS 14 最低執行環境 | 編譯目標為 14.0；未在該系統實跑，unknown。 |
| Intel Mac、其他 macOS／Tk 組合 | 未實跑，unknown。 |
| Tk 缺失、安裝失敗、啟動回復、解除安裝範圍 | 暫存使用者目錄與假外部程序測試；不代表乾淨新 Mac 全流程驗收。 |

## 安全修復摘要

結果：`fixed`（限定本輪 P0-2 邊界，不代表完成全專案安全認證）。

- **信任邊界**：其他本機使用者可能預建 `/tmp/PadPilot`；IPC 配對 payload 可能含 UUID／序號；同名 LaunchAgent／CLI 連結或程序不一定屬於此 checkout。
- **原風險**：狀態目錄／檔案權限未明確限制、完整 IPC payload 進日誌、fallback 讀取與停止清理可跟隨連結、過廣的程序名稱停止方式。
- **共享修復**：`core/storage.py` 驗證所有者、檔案型態與連結，目錄 `0700`、檔案 `0600`，原子寫入；GUI／選單／CLI／daemon 走同一儲存路徑保護。socket 拒絕覆蓋仍在使用的端點。
- **命令與生命週期**：已知 IPC 命令名稱白名單，不記錄 payload／未知原文；停止前驗證磁碟 plist、已載入 job 的來源／參數、Python 程序與腳本位置。安裝、CLI 與 GUI 共用 autostart。新子程序握手失敗會終止並回收；登入啟動失敗嘗試恢復原設定及執行狀態。
- **獨立複查修正**：fallback 狀態清理、隱藏選單標記、新程序失敗清理，以及停止舊服務後的失敗回復均補上回歸測試。
- **合法行為保留**：JSON 與 legacy IPC、配對交易、正常狀態讀寫、stale socket 取代、停用登入啟動後的當次服務、三語選單與 GUI 保留。`--check` 不修改狀態；缺少 Tk 不阻擋核心服務。
- **證據**：`tests/test_release_safety.py`、`tests/test_install_check.py`、`tests/test_menu_pairing.py`、`tests/test_autostart.py`、`tests/test_native_app.py`，以及真實 Tk 版面／語言檢查。
- **範圍限制**：不防禦同帳號已任意執行程式或 root；不改寫舊日誌／Git 歷史，不宣稱所有錯誤日誌都已去識別。掃描只覆蓋有限文字模式，非完整機密偵測。

## 公開前隱私與發布待辦

先前 tree 未命中所列機密模式；Git 歷史有 6 筆 `private_path` 匹配，是早期 README、安裝器與 LaunchAgent 中同批路徑的新增／刪除紀錄，不是 6 組憑證。2026-09-11 維護者已審閱並接受本機帳號名稱、專案及日誌位置公開的風險；保留歷史，不進行清理或改寫。

例外只適用於 `4c7642471fc316991ff8e0ab1ec678e347ce7ed4` 與 `fc53785b1d385d21aac6e8f9d93f4638b0f348ab` 的指定檔案與 `private_path` 類別，列於 `scripts/check_release.py`。報告的 `accepted_history` 保留已審核位置；`tree` 與 `history` 仍代表未豁免匹配。新提交、不同檔案、憑證類別及目前檔案皆不受例外影響。若發現真正憑證，先撤銷或輪替再處理歷史。接受路徑不等於公開倉庫、建立 tag／Release 或通過實機驗收；`SECURITY.md` 的私密通報流程仍未啟用。

三語文件與例外後續驗證：167 項本機測試通過，三語 GUI 文件／診斷說明實際點擊導向、840px 版面與既有狀態保留檢查通過；tree=0、history=0、accepted_history=6。此結果不是實機無頭驗收，也不代表已將本輪修改推送至 GitHub。

本機 App 仍引用外部 Python 與原始碼，只有 ad-hoc 本機簽署；Developer ID、Apple 公證、DMG、內含 Python、自動更新均未納入此輪。

## P0-4 實機驗收表

先記錄 Mac／macOS／iPadOS、線材／hub、BetterDisplay 版本及配對方式，並保留實體螢幕或預先可用的遠端救援。不要為了通過測試關閉 FileVault；登入前畫面不在支援範圍。

| 操作 | 預期 | 狀態 |
| --- | --- | --- |
| 拔除實體螢幕後冷開機、登入 | 自動 Sidecar、指定 iPad 成為主螢幕；登入前不要求畫面 | unknown |
| USB 插入／拔除 | 喚醒既有評估，無重複連線或失控重試 | unknown |
| 睡眠／喚醒 | 狀態恢復、無持續切換 | unknown |
| Sidecar／BetterDisplay 重啟 | 偵測失敗並恢復，重試受冷卻限制 | unknown |
| iPad 連線失敗 | 保留 `PadPilotVirtual` 備援 | unknown |
| 兩台候選 iPad、未指定有效目標 | 不猜測、不自動連線 | unknown |
| 接回實體螢幕 | 自動模式穩定返回實體主螢幕 | unknown |

每項保留操作前／後與穩定後的 `padpilot-cli status --json`、相關日誌片段、時間戳及實際看見的螢幕結果。原始證據含私人資訊，存於本機忽略的 `build/` 或其他私人目錄；去識別後才能公開。程式不會代替使用者拔線、睡眠或重開機。

## 最後審查後的修復（2026-09-11）

已修復安裝器停止前狀態未納入回復、主／備援設定讀取不一致、損壞設定默默啟用自動控制、Sidecar 顯示身分誤判、同次 identifiers 錯誤被覆蓋、GUI 設定未送版本、purge 遺漏備援設定、FileVault 診斷判定、卸載腳本漏檢及虛擬螢幕提示插值；PR 範本也改用既有隱私關卡。三語安裝、架構與疑難排解已同步。設定路徑會換行，避免長路徑超出最小視窗。

178 項單元測試通過，無 ResourceWarning；840px 元件／焦點／草稿／捲動保留與三語 GUI 檢查通過。安裝失敗回復使用暫存使用者目錄與模擬服務，涵蓋原本由 launchd 執行、獨立執行、已停止三種情境；未操作實際安裝與服務。兩份 Shell 分別檢查、plist、版本、diff 檢查通過；隱私結果 tree=0、history=0、accepted_history=6。原始碼修改尚未部署或推送。

完整 `check_release.py --gui` 已在隔離使用者目錄下通過；34 份受版本控制的 Markdown 無失效本機連結。唯讀查詢確認 GitHub 倉庫仍為 private，私密通報 API 回傳 404，未取得有效入口的證據。

安全通報文件已移除未啟用入口與未確認聯絡方式的指示；可公開的維護者信箱或有效私密通報網址仍待提供，因此通報管道與正式公開仍未就緒。macOS 14、實機無頭及其餘物理驗收維持 `unknown`；`stable_ready` 仍為 false。
