# 系統架構說明 — InvoiceGuard-AI（前台網站）

## 1. 系統全貌

InvoiceGuard AI 由三個獨立的 Git repository 組成，**全部以 Python 撰寫**，各自部署為一個 Vercel Python Function：

```
      User                              Admin
       |                                  |
       v                                  v
┌──────────────────────┐        ┌──────────────────────────┐
│ InvoiceGuard-AI      │        │ InvoiceGuard-AI-ADMIN    │
│ FastAPI + Jinja2     │        │ FastAPI + Jinja2         │
│ Vercel Function (Py) │        │ Vercel Function (Py)     │
└──────────┬───────────┘        └─────────────┬────────────┘
           │ HTTPS + JSON (server side)       │
           ▼                                  │
┌──────────────────────┐                      │ SQL
│ InvoiceGuard-AI-API  │◀── Vercel Cron       │ (own DB module)
│ FastAPI              │                      │
│ Vercel Function (Py) │──▶ AI Model          │
└──────────┬───────────┘──▶ MOF e-Invoice API │
           │ SQL                              │
           ▼                                  │
┌──────────────────────┐                      │
│ PostgreSQL (Neon)    │◀─────────────────────┘
└──────────────────────┘
```

| Repository | 角色 | 技術 | 資料存取 |
|---|---|---|---|
| **InvoiceGuard-AI**（本專案） | 前台網站：使用者上傳發票、查看 AI 分析結果 | FastAPI + Jinja2 | 由伺服器端呼叫 API，**不直接連資料庫** |
| InvoiceGuard-AI-ADMIN | 後台網站：發票審核、使用者管理、排程與稽核紀錄 | FastAPI + Jinja2 | 自有 DB 模組，直接連資料庫 |
| InvoiceGuard-AI-API | 後端 API：AI 分析、第三方串接、排程 | FastAPI | 自有 DB 模組 + Alembic |

---

## 2. 運作方式（伺服器端產生 HTML）

瀏覽器只能執行 JavaScript，因此本網站的 Python 程式在**伺服器端**完成所有工作，瀏覽器只收到 HTML：

```
瀏覽器  ──GET /invoices──▶  routers/invoices.py
                               │ 1. 檢查登入 cookie（core/deps.py）
                               │ 2. 呼叫 API 取資料（clients/invoices.py）
                               │ 3. 套用樣板產生 HTML（templates/pages/invoices/list.html）
瀏覽器  ◀──────HTML──────────┘
```

- **局部更新**：使用 HTMX，在 HTML 加上 `hx-get` 等屬性，即可只替換頁面某一區塊，不必自己寫 JavaScript
- **JavaScript**：只放少量全站共用互動（`static/js/main.js`），不寫呼叫 API 的程式

---

## 3. 目錄結構

```
InvoiceGuard-AI/
├── app/
│   ├── main.py                   # ★ 進入點：建立 app、掛載 /static、註冊例外處理與頁面路由（Vercel 自動偵測）
│   ├── constants.py              # 全站常數：網站名稱、cookie 名稱、發票狀態顯示文字
│   ├── core/                     # 全域核心
│   │   ├── config.py             #   環境變數設定（唯一讀取環境變數的地方）
│   │   ├── templating.py         #   Jinja2 樣板環境、filter、static_url()
│   │   ├── security.py           #   登入 cookie、防 open redirect、同源檢查（防 CSRF）
│   │   ├── deps.py               #   相依注入（AccessToken：需要登入的頁面）
│   │   ├── exceptions.py         #   未登入導向、錯誤頁
│   │   └── logging_config.py     #   日誌格式
│   ├── clients/                  # 呼叫 InvoiceGuard-AI-API（伺服器端）
│   │   ├── base.py               #   共用呼叫 request_json()、ApiError
│   │   ├── auth.py               #   /auth/*
│   │   └── invoices.py           #   /invoices/*
│   ├── routers/                  # 頁面路由，一個功能一個檔案
│   │   ├── health.py             #   GET /health
│   │   ├── robots.py             #   GET /robots.txt
│   │   ├── home.py               #   GET /
│   │   ├── auth.py               #   GET/POST /login、POST /logout
│   │   └── invoices.py           #   /invoices、/invoices/upload、/invoices/{id}
│   ├── templates/                # ★ Jinja2 樣板（HTML）
│   │   ├── base.html             #   HTML 骨架（<head>、全站 css / js）
│   │   ├── layouts/              #   版型：default（頁首頁尾）、blank（登入 / 錯誤頁）
│   │   ├── partials/             #   共用片段：header、footer
│   │   └── pages/                #   頁面樣板，依功能分資料夾（與 routers/ 對應）
│   │       ├── home/
│   │       ├── auth/
│   │       ├── invoices/
│   │       └── errors/
│   ├── static/                   # ★ 靜態檔（網址 /static/...，部署後由 Vercel CDN 提供）
│   │   ├── css/                  #   variables.css（設計變數）、reset.css、components.css、main.css（入口）
│   │   ├── js/                   #   main.js（全站共用）
│   │   │   └── vendor/           #   第三方函式庫（htmx），原樣引入不修改
│   │   ├── img/                  #   圖片
│   │   ├── icons/                #   SVG 圖示、favicon
│   │   └── fonts/                #   自訂字型
│   └── utils/                    # 無狀態工具：format.py（金額 / 台灣時間）、file_utils.py（暫存檔）
├── tests/
│   ├── conftest.py               # client / logged_in_client fixture
│   └── unit/
├── docs/
├── tmp/                          # 本機暫存（不進版控；Vercel 上改用 /tmp）
├── .github/pull_request_template.md
├── .vscode/extensions.json       # 建議安裝的 VS Code 擴充套件
├── vercel.json                   # Function 設定、安全標頭、靜態檔快取
├── requirements.txt              # 正式環境依賴（Vercel 安裝）
├── requirements-dev.txt          # 開發 / 測試依賴
├── ruff.toml / .djlintrc / pytest.ini
├── .python-version               # Python 版本（Vercel 依此選擇）
├── .env.example                  # 環境變數範本
├── .editorconfig / .gitattributes / .gitignore
└── README.md
```

