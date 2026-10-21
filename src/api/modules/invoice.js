/**
 * @file 發票 API
 * @description 前台使用者的發票 API：列表、詳情、上傳、重新分析。對應後端：/api/v1/invoices
 */
import http from '@/api/http'

/**
 * 取得我的發票列表
 * @param {Object} [params] - 查詢條件
 * @param {number} [params.page=1] - 頁碼
 * @param {number} [params.page_size=20] - 每頁筆數（上限 100）
 * @param {string} [params.status] - 依狀態篩選，值見 constants/invoice.js
 * @returns {Promise<{ items: Object[], total: number, page: number, page_size: number }>}
 */
export function fetchInvoices(params) {
  return http.get('/invoices', { params })
}

/**
 * 取得單張發票詳情（含明細與 AI 分析結果）
 * @param {number|string} id - 發票 ID
 * @returns {Promise<Object>}
 */
export function fetchInvoice(id) {
  return http.get(`/invoices/${id}`)
}

/**
 * 上傳發票檔案（圖片 / PDF）
 * @param {File} file - 使用者選擇的檔案
 * @returns {Promise<Object>} 建立後的發票資料
 */
export function uploadInvoice(file) {
  const formData = new FormData()
  formData.append('file', file)
  return http.post('/invoices/upload', formData)
}

/**
 * 重新觸發 AI 分析
 * @param {number|string} id - 發票 ID
 * @returns {Promise<Object>} 更新後的發票資料
 */
export function analyzeInvoice(id) {
  return http.post(`/invoices/${id}/analyze`)
}
