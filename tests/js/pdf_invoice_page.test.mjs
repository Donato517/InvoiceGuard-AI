// 測試目標：app/static/js/pdf-invoice-page.js 多頁 PDF 找發票頁的流程——前置過濾（大小、檔頭、密碼、45 頁）、
//   分批判斷、第一聯擋下、聯別不清時以原解析度確認、多頁可用時的選擇視窗（預設第二聯）。
// 注意：在 node:vm 內以最小假 DOM 執行原始碼；pdf.js 與 fetch 都是替身（find 的 pdfjs 參數注入），
//   驗證的是挑頁邏輯，不是真實 PDF 渲染、瀏覽器版面或 API／模型結果。
// 執行：node --test tests/js/
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const SRC = readFileSync(new URL('../../app/static/js/pdf-invoice-page.js', import.meta.url), 'utf8')

class FakeEl {
  constructor(tag) {
    this.tag = tag
    this.children = []
    this.attrs = {}
    this.listeners = {}
    this.open = false
    this.textContent = ''
  }
  setAttribute(k, v) { this.attrs[k] = String(v) }
  append(...nodes) { this.children.push(...nodes) }
  appendChild(node) { this.children.push(node); return node }
  addEventListener(type, fn) { this.listeners[type] = fn }
  remove() { this.removed = true }
  showModal() { this.open = true }
  close() { this.open = false }
  focus() { this.focused = true }
  getContext() { return { fillRect() {} } }
  toBlob(cb, type, quality) { cb({ size: 1000, width: this.width, height: this.height, type, quality }) }
}

// 依頁碼決定 API 判斷：{ 頁碼: [是否發票, 縮圖聯別, 原解析度聯別] }
function setup({ pages = 1, verdicts = {}, openError = null, chooseIndex = null } = {}) {
  const calls = []
  const dialogs = []
  const body = {
    appendChild(el) {
      dialogs.push(el)
      if (chooseIndex !== null) {
        // 視窗出現後由測試點選第 chooseIndex 個選項（null 時按取消）
        queueMicrotask(() => {
          const grid = el.children.find((c) => c.className === 'pdf-pick-dialog__grid')
          if (chooseIndex === 'cancel') {
            el.children.find((c) => c.className === 'pdf-pick-dialog__actions').children[0].onclick()
          } else {
            grid.children[chooseIndex].onclick()
          }
        })
      }
    }
  }
  const context = {
    window: {},
    document: {
      currentScript: { dataset: { pdfjs: '/lib.mjs', pdfjsWorker: '/worker.mjs', pdfjsCmaps: '/cmaps/' } },
      createElement: (tag) => new FakeEl(tag),
      body
    },
    URL: { createObjectURL: () => 'blob:fake', revokeObjectURL() {} },
    FileReader: class {
      readAsDataURL(blob) { this.result = 'data:image/jpeg;base64,' + blob.width; this.onload() }
    },
    FormData: class {
      constructor() { this.entries = [] }
      append(name, blob, filename) { this.entries.push({ name, blob, filename }) }
    },
    fetch: async (url, init) => {
      const names = init.body.entries.map((e) => Number(/page_(\d+)/.exec(e.filename)[1]))
      const full = init.body.entries.length === 1 && init.body.entries[0].blob.width >= 1000
      calls.push({ url, pages: names, full })
      return {
        ok: true,
        redirected: false,
        url,
        json: async () => ({
          pages: names.map((n, i) => {
            const [isInvoice = false, thumbCopy = null, fullCopy = thumbCopy] = verdicts[n] || []
            return { index: i + 1, is_triplicate_invoice: isInvoice, copy_no: full ? fullCopy : thumbCopy }
          })
        })
      }
    },
    Uint8Array,
    Promise,
    Object,
    String,
    Math,
    queueMicrotask
  }
  vm.createContext(context)
  vm.runInContext(SRC, context)
  const pdfjs = {
    getDocument: () => ({
      promise: openError
        ? Promise.reject(Object.assign(new Error('x'), { name: openError }))
        : Promise.resolve({
          numPages: pages,
          destroy() {},
          getPage: async () => ({
            getViewport: ({ scale }) => ({ width: 1000 * scale, height: 600 * scale }),
            render: () => ({ promise: Promise.resolve() }),
            cleanup() {}
          })
        })
    })
  }
  return { finder: context.window.InvoicePdfPage, pdfjs, calls, dialogs }
}

