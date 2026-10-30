# 開發狀態與工作邊界

更新：2026-10-29。本文是目前狀態摘要，歷史聊天、檔名或 TODO 不代表功能完成；修改能力時必須同步本表、實作與測試。

## 本站角色

前台以 FastAPI／Jinja2／HTMX 呈現；登入、發票功能透過 app/clients 呼叫 API。登入（2026-10-28）：POST /login 經 API 建立 v1.3 Session，Session Token 存入 httpOnly cookie `ig_session`；/invoices、/qa 每次經 API /auth/me 核對 Session（routers/auth.py `require_session`），頁首顯示登入者與目前部門；POST /logout 請 API 撤銷 Session 再清 cookie。離線測試通過；2026-10-28 使用者以手機經 START 實測登入成功。電腦上傳（2026-10-29）：/invoices/upload 選取本機 JPG／PNG（10 MB 以內，辨識前縮圖）或單頁 PDF（4 MB 以內，原檔上傳、不旋轉、以 iframe 預覽），之後與手機頁共用同一流程與步驟片段 `_upload_review_steps.html`（data-upload-mode="file"）。手機上傳（2026-10-29）：/invoices/mobile-upload 頁面縮圖（最長邊 2000px JPEG）後經 POST /invoices/mobile-recognize 轉呼叫 API 辨識，依回傳欄位與檢核提醒產生核對表單（課稅別、明細可增刪）並顯示 AI 回傳 JSON；POST /invoices/check-duplicate、POST /invoices/mobile-upload 轉呼叫 API 查重與送出（三者都檢查 Origin，API 錯誤轉 JSON，401 導向登入）；已移除示範資料與離線假成功。必填欄位檢核與格式提示（2026-10-29，分支 feature/c-required-fields-hints，尚未 Commit）：核對畫面的必填欄位標示紅色「*必填」（清單與 API InvoiceSubmitRequest 相同，不自行新增；買受人、名稱、國字大寫、數量、單價不標示）；欄位離開時顯示格式提示——綠「格式正確」、藍「格式相容，可送出」（既有 buildPayload 整理後符合，輸入框內容不改）、紅叉加原因，沒有明確格式規則的欄位（名稱、課稅別、國字大寫、品名）不顯示綠勾，不逐字判斷也不呼叫 API；按「上傳者確認」依序檢查已勾選、鎖定按鈕、收集欄位，呼叫 POST /invoices/check-required（前台代理，沿用 Session、Origin 與錯誤處理），有缺漏就一次顯示全部（淺紅底、「請補填○○」、「尚缺 N 個必填欄位」摘要並捲到第一個缺漏；對不到畫面欄位的缺漏仍列在摘要），補齊後前端清除對應提示，再次按確認一律重新檢核，檢核失敗不放行；必填完整後才進行原有格式檢查、查重與送出。字軌／號碼的整理運算式從 buildPayload 抽成 app/static/js/invoice-field-rules.js 的共用 helper（行為與抽出前相同，有測試），金額整理沿用 cleanNumber。離線測試與本機替身伺服器的瀏覽器操作通過（桌面與 375px），不是已整合驗收：尚未連 API 實機驗證，未在真實手機測試；required_complete 只代表沒有必填缺漏，不代表格式、金額或整體資料有效。補充（2026-10-29 最後一輪）：必填檢核失敗（網路、API 錯誤、回應異常）時，清除上一次已過期的缺漏提示、保留使用者填寫的內容，並在摘要區顯示「目前無法完成必填欄位檢查，請稍後再試。資料尚未送出。」，不進入查重與送出，按鈕恢復、再按會重新檢核；字軌的格式提示只對半形英文字母（去掉空白與連字號後）顯示「格式相容」，ß、ﬁ 等會被既有 toUpperCase() 轉成 ASCII 的字元顯示紅叉（不改動 normalizeTrack／buildPayload）。已知限制：正式提交流程仍會把 ıı、ſſ、ß 等整理成 II、SS 後接受，提示比正式提交保守，兩者並不完全一致，是否放寬提示或收緊整理需團隊決定。補充（2026-10-30）：API 對 POST /invoices/check-required 回 2xx 但本文不是合法 JSON（HTML、不合法 JSON、非 UTF-8）或沒有本文時，app/clients/invoices.py 的 check_required_fields 轉成 ApiError(502, INVALID_UPSTREAM_RESPONSE, 「服務回應異常，請稍後再試」)，前台以既有處理器回 502 JSON，不含原始本文；原本此情況為 500 INTERNAL_ERROR。只改這一個呼叫，app/clients/base.py 與其他 client 的行為不變（其他端點遇到同樣情況仍是 500），401、4xx、5xx、連線失敗與正常 JSON 不變；合法 JSON 但結構異常仍原樣轉出，由前端 parseCheckResult 拒絕。以 MockTransport 測試，未連真實 API。核對頁與 AI 辨識值不同的欄位即時標示「已修改」（顯示 AI 原值；新增明細、刪除的 AI 明細另外標示），每次修改記入修改紀錄，確認頁列出修改清單；送出時附明細來源與修改紀錄，由 API 寫入 invoice_field_reviews／invoice_changes 供審核標示。fetch 帶 Accept: application/json，錯誤（含 Session 核對、Origin 檢查、格式錯誤）回 JSON，Session 失效仍導向登入。發票列表、詳情與 /invoices/{id}/flow 仍是示範資料，API 對應端點仍為 TODO；首頁、登入頁與手機 HTTPS 入口可驗證。本站不建立 DB／Storage 模組，也不持有公司機密。本機由 START 以 app.mobile_dev:app 啟動（手機 HTTPS 入口包裝原網站）。

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
| C 組詳情頁（離線） | 2026-10-29 已完成 A＋B 的前台呈現（尚未 Commit，分支 feature/c-a-rule-hints-detail-diff）：API warnings 轉接與欄位提示、發票詳情 UUID／狀態／輪次、AI 原值差異、本機虛構展示 `/invoices/demo/detail`（僅 APP_ENV=local 且非 Vercel）。**離線測試通過（本機測試：pytest 697 passed、54 skipped；JS 16 passed；Ruff、djLint、check_project 通過），不是已整合驗收**：API 尚無 GET /invoices/{id}，正式詳情未接通；尚未做瀏覽器人工驗收。第三輪補充：檢核摘要新增「未知等級 N」計數與提示（severity 缺失或不認得者另計，不升級為 error／warning，不改提交阻擋政策；API 目前的 FieldWarning 沒有 severity，接入後會全顯示為未知等級）；離線展示頁不提供提交操作（不輸出提交按鈕，只顯示唯讀說明），正式詳情頁的按鈕不變。第四輪 UI 視覺對齊（2026-10-29）：詳情頁參考 `InvoiceGuard-AI-Other/invoiceguard_final_formatted.html`（展示原型，非已核定規範）做視覺調整，使用頁面專屬 `app/static/css/pages/invoice-detail.css`，規則全部限定在 `.invoice-detail` 內，不修改全站 Design Tokens、共用 layout／header 或 ADMIN；原型色票以頁面內暫時性 `--idt-*` 變數保存，待全站 Tokens 統一後改為引用全站變數。內容：欄位卡片、案件狀態 badge（只有「已核准」為綠；退回為橘、駁回為紅、作廢與未知為灰虛線）、AI 原值差異標示（已修改為中性藍，不視為驗證失敗）、未知等級摘要為灰色虛線（不升級為 error／warning）、明細表獨立橫向捲動容器（手機版）。明細列警示已從表格內移到表格下方的獨立卡片（依列分組，標題「第 N 筆明細（品名）」，保留 `class="row-issues" data-line-no`），修正長代碼被裁切；另修正表格數字被拆行（250 顯示成 25／0）。為達 4.5:1 對比，部分小字使用同色相較深的文字色。瀏覽器實測（內建瀏覽器，免登入本機展示頁）：375px 手機版頁面無水平溢出、明細表可在容器內橫向捲動、警示卡片完整可讀、長代碼可換行；1280px 桌面版無重複警示、無水平溢出。尚未實測平板寬度與真實手機裝置。跨組待辦：前台共用頁首導覽在 375px 換行、前台全站色票與響應式斷點尚未與原型／ADMIN 對齊（交 A 組或組長）。瀏覽器尚待使用者最後確認。已知限制：明細依位置比對，筆數不同時只標「僅供參考」，筆數相同也無列識別資訊；金額／日期／字軌的標準化比較語意與 API `_canonical_value` 未對齊（待整合）；APP_ENV 預設為 local，部署須明確設定，否則展示頁可能開放。待 API／DB 組確認：詳情 GET 契約、欄位 key、original_values 與 invoice_changes／invoice_field_reviews 的對應 |
| CI | 已有單站無公司密鑰工作流程（.github/workflows/project-checks.yml）；2026-10-26 已 Push 至 feature/python-web，遠端執行結果須到 GitHub Actions 確認 |

開發者不取得 Vercel／Supabase 管理員權限；雲端變數更新後，雲端需重新部署、本機需重新 START 才會套用。部署、執行 migration、修改正式資料、Commit／Merge／Push 需使用者明確授權。

## 文件權責

AGENTS.md 說明三站架構、閱讀順序與共同約定；README 說明使用方式；ARCHITECTURE／CODING_CONVENTIONS 管目錄與格式；ADMIN/API MODULE_CONTRACT 管型別與未實作邊界；API 的 app/db/README.md 管 Schema 權威。若文件與實際程式衝突，先指出並對齊，不能擅自繞過保護。單站 clone 無兄弟專案時仍可執行本站檢查；不得為讀取兄弟站而索取管理員 Token。

精確檢查與限制見 [PROJECT_CHECKS.md](PROJECT_CHECKS.md)，實測結果見 [TEST_REPORT.md](TEST_REPORT.md)，修正紀錄見 [REVIEW_FIX_LOG.md](REVIEW_FIX_LOG.md)。
