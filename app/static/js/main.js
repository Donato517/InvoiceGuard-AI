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

