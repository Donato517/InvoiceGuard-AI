/**
 * @file 發票圖片選取與預覽（C-IMG-01）
 * @description 掛在 [data-image-picker] 區塊：選取 → 驗證 → 預覽 → 重新選取／取消。
 *   - 前端檢查只是使用者體驗；正式上傳時後端必須再驗證一次。
 *   - 不上傳、不呼叫任何 API、不寫入 localStorage／sessionStorage／IndexedDB，圖片只存在記憶體。
 *   - 預覽使用 object URL；更換、取消、載入失敗與離開頁面時都會 revoke。
 *   - 錯誤代碼與 Python 的 app/utils/image_validation.py 相同。
 */
;(function (root) {
  'use strict'

  var EXTENSION_TO_TYPE = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png' }
  var MESSAGES = {
    no_file: '請選擇發票圖片',
    empty: '檔案是空的，請重新選擇',
    too_large: '檔案過大，請選擇小於 {limit} 的圖片',
    unsupported_extension: '只支援 JPG、JPEG、PNG 圖片',
    unsupported_mime: '檔案類型不符，只支援 JPG、JPEG、PNG 圖片',
    content_mismatch: '檔案內容不是有效的 JPG 或 PNG 圖片，請重新選擇',
    unreadable: '無法讀取這個檔案，請重新選擇',
    preview_failed: '無法預覽這張圖片，請重新選擇'
  }

  function formatSize(bytes) {
    if (bytes >= 1024 * 1024) return Number((bytes / (1024 * 1024)).toPrecision(6)) + ' MB'
    if (bytes >= 1024) return Number((bytes / 1024).toPrecision(6)) + ' KB'
    return bytes + ' 位元組'
  }

  function message(code, maxBytes) {
    return (MESSAGES[code] || MESSAGES.unreadable).replace('{limit}', formatSize(maxBytes))
  }

  /** 由檔頭判斷圖片類型；bytes 為 Uint8Array。 */
  function detectType(bytes) {
    if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
      return 'image/jpeg'
    }
    var png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
    var ihdr = [0x49, 0x48, 0x44, 0x52]
    if (bytes.length >= 16) {
      var ok = png.every(function (b, i) { return bytes[i] === b }) &&
        ihdr.every(function (b, i) { return bytes[12 + i] === b })
      if (ok) return 'image/png'
    }
    return null
  }

  /**
   * 驗證 File；回傳 Promise<{ ok, code }>。檢查順序與 Python 端相同。
   * @param {File} file
   * @param {number} maxBytes 由頁面 data-max-bytes 提供，這裡不內建預設值。
   */
  function validateFile(file, maxBytes) {
    if (!file) return Promise.resolve({ ok: false, code: 'no_file' })
    if (file.size === 0) return Promise.resolve({ ok: false, code: 'empty' })
    if (file.size > maxBytes) return Promise.resolve({ ok: false, code: 'too_large' })
    var ext = (file.name.split('.').pop() || '').toLowerCase()
    var extType = file.name.indexOf('.') > 0 ? EXTENSION_TO_TYPE[ext] : undefined
    if (!extType) return Promise.resolve({ ok: false, code: 'unsupported_extension' })
    var mime = (file.type || '').toLowerCase()
    if (mime !== 'image/jpeg' && mime !== 'image/png') {
      return Promise.resolve({ ok: false, code: 'unsupported_mime' })
    }
    return file.slice(0, 16).arrayBuffer().then(
      function (buffer) {
        var detected = detectType(new Uint8Array(buffer))
        if (detected === null || detected !== extType || detected !== mime) {
          return { ok: false, code: 'content_mismatch' }
        }
        return { ok: true, code: null }
      },
      function () { return { ok: false, code: 'unreadable' } }
    )
  }

  /**
   * 建立選取器。
   * @param {HTMLElement} container 含 [data-image-picker-*] 子元素的區塊
   * @param {{ createObjectURL?: Function, revokeObjectURL?: Function }} [urlApi] 測試用替身
   */
  function createPicker(container, urlApi) {
    var urls = urlApi || root.URL
    var input = container.querySelector('input[type="file"]')
    var preview = container.querySelector('[data-image-picker-preview]')
    var image = container.querySelector('[data-image-picker-image]')
    var nameEl = container.querySelector('[data-image-picker-name]')
    var sizeEl = container.querySelector('[data-image-picker-size]')
    var errorEl = container.querySelector('[data-image-picker-error]')
    var clearBtn = container.querySelector('[data-image-picker-clear]')
    var maxBytes = Number(container.getAttribute('data-max-bytes'))
    var currentUrl = null
    var ticket = 0 // 避免舊檔案的非同步驗證覆蓋較新的選擇

    function releaseUrl() {
      if (currentUrl) {
        urls.revokeObjectURL(currentUrl)
        currentUrl = null
      }
    }

    function render(state, detail) {
      container.setAttribute('data-state', state)
      var showPreview = state === 'selected'
      preview.hidden = !showPreview
      if (!showPreview) {
        image.removeAttribute('src')
        nameEl.textContent = ''
        sizeEl.textContent = ''
      }
      errorEl.hidden = state !== 'error'
      errorEl.textContent = state === 'error' ? detail : ''
      if (clearBtn) clearBtn.hidden = !showPreview
    }

    function reset(state, detail) {
      ticket += 1
      releaseUrl()
      input.value = '' // 失敗或取消時不保留檔案，避免被表單送出
      render(state, detail)
    }

    function fail(code) {
      reset('error', message(code, maxBytes))
    }

    function onChange() {
      var file = input.files && input.files[0]
      if (!file) {
        reset('idle')
        return
      }
      var mine = ++ticket
      container.setAttribute('data-state', 'validating')
      validateFile(file, maxBytes).then(function (result) {
        if (mine !== ticket) return // 已有更新的選擇
        if (!result.ok) {
          fail(result.code)
          return
        }
        releaseUrl()
        try {
          currentUrl = urls.createObjectURL(file)
        } catch (e) {
          fail('preview_failed')
          return
        }
        nameEl.textContent = file.name
        sizeEl.textContent = formatSize(file.size)
        image.setAttribute('src', currentUrl)
        errorEl.hidden = true
        errorEl.textContent = ''
        preview.hidden = false
        if (clearBtn) clearBtn.hidden = false
        container.setAttribute('data-state', 'selected')
      })
    }

    function onImageError() {
      if (container.getAttribute('data-state') === 'selected') fail('preview_failed')
    }

    function onClear() {
      reset('idle')
      input.focus()
    }

    function onSubmit(event) {
      if (container.getAttribute('data-state') !== 'selected') {
        event.preventDefault()
        fail('no_file')
      }
    }

    input.addEventListener('change', onChange)
    image.addEventListener('error', onImageError)
    if (clearBtn) clearBtn.addEventListener('click', onClear)
    var form = container.closest ? container.closest('form') : null
    if (form) form.addEventListener('submit', onSubmit)
    if (root.addEventListener) root.addEventListener('pagehide', releaseUrl)
    render('idle')

    return {
      hasValidFile: function () { return container.getAttribute('data-state') === 'selected' },
      destroy: function () {
        ticket += 1
        releaseUrl()
        input.removeEventListener('change', onChange)
        image.removeEventListener('error', onImageError)
        if (clearBtn) clearBtn.removeEventListener('click', onClear)
        if (form) form.removeEventListener('submit', onSubmit)
        if (root.removeEventListener) root.removeEventListener('pagehide', releaseUrl)
      }
    }
  }

  var api = { validateFile: validateFile, detectType: detectType, createPicker: createPicker }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  root.ImagePicker = api

  if (root.document && root.document.querySelectorAll) {
    root.document.addEventListener('DOMContentLoaded', function () {
      root.document.querySelectorAll('[data-image-picker]').forEach(function (el) {
        createPicker(el)
      })
    })
  }
})(typeof window !== 'undefined' ? window : globalThis)