function pdfFile({ size = 1000, header = '%PDF-', name = '請款.pdf' } = {}) {
  return {
    name,
    size,
    slice: () => ({ arrayBuffer: async () => new TextEncoder().encode(header).buffer }),
    arrayBuffer: async () => new ArrayBuffer(8)
  }
}

test('前置過濾：超過 4 MB、不是 PDF、有密碼、超過 45 頁都擋下', async () => {
  let s = setup()
  await assert.rejects(s.finder.find(pdfFile({ size: 4 * 1024 * 1024 + 1 }), { pdfjs: s.pdfjs }), /4 MB/)
  await assert.rejects(s.finder.find(pdfFile({ header: 'GIF89' }), { pdfjs: s.pdfjs }), /不是有效的 PDF/)
  s = setup({ openError: 'PasswordException' })
  await assert.rejects(s.finder.find(pdfFile(), { pdfjs: s.pdfjs }), /密碼/)
  s = setup({ pages: 46 })
  await assert.rejects(s.finder.find(pdfFile(), { pdfjs: s.pdfjs }), /超過 45 頁（共 46 頁）/)
  assert.equal(s.calls.length, 0)
})

test('12 頁分兩批判斷，找到第 5 頁第二聯，直接帶出原解析度影像', async () => {
  const s = setup({ pages: 12, verdicts: { 5: [true, 2] } })
  const progress = []
  const found = await s.finder.find(pdfFile(), { pdfjs: s.pdfjs, onProgress: (m) => progress.push(m) })
  assert.deepEqual(s.calls.map((c) => c.pages), [[1, 2, 3, 4, 5, 6, 7, 8, 9], [10, 11, 12]])
  assert.equal(found.page, 5)
  assert.equal(found.pageCount, 12)
  assert.equal(found.copy, 2)
  assert.equal(found.name, '請款_p5.jpg')
  assert.equal(found.dataUrl, 'data:image/jpeg;base64,2000') // 最長邊 2000px
  assert.match(found.message, /已找到第 5 頁（共 12 頁）.*第二聯（扣抵聯）/)
  assert.equal(found.blob.width, 2000)
  assert.ok(progress.includes('正在分析第 10–12 頁（共 12 頁）…'))
})

test('只有第一聯：先用原解析度確認，確認後擋下', async () => {
  const s = setup({ pages: 3, verdicts: { 2: [true, 1, 1] } })
  await assert.rejects(s.finder.find(pdfFile(), { pdfjs: s.pdfjs }), /第一聯（存根聯），不能報帳/)
  assert.deepEqual(s.calls.at(-1), { url: '/invoices/pdf-pages/classify', pages: [2], full: true })
})

test('縮圖誤判第一聯，原解析度看出是第三聯時不擋', async () => {
  const s = setup({ pages: 3, verdicts: { 2: [true, 1, 3] } })
  const found = await s.finder.find(pdfFile(), { pdfjs: s.pdfjs })
  assert.equal(found.page, 2)
  assert.equal(found.copy, 3)
})

test('第二、三聯都在時跳出選擇視窗，預設聚焦第二聯，選第 4 頁就回傳第 4 頁', async () => {
  const s = setup({ pages: 6, verdicts: { 3: [true, 3], 4: [true, 2] }, chooseIndex: 1 })
  const found = await s.finder.find(pdfFile(), { pdfjs: s.pdfjs })
  const grid = s.dialogs[0].children.find((c) => c.className === 'pdf-pick-dialog__grid')
  assert.equal(grid.children.length, 2)
  assert.equal(grid.children[1].focused, true) // 第 4 頁是第二聯
  assert.equal(grid.children[0].focused, undefined)
  assert.equal(found.page, 4)
  assert.equal(s.dialogs[0].removed, true)
})

