"""
呼叫 InvoiceGuard-AI-API 的用戶端：每個 API 資源一個模組（auth、invoices）。
規則：
    - routers 只能透過這裡呼叫 API，禁止直接使用 httpx。
    - 函式名稱以 fetch（查詢）/ create / update / delete / 動詞開頭，並註明對應的 API 路徑。
"""
