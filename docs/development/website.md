# PadPilot 介紹網頁

網站定位為專案介紹、免費下載與自願支持開發。原始碼與 App 下載指向 GitHub；贊助按鈕連到 README 已列出的歐付寶、綠界科技、PayPal 與 Ko-fi，不設付費下載或功能解鎖。

## 編輯與預覽

- `website/template.html`：三語共用版型。
- `website/content.json`：繁體中文、英文、日文文案，欄位必須一致。
- `website/style.css`：桌面與手機版面。
- 圖示、影片、介面截圖與金流品牌圖沿用既有專案素材。

在專案根目錄執行：

```sh
python3 scripts/build_website.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory build/website
```

開啟 `http://127.0.0.1:8765/`。三語入口分別為 `index.html`、`en.html`、`ja.html`。不需 Node.js、套件安裝或執行前端 JavaScript。

建置會檢查三語欄位、所有本機圖片與影片、語言連結及頁內錨點。缺少素材或連結目標時直接失敗。產物位於被 Git 忽略的 `build/website/`。

## GitHub Pages 發布範圍

發布時以 `build/website/` 內的完整內容作為網站產物，不要直接發布整個專案根目錄或 `website/` 模板目錄。所有站內路徑皆為相對路徑，適用於 `/PadPilot/` 專案網站路徑。

這次僅製作本機初稿，未啟用 GitHub Pages、建立部署工作流程、推送或公開上線。外部下載、文件、回報與付款連結沿用 README；發布前仍須確認目標頁面可供一般訪客存取，以及金流帳戶允許此收款用途。

### 2026-09-17：加入自動部署

新增 `.github/workflows/pages.yml`，在 `main` 的網站內容或素材變更時重新建置，也可手動執行。儲存庫的 Pages 來源須設為 GitHub Actions；工作流程只上傳 `build/website/`，部署至 `https://kcayut.github.io/PadPilot/`。上方「本機初稿」段落保留作為當時紀錄，實際部署結果以 GitHub Actions 為準。

## 內容維護

變更版型會同步套用三語；修改文案時須一併更新三種語言。網站未變更軟體授權，仍如實標示 PolyForm Noncommercial 1.0.0，不能將「原始碼公開」改寫成 OSI 開源授權。

實機影片是完成首次設定後的示範，等待段加速 8 倍；介面截圖使用示範裝置資料。保留登入後才運作、FileVault／登入前畫面不支援、早期預覽與未簽署／公證等限制。未加入分析追蹤、表單、第三方程式或付款資料收集。

### 2026-09-18：綠界科技贊助項目加入收款信箱

在 `website/content.json`、`website/template.html` 與 `website/style.css` 統一在綠界科技區塊標註收款信箱 `kcayut@gmail.com`，樣式與排版規則與歐付寶會員編號保持一致。

