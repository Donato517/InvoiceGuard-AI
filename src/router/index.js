/**
 * @file 路由設定
 * @description 定義前台所有頁面路由。頁面元件一律使用動態 import（lazy loading），縮小首次載入體積。
 *
 * 路由 meta 欄位：
 *   - title {string}          頁面標題（顯示於瀏覽器分頁）
 *   - layout {string}         版型：default（預設）/ blank（無頁首頁尾）
 *   - requiresAuth {boolean}  是否需要登入
 */
import { createRouter, createWebHistory } from 'vue-router'

import { setupRouterGuards } from '@/router/guards'

const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/home/HomeView.vue'),
    meta: { title: '首頁' },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/auth/LoginView.vue'),
    meta: { title: '登入', layout: 'blank' },
  },
  {
    path: '/invoices',
    name: 'invoice-list',
    component: () => import('@/views/invoice/InvoiceListView.vue'),
    meta: { title: '我的發票', requiresAuth: true },
  },
  {
    path: '/invoices/upload',
    name: 'invoice-upload',
    component: () => import('@/views/invoice/InvoiceUploadView.vue'),
    meta: { title: '上傳發票', requiresAuth: true },
  },
  {
    path: '/invoices/:id',
    name: 'invoice-detail',
    component: () => import('@/views/invoice/InvoiceDetailView.vue'),
    props: true,
    meta: { title: '發票詳情', requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/error/NotFoundView.vue'),
    meta: { title: '找不到頁面', layout: 'blank' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

setupRouterGuards(router)

export default router
