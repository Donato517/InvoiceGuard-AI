# 系統架構說明 — InvoiceGuard-AI（前台）

## 1. 系統全貌

InvoiceGuard AI 由三個獨立的 Git repository 組成，各自部署為一個 Vercel Project：

```
      User                              Admin
       |                                  |
       v                                  v
┌──────────────────────┐        ┌──────────────────────────┐
│ InvoiceGuard-AI      │        │ InvoiceGuard-AI-ADMIN    │
│ Vue 3 + Vite (SPA)   │        │ Vue 3 + Vite (SPA)       │
│ Vercel Static        │        │ Vercel Static            │
└──────────┬───────────┘        └─────────────┬────────────┘
           │ /api/v1/*                        │ /api/v1/admin/*
           └────────────────┬─────────────────┘
                            ▼  HTTPS + JSON (Bearer token)
             ┌──────────────────────────────┐
             │ InvoiceGuard-AI-API          │◀──── Vercel Cron
             │ Python FastAPI               │      GET /api/cron/*
             │ Vercel Function (Python)     │
             └───┬──────────┬──────────┬────┘
                 │          │          │
                 ▼          ▼          ▼
            PostgreSQL  AI Model   MOF e-Invoice
            (Neon)      Service    API
```

| Repository | 角色 | 技術 | 部署 |
|---|---|---|---|
| **InvoiceGuard-AI**（本專案） | 前台：使用者上傳發票、查看 AI 分析結果 | Vue 3 + Vite | Vercel 靜態網站 |
| InvoiceGuard-AI-ADMIN | 後台：發票審核、使用者管理、排程與稽核紀錄 | Vue 3 + Vite | Vercel 靜態網站 |
| InvoiceGuard-AI-API | 後端：REST API、AI 分析、第三方串接、排程 | Python FastAPI | Vercel Python Function |

前端**不直接**連資料庫或第三方服務，所有資料都經由 InvoiceGuard-AI-API。

---

## 2. 目錄結構

```
InvoiceGuard-AI/
├── public/                       # 不經編譯、原樣複製到網站根目錄的檔案
│   ├── favicon.svg
│   └── robots.txt
├── src/
│   ├── main.js                   # ★ 進入點：建立 app、掛載 Pinia / Router / 全域樣式
│   ├── App.vue                   # 根元件：依路由 meta.layout 切換版型
│   ├── api/                      # 後端 API 呼叫
│   │   ├── http.js               #   axios 共用實例（token、逾時、統一錯誤格式）
│   │   └── modules/              #   依後端資源分檔：auth.js、invoice.js
│   ├── assets/                   # 會經過 Vite 編譯（加 hash、壓縮）的靜態資源
│   │   ├── css/                  #   全域樣式：variables.css（設計變數）、reset.css、main.css（入口）
│   │   ├── img/                  #   圖片（png / jpg / webp）
│   │   ├── icons/                #   SVG 圖示
│   │   └── fonts/                #   自訂字型
│   ├── components/               # 可重用元件
│   │   ├── common/               #   通用 UI 元件（BaseButton、BaseModal…），不含業務邏輯
│   │   ├── business/             #   業務元件（InvoiceCard、RiskBadge…）
│   │   └── layout/               #   版型組件（AppHeader、AppFooter）
│   ├── composables/              # 可重用的組合式函式（useXxx.js）
│   ├── constants/                # 常數與列舉（與後端共用的值需註明來源）
│   ├── layouts/                  # 版型：DefaultLayout（頁首頁尾）、BlankLayout（登入 / 錯誤頁）
│   ├── router/                   # 路由：index.js（路由表）、guards.js（登入檢查、頁面標題）
│   ├── stores/                   # Pinia store：index.js（實例）、user.js（登入狀態）
│   ├── utils/                    # 純函式工具（format.js：金額 / 日期顯示）
│   └── views/                    # 頁面元件（一個路由對應一個 XxxView.vue）
│       ├── home/
│       ├── auth/
│       ├── invoice/
│       └── error/
├── tests/
│   └── unit/                     # Vitest 單元測試（xxx.test.js）
├── docs/                         # 專案文件
├── tmp/                          # 本機暫存（不進版控）
├── .github/pull_request_template.md
├── .vscode/extensions.json       # 建議安裝的 VS Code 擴充套件
├── index.html                    # HTML 樣板（Vite 入口）
├── vite.config.js                # Vite 設定（@ 別名、port）
├── vercel.json                   # Vercel 設定（SPA rewrite、安全標頭、快取）
├── eslint.config.js / .prettierrc.json / jsconfig.json
├── package.json
├── .env.example                  # 環境變數範本
├── .editorconfig / .gitattributes / .gitignore
└── README.md
```

---

## 3. 檔案放置規則（我要放 js / css / 圖片 / 暫存檔，該放哪？）

