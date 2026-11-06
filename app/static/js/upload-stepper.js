/**
 * @file 上傳流程步驟卡片（partials/upload_stepper.html，2026-11-06 對齊後台）
 * @description 觀察上傳頁哪個步驟區塊正在顯示，更新步驟卡片：之前的步驟打 ✓、目前步驟藍底、手機版的「步驟 X / 6」與進度條。
 *   - 只讀取 #step-upload、#step-preview、#step-fields、#step-confirm、#step-success 的 hidden 狀態，不修改 mobile-camera.js。
 *   - 「辨識」（第 3 步）沒有自己的畫面：進入核對修正時與前兩步一起標成完成。
 */
;(function () {
  'use strict'

  const SECTION_STEPS = [
    ['step-upload', 1],
    ['step-preview', 2],
    ['step-fields', 4],
    ['step-confirm', 5],
    ['step-success', 6]
  ]

  function currentStep() {
    for (const [id, step] of SECTION_STEPS) {
      const section = document.getElementById(id)
      if (section && !section.hidden) return step
    }
    return 1
  }

  function render(stepper) {
    const now = currentStep()
    const items = stepper.querySelectorAll('[data-step]')
    const done = now === 6 // 上傳成功：全部完成
    items.forEach((item) => {
      const step = Number(item.dataset.step)
      const no = item.querySelector('.upload-stepper__no')
      const isDone = done || step < now
      const isActive = !done && step === now
      item.classList.toggle('upload-stepper__item--done', isDone)
      item.classList.toggle('upload-stepper__item--active', isActive)
      if (isActive) item.setAttribute('aria-current', 'step')
      else item.removeAttribute('aria-current')
      if (no) no.textContent = isDone ? '✓' : String(step)
    })
    const current = stepper.querySelector('[data-step="' + now + '"] .upload-stepper__label')
    const nowEl = stepper.querySelector('[data-stepper-now]')
    const nameEl = stepper.querySelector('[data-stepper-name]')
    const bar = stepper.querySelector('[data-stepper-bar]')
    if (nowEl) nowEl.textContent = String(now)
    if (nameEl && current) nameEl.textContent = done ? '完成' : current.textContent
    if (bar) bar.style.width = Math.round((now / items.length) * 100) + '%'
  }

  function init() {
    const stepper = document.querySelector('[data-upload-stepper]')
    if (!stepper) return
    render(stepper)
    const observer = new MutationObserver(function () {
      render(stepper)
    })
    SECTION_STEPS.forEach(function ([id]) {
      const section = document.getElementById(id)
      if (section) observer.observe(section, { attributes: true, attributeFilter: ['hidden'] })
    })
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init)
  else init()
})()
