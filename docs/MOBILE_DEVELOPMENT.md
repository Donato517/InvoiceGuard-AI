# 手機 HTTPS 與原有網站登入頁

初次執行根目錄 SETUP.cmd；日常只執行 START.cmd，不需 --mobile 或手動 activate venv。
SETUP 從三站 Clone 的共同上層推導 PROJECT_ROOT，START 沿用現有 Python 3.12 venv。

```powershell
# 在 InvoiceGuard-STARTUP 資料夾執行
.\SETUP.cmd
.\START.cmd
```

ADMIN／API 就緒即列本機別名並開啟 ADMIN。終端顯示前端、Tunnel、公開連線三個階段與等待進度；
HTTPS 驗證成功後顯示「FRONTEND 電腦／手機共用 HTTPS：https://…trycloudflare.com/login」，再自動開啟該登入頁。
瀏覽器開啟失敗時可直接複製終端網址；不必經過平台導覽。
每個服務視窗顯示 Repository 名稱、實際服務 URL 與本站別名；前端在公開 origin 檔發布後，再顯示當次 HTTPS /login。

| 入口 | 行為 |
|---|---|
| 當次 HTTPS /login | 電腦與手機直接顯示原有 Email／密碼登入表單 |
| http://invoiceguard-ai.localhost:8080/login | 電腦別名，307 轉至同一 HTTPS 的 /login |
| http://invoiceguard-ai-admin.localhost:8080/ | 原有管理後台，僅開發電腦 |
| http://invoiceguard-ai-api.localhost:8080/health | 本機 API 健康狀態，僅開發電腦 |

手機不能使用電腦的 localhost 或 .localhost。臨時 HTTPS 每次可能不同，請用當次 START 顯示的網址。
不使用 dev／臨時存取碼登入、不發送瀏覽器 Basic 帳密挑戰、不把開發導覽列插入原有網站。
網站本身的登入、部門授權與 API 驗證保留；顯示登入表單不等於真實登入已完成。
登入路由／模板為前台 app/routers/auth.py、app/templates/pages/auth/login.html；手機入口沿用，不另做登入頁。

## 診斷與範圍

前端沿用 app.mobile_dev:app 組裝原網站及本機 HTTPS 來源限制；正式入口 app.main:app 不變。
/platforms、/mobile、/api-status、/health、/__dev/* 是啟動器內部診斷；沒有內部憑證回 403 且不帶 WWW-Authenticate。
內部隨機碼只存在本次程序記憶體，不印到使用者終端、不放 URL、JSON、Git 或測試證據。
一般頁面與原有靜態資源可正常顯示；發票等業務頁仍使用網站原有授權，不能因 APP_ENV=local 繞過。
啟動器只讀固定 loopback API health，不公開 API／ADMIN；ADMIN／API 沿用各自 Vercel Project 取得的核定 DB／S3 設定（Production 值，本機寫入即正式資料）。啟動器自動化測試只用合成服務，不連公司 DB／Storage／模型。

## 手機手動驗收

1. 停止舊版 START，在新視窗執行最新 START.cmd。
2. 手機開終端當次 HTTPS /login：直接看到既有 Email／密碼登入表單，沒有瀏覽器額外帳密視窗。
3. 重新整理數次、檢查樣式／圖示正常；畫面沒有平台導覽列。未登入開 /invoices，應導回網站 /login。
4. 實際帳號登入、拍照、上傳與 AI 另依業務功能實作驗收；不以頁面顯示測試宣稱通過。
5. 在主 START 總控按 Ctrl+C 停止全部。CMD 若詢問是否終止批次，輸入 N，讓清理與字碼頁還原完成；輸入 Y 可能使字碼頁停在 65001。

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8100,8101,8002,8080 -ErrorAction SilentlyContinue
```

另測在單一服務視窗按 Ctrl+C：只停本站服務，CMD 視窗保留並顯示啟動指令，貼上即可在同視窗重啟；點 X 關閉該視窗則清本站全部程序，在總控按 1／2／3 重新開啟。其餘站、gateway、Tunnel 與當次 HTTPS 網址保留，不自動重開。停止 API 後依賴 API 的功能可能失敗，但其他站程序應繼續運行。
直接關閉主 START 總控視窗則應清理本次全部程序與埠；不可使用 taskkill /IM python.exe。
手機硬體、人工按鍵或點 X 與程式化 Ctrl+C／WM_CLOSE 要分別記錄。

## 保留機制與選項

- 三站綁 127.0.0.1，gateway 獨占 127.0.0.1／::1。IPv4／IPv6／萬用埠占用即拒絕，不停止既有程序。
- 前端保留固定 Host／HTTPS／Origin／CSRF、no-store、origin 握手；來源未就緒不開放網站。
- 前端別名 GET／HEAD 跨來源 307 至同一 HTTPS；POST 等寫入回 409，不代理或注入內部憑證。
- Windows CreateProcessW 原子 JOB_LIST；三站各有私有 KILL_ON_JOB_CLOSE Job，gateway／Tunnel 使用共用 Job，handles 不可繼承。本站 Ctrl+C 或 Python 程序退出時，CMD 視窗與私有 Job 保留供重啟；只有本站 CMD 視窗程序退出／WM_CLOSE 才關本站 Job、清理本站全部子孫。主 START Ctrl+C／WM_CLOSE 仍收回本次全部 Job 與子孫。
- 子程序使用 OS 環境白名單，不繼承公司 DB／模型 Key、VERCEL、代理或 PYTHONPATH；ADMIN／API 只另外取得 START 注入的核定 DB／S3 設定。正式／本機設定隔離保留。
- cloudflared 只解析核定 info JSON；缺工具在預檢即拒絕。Tunnel 或公開驗證失敗會明確提示手機 HTTPS 未通過、不自動開前端，三站繼續以本機網址執行，不宣稱手機可用。
- --check 唯讀預檢；--no-browser 仍列 URL；--open 只開既有入口；--local-only 為無 Tunnel 的電腦診斷；--mobile 僅相容舊指令。
- 自訂測試埠：START.cmd --api-port 8210 --frontend-port 8211 --admin-port 8212 --alias-port 8081。
- 異常結束可能留下只有公開 origin.json 的暫存目錄，不含內部碼；只能清理確認屬於本次的檔案。

原始碼在 launcher/，封裝在 packaging/，文件在 docs/，測試在 tests/，暫存放 artifacts/ 或專案外。
重建兩個入口與 ZIP 後，以 SETUP.cmd --reuse --skip-tools 更新既有設定，不跑 pip。
測試與修正記錄見 STARTUP docs/TEST_REPORT.md、docs/REVIEW_FIX_LOG.md；歷史 Basic 流程已由本版取代。
本文件在 STARTUP 與 InvoiceGuard-AI/docs 各一份，保持逐位元組一致；修改時兩份同步。
