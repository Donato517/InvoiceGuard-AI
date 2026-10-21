# InvoiceGuard-AI

InvoiceGuard AI 前台網站：使用者上傳發票、查看 AI 風險分析結果。

| 項目 | 內容 |
|---|---|
| 框架 | Vue 3（Composition API / `<script setup>`）+ Vite |
| 路由 / 狀態 | Vue Router / Pinia |
| HTTP | axios（統一經由 `src/api/http.js`） |
| 品質工具 | ESLint + Prettier + Vitest |
| 部署 | Vercel（靜態網站，SPA） |
| 相關專案 | [InvoiceGuard-AI-API](https://github.com/Donato517/InvoiceGuard-AI-API)（後端）、[InvoiceGuard-AI-ADMIN](https://github.com/Donato517/InvoiceGuard-AI-ADMIN)（後台） |

## 快速開始

需求：Node.js 22.12 以上

```bash
npm install
cp .env.example .env.local    # Windows 用 copy；填入 VITE_API_BASE_URL
npm run dev                   # http://localhost:5173
```

## 常用指令

| 指令 | 說明 |
|---|---|
| `npm run dev` | 本機開發（port 5173） |
| `npm run build` | 建置正式版到 `dist/` |
| `npm run preview` | 預覽建置結果 |
| `npm run lint` | ESLint 檢查 |
| `npm run format` | Prettier 格式化 |
| `npm run test` | 執行單元測試 |

## 文件索引

| 文件 | 內容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系統全貌、目錄說明、檔案放置規則、部署 |
| [docs/CODING_CONVENTIONS.md](docs/CODING_CONVENTIONS.md) | 命名規則、**程式碼備註格式** |
| [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) | 分支、Commit 訊息、PR 規範 |
| API 規範 | 見 InvoiceGuard-AI-API 專案 `docs/API_CONVENTIONS.md` |