---

## 4. 檔案放置規則（程式碼 / js / css / 圖片 / 暫存檔該放哪？）

| 要放的東西 | 位置 | 說明 |
|---|---|---|
| 頁面路由（Python） | `app/routers/<功能>.py` | 只做：檢查登入 → 呼叫 clients → 回傳樣板 |
| 呼叫後端 API | `app/clients/<資源>.py` | routers 禁止直接使用 httpx |
| 頁面 HTML | `app/templates/pages/<功能>/<頁面>.html` | 資料夾名稱與 routers 檔名一致 |
| 多頁共用的 HTML 片段 | `app/templates/partials/` | 用 `{% include %}` 引入 |
| 版型 | `app/templates/layouts/` | 頁面用 `{% extends %}` 繼承 |
| 樣板用的格式化 | `app/utils/format.py` | 在 `core/templating.py` 註冊為 filter |
| 常數 / 狀態文字 | `app/constants.py` | 禁止在程式或樣板中寫魔術字串 |
| CSS | `app/static/css/` | 設計變數在 `variables.css`，共用元件在 `components.css` |
| JavaScript | `app/static/js/main.js` | 只放全站共用的小型互動 |
| 第三方 JS / CSS | `app/static/js/vendor/` | 原樣引入，版本記錄於該資料夾 README |
| 圖片 | `app/static/img/` | |
| SVG 圖示、favicon | `app/static/icons/` | |
| 字型 | `app/static/fonts/` | |
| 處理中的暫存檔 | 本機 `tmp/`、Vercel `/tmp/invoiceguard` | 一律用 `app.utils.file_utils.temp_file_path()`，用完自動刪除 |
| 使用者上傳的原始檔 | 不存在本網站 | 直接轉交 API，由 API 存到 Vercel Blob |

---

## 5. 登入與安全

| 項目 | 做法 | 位置 |
|---|---|---|
| 登入狀態 | API 回傳的 access token 存在 **httpOnly cookie**（`ig_session`），瀏覽器 JS 讀不到 | `core/security.py` |
| 需要登入的頁面 | 參數宣告 `token: AccessToken`；未登入自動導向 `/login?next=原頁面` | `core/deps.py` |
| token 過期 | API 回 401 → 清除 cookie 並導向登入頁 | `core/exceptions.py` |
| CSRF | cookie 設 `SameSite=Lax`；POST 路由加上 `Depends(verify_same_origin)` | `core/security.py` |
| Open redirect | 登入後導向的 `next` 只允許站內路徑（`safe_next_path()`） | `core/security.py` |
| XSS | Jinja2 自動跳脫；**禁止**對使用者或 API 資料使用 `\|safe` | `core/templating.py` |
| 錯誤訊息 | 錯誤頁只顯示中文說明，內部細節寫入日誌 | `core/exceptions.py` |

---

## 6. 環境變數

完整範本見 [`.env.example`](../.env.example)，讀取統一透過 `app/core/config.py`。

| 變數 | 說明 | 範例 |
|---|---|---|
| `APP_ENV` | `local` / `preview` / `production`；非 local 時 cookie 只走 HTTPS | `local` |
| `DEBUG` | 日誌輸出 DEBUG 等級 | `true` |
| `API_BASE_URL` | InvoiceGuard-AI-API 位址（含 `/api/v1`） | `http://localhost:8000/api/v1` |
| `API_TIMEOUT_SECONDS` | 呼叫 API 的逾時秒數 | `30` |
| `SESSION_MAX_AGE_SECONDS` | 登入 cookie 有效秒數，應與 API 的 token 有效期一致 | `3600` |

`API_BASE_URL` 只在伺服器端使用，不會出現在瀏覽器。新增變數時：`.env.example`、`app/core/config.py`、本表、Vercel Project Settings 四處同步。

---

## 7. 部署（Vercel）

| 項目 | 設定 |
|---|---|
| Framework Preset | FastAPI（由 `requirements.txt` 與 `app/main.py` 自動偵測） |
| Python 版本 | `.python-version`（3.12） |
| Function 設定 | `vercel.json` → `functions["app/main.py"]`：`maxDuration`、`excludeFiles` |
| 靜態檔 | `app.mount("/static", ...)` 會在建置時提升到 CDN；**不要加全域 middleware**，否則靜態檔改由 Function 回應 |
| 快取 | `/static/*` 設一年快取；網址帶 `?v=<commit>` 版本參數，部署新版後自動更新 |
| Production | `main` 分支 |
| Preview | 其他分支 / PR；`API_BASE_URL` 指向 API 的 Preview / 測試環境 |

---

## 8. 新增頁面檢查清單（以「發票詳情」為例）

1. `app/clients/invoices.py` — 確認有對應的 API 函式（含 docstring 與 API 路徑）
2. `app/routers/invoices.py` — 新增路由；需登入就加 `token: AccessToken`；POST 加 `Depends(verify_same_origin)`
3. `app/templates/pages/invoices/detail.html` — 繼承 `layouts/default.html`，檔頭寫 `@template` 備註
4. 頁面專用樣式寫在 `main.css` 對應區塊（變多時拆成 `css/pages/<頁面>.css`）
5. `tests/unit/` 新增測試（以 monkeypatch 替換 clients 函式）
6. `ruff check .`、`djlint app/templates --lint`、`pytest` 通過
