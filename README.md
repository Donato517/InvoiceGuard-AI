# InvoiceGuard-AI

InvoiceGuard AI 前台網站：使用者上傳發票、查看 AI 風險分析結果。

| 項目 | 內容 |
|---|---|
| 語言 / 框架 | Python 3.12 + FastAPI + Jinja2 樣板（伺服器端產生 HTML） |
| 互動 | HTMX（以 HTML 屬性做局部更新，幾乎不寫 JavaScript） |
| 資料來源 | 由伺服器端呼叫 [InvoiceGuard-AI-API](https://github.com/Donato517/InvoiceGuard-AI-API)，不直接連資料庫 |
| 品質工具 | Ruff（Python）、djLint（樣板）、pytest |
| 部署 | Vercel Python Runtime（自動偵測 `app/main.py`） |
| 相關專案 | [InvoiceGuard-AI-API](https://github.com/Donato517/InvoiceGuard-AI-API)（後端 API）、[InvoiceGuard-AI-ADMIN](https://github.com/Donato517/InvoiceGuard-AI-ADMIN)（後台） |

## 快速開始（Windows 團隊開發）

先閱讀 [AGENTS.md](AGENTS.md)；Claude 入口為 [CLAUDE.md](CLAUDE.md)。
目前已完成、僅有契約與尚未實作的能力，以 [開發狀態](docs/DEVELOPMENT_STATUS.md) 為準。

三站放在同一個根目錄，啟動器放在同層 `InvoiceGuard-STARTUP`。
啟動器的 `SETUP.cmd` 從三站共同上層推導並記錄 `PROJECT_ROOT`，不要在三站重複寫死路徑。
在 PowerShell 切換到 `InvoiceGuard-STARTUP` 後執行：

```powershell
# 初次設定：建立或重用三站各自的 Python 3.12 venv，安裝開發依賴（相容指令 .\START.cmd setup）
.\SETUP.cmd

# 日常啟動：三站、電腦別名及電腦／手機共用的臨時 HTTPS；不需 --mobile
.\START.cmd
```

START 最後自動開啟當次 HTTPS 的 `/login`，電腦與手機都直接看到原有 Email／密碼登入表單，
不需要開發存取碼，也不會出現額外的瀏覽器帳密視窗；網站登入與權限照舊。電腦另有本機別名：

- 前台：<http://invoiceguard-ai.localhost:8080/login>（307 轉至同一次 HTTPS 的 /login）
- ADMIN：<http://invoiceguard-ai-admin.localhost:8080/>（僅開發電腦）
- API 健康檢查：<http://invoiceguard-ai-api.localhost:8080/health>（僅開發電腦）

內部服務埠（日常 8100／8101／8002；離線診斷 `--local-only` 為 8000／8001／8002）不作為日常辨識入口。
手機不能使用電腦的 `.localhost`；請開終端顯示的 HTTPS `/login`。依啟動器文件操作 Ctrl+C 關閉本次服務。
若啟動器未隨 clone 取得，先向團隊取得核定啟動器，不自行建置另一套網站或下載公司機密。

本機預設不讀 `.env`；前台程序不取得任何公司 DB、Storage、模型或 Session 密鑰。
開啟頁面及 `/health` 只表示程序正常，不能視為登入、CRUD、Storage 或雲端連線通過。

## 本站無密鑰檢查

在本站根目錄使用既有 `.venv`：

```powershell
.\.venv\Scripts\python.exe -B scripts/check_project.py
.\.venv\Scripts\python.exe -B -m app.core.environment --check
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp=tmp/pytest
```

共同檢查不需要兄弟 Repository 或公司密鑰；同時持有三站時可加 `--project-root` 比對契約。
檢查範圍、限制與指令見 [PROJECT_CHECKS.md](docs/PROJECT_CHECKS.md)。
`tmp/pytest` 只作測試暫存，不能放要保留的檔案。

## 常用指令

| 指令 | 說明 |
|---|---|
| `uvicorn app.main:app --reload --port 8001` | 單站診斷；日常使用 `START.cmd` |
| `ruff check app tests scripts` / `ruff format app tests scripts` | Python 檢查 / 格式化 |
| `djlint app/templates --lint` | 樣板檢查 |
| `djlint app/templates --reformat` | 樣板格式化 |
| `pytest` | 執行測試 |

## 文件索引

| 文件 | 內容 |
|---|---|
| [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) | AI 固定閱讀入口：三站架構、共同規則、本站現況與授權邊界 |
| [docs/DEVELOPMENT_STATUS.md](docs/DEVELOPMENT_STATUS.md) | 已完成、契約與尚未實作的能力 |
| [docs/PROJECT_CHECKS.md](docs/PROJECT_CHECKS.md) | 無密鑰契約／分層檢查、跨站同步與限制 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統全貌、目錄說明、檔案放置規則（css / js / img / 暫存檔）、登入與安全、部署 |
| [docs/CODING_CONVENTIONS.md](docs/CODING_CONVENTIONS.md) | 命名規則、**程式碼與樣板備註格式** |
| [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) | 分支、Commit 訊息、PR 規範 |
| API 規範 | 見 InvoiceGuard-AI-API 專案 `docs/API_CONVENTIONS.md` |

環境與 URL 的來源、管理者檢查及 PowerShell 驗證方式見 [開發／雲端環境隔離](docs/ENVIRONMENT_ISOLATION.md)。

手機 HTTPS 開發入口與實機驗證方式見 [手機開發文件](docs/MOBILE_DEVELOPMENT.md)。

`docs/CLAUDE_REVIEW_PROMPT.md` 是歷史檢驗指令，不是現行規則。