test('在選擇視窗按取消時回傳 null', async () => {
  const s = setup({ pages: 2, verdicts: { 1: [true, 2], 2: [true, 3] }, chooseIndex: 'cancel' })
  assert.equal(await s.finder.find(pdfFile(), { pdfjs: s.pdfjs }), null)
})

test('找不到三聯式發票時提示', async () => {
  const s = setup({ pages: 4 })
  await assert.rejects(s.finder.find(pdfFile(), { pdfjs: s.pdfjs }), /找不到三聯式統一發票/)
})

test('單頁 PDF 直接用原解析度判斷；聯別不清時不擋但提示確認', async () => {
  const s = setup({ pages: 1, verdicts: { 1: [true, null] } })
  const found = await s.finder.find(pdfFile(), { pdfjs: s.pdfjs })
  assert.deepEqual(s.calls, [{ url: '/invoices/pdf-pages/classify', pages: [1], full: true }])
  assert.equal(found.copy, null)
  assert.match(found.message, /聯別無法辨識，請確認不是第一聯/)
})

test('選了其他檔案（isCurrent 變 false）時中止並回傳 null', async () => {
  const s = setup({ pages: 12, verdicts: { 5: [true, 2] } })
  let current = true
  const found = await s.finder.find(pdfFile(), {
    pdfjs: s.pdfjs,
    isCurrent: () => current,
    onProgress: (m) => { if (m.startsWith('正在分析第 10')) current = false }
  })
  assert.equal(found, null)
  assert.equal(s.calls.length, 1)
})

// ---------- 裁掉四周空白 ----------
function sheet(width, height, boxes) {
  const data = new Uint8ClampedArray(width * height * 4).fill(255)
  for (const [x0, y0, x1, y1] of boxes) {
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const i = (y * width + x) * 4
      data[i] = data[i + 1] = data[i + 2] = 0
    }
  }
  return data
}

test('A4 上半部是發票：裁到發票範圍並保留少許邊距', () => {
  const { finder } = setup()
  // 200×300 的頁面，發票在 (20,30)–(180,130)
  const box = finder.trimBounds(sheet(200, 300, [[20, 30, 180, 130]]), 200, 300)
  assert.deepEqual({ ...box }, { x: 17, y: 28, w: 166, h: 104 })
})

test('頁首文字與頁碼離發票很遠：只保留內容最多的一段（發票本身）', () => {
  const { finder } = setup()
  // 頁首 (10,5)–(60,9)、發票 (20,100)–(180,200)、頁碼 (95,285)–(105,290)
  const page = sheet(200, 300, [[10, 5, 60, 9], [20, 100, 180, 200], [95, 285, 105, 290]])
  assert.deepEqual({ ...finder.trimBounds(page, 200, 300) }, { x: 17, y: 98, w: 166, h: 104 })
})

test('發票旁還有大段內容（最多的一段不到六成）時，保留全部內容的範圍，不冒險只留一段', () => {
  const { finder } = setup()
  // 上方大段文字 (20,10)–(180,90)、發票 (20,150)–(180,250)：兩段內容量接近
  const page = sheet(200, 300, [[20, 10, 180, 90], [20, 150, 180, 250]])
  assert.deepEqual({ ...finder.trimBounds(page, 200, 300) }, { x: 17, y: 5, w: 166, h: 250 })
})

test('零星雜點不算內容；整頁空白或幾乎沒有空白時不裁', () => {
  const { finder } = setup()
  const noisy = sheet(200, 300, [[20, 30, 180, 130], [190, 290, 191, 291]])
  assert.deepEqual({ ...finder.trimBounds(noisy, 200, 300) }, { x: 17, y: 28, w: 166, h: 104 })
  assert.equal(finder.trimBounds(sheet(200, 300, []), 200, 300), null)
  assert.equal(finder.trimBounds(sheet(200, 300, [[2, 2, 198, 298]]), 200, 300), null)
})
