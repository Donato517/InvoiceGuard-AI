/**
 * @file 使用者狀態 store
 * @description 保存登入 token 與目前使用者資料；token 同步寫入 localStorage，重新整理後仍維持登入。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { STORAGE_KEYS } from '@/constants/storage'

export const useUserStore = defineStore('user', () => {
  /** 存取權杖（access token） */
  const token = ref(localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN) ?? '')
  /** 目前登入的使用者資料（GET /auth/me 的回應），未載入時為 null */
  const profile = ref(null)

  /** 是否已登入 */
  const isLoggedIn = computed(() => Boolean(token.value))

  /**
   * 設定 token（登入成功後呼叫）
   * @param {string} value - 後端回傳的 access token
   */
  function setToken(value) {
    token.value = value
    localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, value)
  }

  /** 登出：清除 token 與使用者資料 */
  function logout() {
    token.value = ''
    profile.value = null
    localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN)
  }

  // TODO(JerryChien): fetchProfile() 呼叫 api/modules/auth.js 的 fetchMe() 載入使用者資料

  return { token, profile, isLoggedIn, setToken, logout }
})
