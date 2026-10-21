/**
 * @file 路由守衛
 * @description meta.requiresAuth 為 true 的頁面需登入，未登入導向登入頁並記錄原本要去的頁面；
 *   切換頁面後更新瀏覽器分頁標題。
 */
import { useUserStore } from '@/stores/user'

const SITE_NAME = 'InvoiceGuard AI'

/**
 * 註冊路由守衛
 * @param {import('vue-router').Router} router - Router 實例
 */
export function setupRouterGuards(router) {
  router.beforeEach((to) => {
    const userStore = useUserStore()

    if (to.meta.requiresAuth && !userStore.isLoggedIn) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    return true
  })

  router.afterEach((to) => {
    document.title = to.meta.title ? `${to.meta.title} | ${SITE_NAME}` : SITE_NAME
  })
}
