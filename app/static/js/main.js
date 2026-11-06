/**
 * @file 全站共用 JavaScript
 * @description 只放少量通用互動。頁面互動優先使用 HTMX 屬性（hx-get、hx-post…），
 *   不要自行寫 fetch 呼叫；資料一律由伺服器端（Python）處理後產生 HTML。
 */

/**
 * 送出前確認：表單加上 data-confirm 屬性即會先跳出確認視窗，按取消則不送出。
 * @example
 * <form method="post" action="/logout" data-confirm="確定要登出嗎？">
 */
document.addEventListener('submit', (event) => {
  const message = event.target.dataset.confirm
  if (message && !window.confirm(message)) {
    event.preventDefault()
  }
})

/**
 * 登入表單：送出時將登入按鈕轉為載入旋轉圈狀態。
 */
document.addEventListener('submit', (event) => {
  const form = event.target
  if (
    form &&
    form.getAttribute('action') === '/login' &&
    !event.defaultPrevented
  ) {
    const submitBtn = form.querySelector('button[type="submit"]')
    if (submitBtn) {
      submitBtn.classList.add('btn--loading')
      submitBtn.setAttribute('aria-busy', 'true')
      submitBtn.innerHTML = '<span class="btn__spinner" aria-hidden="true"></span>登入中…'
      setTimeout(() => {
        submitBtn.disabled = true
      }, 0)
    }
  }
})

window.addEventListener('pageshow', () => {
  const loginForm = document.querySelector('form[action="/login"]')
  if (loginForm) {
    const loginBtn = loginForm.querySelector('button[type="submit"]')
    if (loginBtn && loginBtn.classList.contains('btn--loading')) {
      loginBtn.classList.remove('btn--loading')
      loginBtn.removeAttribute('aria-busy')
      loginBtn.disabled = false
      loginBtn.textContent = '登入'
    }
  }
})

/**
 * 登入後左側欄（partials/app_sidebar.html，2026-11-06 對齊後台）：群組展開／收合、收合成圖示列。
 * 狀態記在瀏覽器；無痕或封鎖儲存時照預設顯示（目前頁面所在群組展開、側欄不收合）。
 * 圖示列時點群組圖示：先展開側欄並打開該群組。
 */
const SIDEBAR_COLLAPSED_KEY = 'ig-front-sidebar-collapsed'
const SIDEBAR_OPEN_KEY = 'ig-front-sidebar-open-groups'

function readSidebarPrefs() {
  try {
    const storage = window.localStorage
    return {
      collapsed: storage.getItem(SIDEBAR_COLLAPSED_KEY) === '1',
      open: JSON.parse(storage.getItem(SIDEBAR_OPEN_KEY) || '[]')
    }
  } catch {
    return { collapsed: false, open: [] }
  }
}

function saveSidebarPref(key, value) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // 無法保存時只影響下次開頁的預設狀態
  }
}

function setSidebarGroup(group, open) {
  const toggle = group.querySelector('.app-sidebar__group-toggle')
  const items = group.querySelector('.app-sidebar__group-items')
  if (!toggle || !items) return
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false')
  items.hidden = !open
}

function setSidebarCollapsed(collapsed) {
  document.documentElement.classList.toggle('sidebar-collapsed', collapsed)
  document.querySelectorAll('[data-sidebar-collapse]').forEach((button) => {
    const label = collapsed ? '展開側欄' : '收合側欄'
    button.setAttribute('aria-label', label)
    button.setAttribute('title', label)
  })
}

const sidebarPrefs = readSidebarPrefs()
const openSidebarGroups = new Set(Array.isArray(sidebarPrefs.open) ? sidebarPrefs.open : [])
setSidebarCollapsed(sidebarPrefs.collapsed)
document.querySelectorAll('[data-sidebar-group]').forEach((group) => {
  if (openSidebarGroups.has(group.dataset.sidebarGroup)) setSidebarGroup(group, true)
})

document.addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target : null
  if (!target) return
  if (target.closest('[data-sidebar-collapse]')) {
    const collapsed = !document.documentElement.classList.contains('sidebar-collapsed')
    setSidebarCollapsed(collapsed)
    saveSidebarPref(SIDEBAR_COLLAPSED_KEY, collapsed ? '1' : '0')
    return
  }
  const toggle = target.closest('.app-sidebar__group-toggle')
  const group = toggle && toggle.closest('[data-sidebar-group]')
  if (!group) return
  let open = toggle.getAttribute('aria-expanded') !== 'true'
  if (document.documentElement.classList.contains('sidebar-collapsed')) {
    setSidebarCollapsed(false)
    saveSidebarPref(SIDEBAR_COLLAPSED_KEY, '0')
    open = true
  }
  setSidebarGroup(group, open)
  if (open) openSidebarGroups.add(group.dataset.sidebarGroup)
  else openSidebarGroups.delete(group.dataset.sidebarGroup)
  saveSidebarPref(SIDEBAR_OPEN_KEY, JSON.stringify([...openSidebarGroups]))
})
