# 開發狀態與工作邊界

更新：2026-10-29。本文是目前狀態摘要，歷史聊天、檔名或 TODO 不代表功能完成；修改能力時必須同步本表、實作與測試。

## 本站角色

前台以 FastAPI／Jinja2／HTMX 呈現；登入、發票功能透過 app/clients 呼叫 API。登入（2026-10-28）：POST /login 經 API 建立 v1.3 Session，Session Token 存入 httpOnly cookie `ig_session`；/invoices、/qa 每次經 API /auth/me 核對 Session（routers/auth.py `require_session`），頁首顯示登入者與目前部門；POST /logout 請 API 撤銷 Session 再清 cookie。離線測試通過；2026-10-28 使用者以手機經 START 實測登入成功。電腦上傳（2026-10-29）：/invoices/upload 選取本機 JPG／PNG（10 MB 以內，辨識前縮圖）或單頁 PDF（4 MB 以內，原檔上傳、不旋轉、以 iframe 預覽），之後與手機頁共用同一流程與步驟片段 `_upload_review_steps.html`（data-upload-mode="file"）。手機上傳（2026-10-29）：/invoices/mobile-upload 頁面縮圖（最長邊 2000px JPEG）後經 POST /invoices/mobile-recognize 轉呼叫 API 辨識，依回傳欄位與檢核提醒產生核對表單（課稅別、明細可增刪）並顯示 AI 回傳 JSON；POST /invoices/check-duplicate、POST /invoices/mobile-upload 轉呼叫 API 查重與送出（三者都檢查 Origin，API 錯誤轉 JSON，401 導向登入）；已移除示範資料與離線假成功。核對頁與 AI 辨識值不同的欄位即時標示「已修改」（顯示 AI 原值；新增明細、刪除的 AI 明細另外標示），每次修改記入修改紀錄，確認頁列出修改清單；送出時附明細來源與修改紀錄，由 API 寫入 invoice_field_reviews／invoice_changes 供審核標示。fetch 帶 Accept: application/json，錯誤（含 Session 核對、Origin 檢查、格式錯誤）回 JSON，Session 失效仍導向登入。發票列表、詳情與 /invoices/{id}/flow 仍是示範資料，API 對應端點仍為 TODO；首頁、登入頁與手機 HTTPS 入口可驗證。本站不建立 DB／Storage 模組，也不持有公司機密。本機由 START 以 app.mobile_dev:app 啟動（手機 HTTPS 入口包裝原網站）。

## 共同狀態（三站相同）

| 能力 | 狀態與證據 |
|---|---|
| AI 規範入口 | AGENTS.md（三站架構、共同規則、本站現況）＋ CLAUDE.md 匯入；2026-10-26 已提交並 Push 至 feature/python-web |
| 契約／分層檢查 | scripts/check_project.py + contracts/project-contract.json；只做無副作用靜態分析 |
| 本機三站／手機 HTTPS | InvoiceGuard-STARTUP 的 SETUP.cmd／START.cmd；三站各在自己的 CMD 視窗執行並自動重載本站 app/ 的 Python |
| 本機雲端設定 | START 以 Vercel CLI 讀取 ADMIN／API 各自專案的 Production 設定，把 DATABASE_URL、S3_*、SUPABASE_STORAGE_BUCKET 注入本機該站程序（2026-10-25 核定）；ADMIN 與 API 另各自注入自己專案的 GOOGLE_CLOUD_PROJECT_ID、GOOGLE_CLOUD_LOCATION、DOCUMENT_AI_PROCESSOR_ID、GOOGLE_SERVICE_ACCOUNT_JSON、GEMINI_API_KEY、GROQ_API_KEY（API 2026-10-28、ADMIN 2026-10-29 核定，不視為本機禁用機密；ADMIN 缺 AI 設定時 START 只提示、照常啟動）；前台不取得。本機 ADMIN／API 的資料就是正式資料 |
| 共用常數 | app/core/constants.py（2026-10-26，三站相同）：正式／本機網址、網站名稱、圖示、搜尋引擎設定 |
| 搜尋引擎 | 三站 noindex：網頁 meta 與 vercel.json 的 X-Robots-Tag（後者部署後生效）；robots.txt 不封鎖抓取 |
| 模組 | ADMIN／API 的 DB 模組（app/db）與 Vercel 模組（檔案存取，app/integrations/supabase_storage.py）可直接操作正式 DB／Storage；ADMIN 的 /dev 示範檔案使用的就是這兩個模組。AI 模組（integrations 的 document_ai／gemini／groq／chat_models）2026-10-29 起兩站同版，由兩站的 tests/unit/test_shared_integrations.py 比對一致。第一階段契約 DataService／FileService／get_storage_client() 尚未接線，呼叫時拋出 ModuleNotReadyError |
| Schema／部門 | 既有 ORM 為草案；StoredFile、version 與部門模型尚待設計，未與雲端結構核對 |
| 授權 | APP_ENV=local 不跳過登入（唯一例外：ADMIN 本機 /dev 示範檔案）；OperationContext 不可直接信任請求宣告的身分／權限 |
| 模型整合 | API 已串接：Document AI（OCR）與 Groq gpt-oss（20B／120B）用於手機與電腦上傳辨識（2026-10-29）；Gemini 模組已建、對話待儲值後驗證。ADMIN 有同版 AI 模組與設定（2026-10-29），尚未接線任何功能；前台不直接串接模型；舊 Blob 保留名稱不代表遷移 |
| CI | 已有單站無公司密鑰工作流程（.github/workflows/project-checks.yml）；2026-10-26 已 Push 至 feature/python-web，遠端執行結果須到 GitHub Actions 確認 |

開發者不取得 Vercel／Supabase 管理員權限；雲端變數更新後，雲端需重新部署、本機需重新 START 才會套用。部署、執行 migration、修改正式資料、Commit／Merge／Push 需使用者明確授權。

## 文件權責

AGENTS.md 說明三站架構、閱讀順序與共同約定；README 說明使用方式；ARCHITECTURE／CODING_CONVENTIONS 管目錄與格式；ADMIN/API MODULE_CONTRACT 管型別與未實作邊界；API 的 app/db/README.md 管 Schema 權威。若文件與實際程式衝突，先指出並對齊，不能擅自繞過保護。單站 clone 無兄弟專案時仍可執行本站檢查；不得為讀取兄弟站而索取管理員 Token。

精確檢查與限制見 [PROJECT_CHECKS.md](PROJECT_CHECKS.md)，實測結果見 [TEST_REPORT.md](TEST_REPORT.md)，修正紀錄見 [REVIEW_FIX_LOG.md](REVIEW_FIX_LOG.md)。