| 要放的東西 | 位置 | 說明 |
|---|---|---|
| 頁面 | `src/views/<功能>/XxxView.vue` | 一個路由一個檔案 |
| 跨頁共用的 UI 元件 | `src/components/common/` | 不可呼叫 API、不可依賴 store |
| 業務元件 | `src/components/business/` | 例：發票卡片、風險標籤 |
| 呼叫後端 API | `src/api/modules/<資源>.js` | 元件內禁止直接用 axios / fetch |
| 可重用的狀態邏輯 | `src/composables/useXxx.js` | 例：`useLoading`、`usePagination` |
| 跨頁共享的狀態 | `src/stores/<名稱>.js` | 只放真正需要跨頁共享的資料 |
| 工具函式（JS） | `src/utils/` | 純函式，不碰 DOM、不呼叫 API |
| 常數 / 列舉 | `src/constants/` | 禁止在程式中寫魔術字串 |
| 全域 CSS | `src/assets/css/` | 元件樣式寫在 `.vue` 的 `<style scoped>` |
| 設計變數（色碼、間距） | `src/assets/css/variables.css` | 元件內禁止寫死色碼 |
| 圖片 | `src/assets/img/` | 會被 Vite 加 hash，可長期快取 |
| SVG 圖示 | `src/assets/icons/` | |
| 字型 | `src/assets/fonts/` | |
| 需固定網址的檔案 | `public/` | 例：favicon、robots.txt、OG 分享圖 |
| 無法用 npm 安裝的第三方腳本 | `public/vendor/`（需要時再建立） | 盡量改用 npm 套件 |
| 暫存檔（匯出測試、截圖、除錯輸出） | `tmp/` | 已列入 `.gitignore`，只保留 `.gitkeep` |
| 建置輸出 | `dist/` | 自動產生，不進版控 |

---

## 4. 資料流

```
View（頁面）
  │ 呼叫
  ├─▶ composables/useXxx.js（loading、分頁等可重用邏輯）
  │       │
  ▼       ▼
api/modules/xxx.js ──▶ api/http.js（axios：baseURL、token、錯誤轉換）──▶ InvoiceGuard-AI-API
  │
  └─ 需要跨頁共享的結果 ──▶ stores/xxx.js
```

- `http.js` 成功時直接回傳 `response.data`；失敗時 reject 一個 `ApiError`（`{ code, message, details, status }`），畫面可直接顯示 `message`。
- API 欄位為 **snake_case**，前端直接沿用，不做命名轉換。
- 金額為字串、時間為 UTC，顯示時一律透過 `utils/format.js`。

---

## 5. 路由規則

| meta 欄位 | 型別 | 說明 |
|---|---|---|
| `title` | string | 頁面標題（瀏覽器分頁顯示「標題 \| InvoiceGuard AI」） |
| `layout` | string | `default`（預設）/ `blank` |
| `requiresAuth` | boolean | 需登入；未登入導向 `/login?redirect=原路徑` |

- 路由 `name` 使用 kebab-case（`invoice-detail`），程式中以 `name` 導頁，不寫死路徑
- 頁面元件一律 `() => import(...)` 動態載入

---

## 6. 環境變數

| 變數 | 說明 | 範例 |
|---|---|---|
| `VITE_API_BASE_URL` | 後端 API 位址（含 `/api/v1`） | `http://localhost:8000/api/v1` |

- 只有 `VITE_` 開頭的變數會被打包，**打包後任何人都看得到**，嚴禁放金鑰
- 本機寫在 `.env.local`；Vercel 分別設定 Production / Preview 的值
- 新增變數時同步更新 `.env.example` 與本表

---

## 7. 部署（Vercel）

| 項目 | 設定 |
|---|---|
| Framework Preset | Vite（自動偵測） |
| Build Command | `npm run build` |
| Output Directory | `dist` |
| SPA 路由 | `vercel.json` 將所有路徑 rewrite 到 `index.html`（實體檔案優先） |
| 快取 | `/assets/*`（含 hash 檔名）設定一年快取 |
| Production | `main` 分支 |
| Preview | 其他分支 / PR；`VITE_API_BASE_URL` 指向 API 的 Preview / 測試環境 |
| CORS | 前台正式網域必須加入 API 的 `CORS_ORIGINS` |

---

## 8. 新增頁面檢查清單

1. `src/views/<功能>/XxxView.vue`（含檔頭備註）
2. `src/router/index.js` 新增路由，設定 `name`、`meta.title`、是否 `requiresAuth`
3. 需要的 API 加到 `src/api/modules/<資源>.js`（含 JSDoc）
4. 可重用的邏輯抽到 `composables/`，可重用的畫面抽到 `components/`
5. `npm run lint && npm run test && npm run build` 通過
