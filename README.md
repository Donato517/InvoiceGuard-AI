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

## 快速開始（本機）

```bash
# 1. 建立虛擬環境並安裝套件（Windows 用 .venv\Scripts\activate）
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. 建立環境變數檔，確認 API_BASE_URL（Windows 用 copy）
cp .env.example .env

# 3. 啟動（API 需同時在 port 8000 執行）
uvicorn app.main:app --reload --port 8001
```

開啟 <http://localhost:8001>。本機埠號：API `8000`、前台 `8001`、後台 `8002`。

## 常用指令

| 指令 | 說明 |
|---|---|
| `uvicorn app.main:app --reload --port 8001` | 本機啟動 |
| `ruff check .` / `ruff format .` | Python 檢查 / 格式化 |
| `djlint app/templates --lint` | 樣板檢查 |
| `djlint app/templates --reformat` | 樣板格式化 |
| `pytest` | 執行測試 |

## 文件索引

| 文件 | 內容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統全貌、目錄說明、檔案放置規則（css / js / img / 暫存檔）、登入與安全、部署 |
| [docs/CODING_CONVENTIONS.md](docs/CODING_CONVENTIONS.md) | 命名規則、**程式碼與樣板備註格式** |
| [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) | 分支、Commit 訊息、PR 規範 |
| API 規範 | 見 InvoiceGuard-AI-API 專案 `docs/API_CONVENTIONS.md` |
