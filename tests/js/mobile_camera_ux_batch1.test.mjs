// 測試目標：C 組欄位核對 UX 第一批（UX-01～UX-05）——輸入時即時格式檢核、必填顯示、未來日期即時警示、
//   全形數字轉半形、空白新增明細略過；以及 invoice-field-rules.js 新增的純函式。
// 注意：與 mobile_camera_add_item_c.test.mjs 相同，用最小假 DOM 在 node:vm 執行原始碼，fetch 為替身；
//   不連 API／資料庫，也不是真實瀏覽器（版面、游標、輸入法組字須另行人工驗收）。
// 執行：node --test tests/js/
// 注意：專案沒有 jsdom，這裡用最小的「假 DOM」（含簡化的選擇器）在 node:vm 內執行原始碼，fetch 以替身取代；
//   驗證的是程式流程與送出資料，不是真實瀏覽器的版面、點擊與捲動，也不連 API／資料庫。真實瀏覽器須另行驗收。
// 執行：node --test tests/js/
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const SRC = (name) => readFileSync(new URL(`../../app/static/js/${name}`, import.meta.url), 'utf8')

// ---------- 最小假 DOM ----------
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
const kebab = (s) => s.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase())

class FakeText {
  constructor(text) { this.nodeType = 3; this.data = text; this.parent = null }
  get textContent() { return this.data }
}

class FakeEl {
  constructor(tag) {
    this.nodeType = 1
    this.tag = tag.toLowerCase()
    this.attrs = {}
    this.children = []
    this.parent = null
    this.listeners = {}
    this.value = ''
    this.checked = false
    this.hidden = false
    this.disabled = false
    this.onclick = null
    this.dataset = new Proxy({}, {
      get: (_, k) => this.attrs['data-' + kebab(String(k))],
      set: (_, k, v) => { this.attrs['data-' + kebab(String(k))] = String(v); return true },
      has: (_, k) => ('data-' + kebab(String(k))) in this.attrs
    })
    const el = this
    this.classList = {
      list: () => (el.attrs.class || '').split(/\s+/).filter(Boolean),
      add(c) { const l = this.list(); if (!l.includes(c)) el.attrs.class = [...l, c].join(' ') },
      remove(c) { el.attrs.class = this.list().filter((x) => x !== c).join(' ') },
      contains(c) { return this.list().includes(c) },
      toggle(c, force) {
        const on = force === undefined ? !this.contains(c) : Boolean(force)
        if (on) this.add(c); else this.remove(c)
        return on
      }
    }
  }
  get className() { return this.attrs.class || '' }
  set className(v) { this.attrs.class = v }
  get id() { return this.attrs.id || '' }
  set id(v) { this.attrs.id = v }
  setAttribute(k, v) {
    this.attrs[k] = String(v)
    if (k === 'value') this.value = String(v)
    if (k === 'hidden') this.hidden = true
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null }
  removeAttribute(k) { delete this.attrs[k] }
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn) }
  // 事件與瀏覽器一樣往上層冒泡（input／change／click 都會冒泡；target 保持原始元素）
  fire(t, ev = {}) {
    const event = { type: t, target: this, ...ev }
    for (let n = this; n && n.nodeType === 1; n = n.parent) (n.listeners[t] || []).forEach((fn) => fn(event))
  }
  click() { if (this.onclick) return this.onclick({ target: this }); this.fire('click') }
  append(...nodes) {
    nodes.forEach((n) => {
      const node = typeof n === 'string' ? new FakeText(n) : n
      node.parent = this
      this.children.push(node)
    })
  }
  scrollIntoView() {}
  focus() {}
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null }
  after(node) {
    const i = this.parent.children.indexOf(this)
    node.parent = this.parent
    this.parent.children.splice(i + 1, 0, node)
  }
  get textContent() { return this.children.map((c) => c.textContent).join('') }
  set textContent(v) {
    this.children = []
    if (v) this.append(new FakeText(String(v)))
  }
  matches(sel) {
    return sel.split(',').some((part) => {
      const tokens = part.trim().match(/#[\w-]+|\.[\w-]+|\[[^\]]+\]|^[a-z][a-z0-9]*/gi) || []
      return tokens.every((t) => {
        if (t[0] === '#') return this.attrs.id === t.slice(1)
        if (t[0] === '.') return this.classList.contains(t.slice(1))
        if (t[0] === '[') {
          const m = t.match(/^\[([\w-]+)(?:="?([^"\]]*)"?)?\]$/)
          return m[1] in this.attrs && (m[2] === undefined || this.attrs[m[1]] === m[2])
        }
        return this.tag === t.toLowerCase()
      })
    })
  }
  closest(sel) {
    for (let n = this; n && n.nodeType === 1; n = n.parent) if (n.matches(sel)) return n
    return null
  }
  querySelectorAll(sel) {
    const parts = sel.trim().split(/\s+/)
    const out = []
    const walk = (node, ancestors) => {
      node.children.forEach((c) => {
        if (c.nodeType !== 1) return
        if (c.matches(parts[parts.length - 1])) {
          // 後代選擇器：祖先鏈需依序符合前面的片段
          let i = parts.length - 2
          for (let a = c.parent; a && i >= 0; a = a.parent) if (a.nodeType === 1 && a.matches(parts[i])) i--
          if (i < 0) out.push(c)
        }
        walk(c, ancestors)
      })
    }
    walk(this, [])
    return out
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null }
}

// ---------- 載入頁面與腳本 ----------
const ID = (el, id) => { el.attrs.id = id; return el }

let AI_OVERRIDE = {}
let AI_WARNINGS = []
function aiInvoice() {
  const base = {
    recognition_id: 'rec-1',
    is_triplicate: true,
    warnings: AI_WARNINGS,
    invoice: {
      invoice_track: 'TL', invoice_number: '28281500', invoice_date: '2020-01-15',
      buyer_name: '', buyer_tax_id: '', seller_name: '範例商行', seller_tax_id: '27601907',
      tax_type: 'taxable', sales_amount: '300', tax_amount: '15', total_amount: '315', total_amount_zh: '',
      items: [
        { line_no: 1, item_name: '原子筆', quantity: '2', unit_price: '50', line_amount: '100' },
        { line_no: 2, item_name: '筆記本', quantity: '4', unit_price: '50', line_amount: '200' }
      ]
    }
  }
  base.invoice = { ...base.invoice, ...AI_OVERRIDE }
  return base
}

async function setup() {
  const doc = new FakeEl('document')
  const root = new FakeEl('body')
  doc.append(root)
  const shell = new FakeEl('main'); shell.setAttribute('data-upload-mode', 'file'); root.append(shell)
  const mk = (tag, id, cls) => {
    const el = ID(new FakeEl(tag), id)
    if (cls) el.attrs.class = cls
    shell.append(el)
    return el
  }
  mk('section', 'step-upload', 'mobile-step-section')
  mk('section', 'step-preview', 'mobile-step-section')
  const stepFields = mk('section', 'step-fields', 'mobile-step-section')
  mk('section', 'step-confirm', 'mobile-step-section')
  mk('div', 'skipped-blank-items')
  { const box = ID(new FakeEl('div'), 'required-summary'); box.hidden = true; stepFields.append(box) } // 與正式樣板相同，初次載入隱藏
  mk('div', 'business-warnings'); mk('p', 'business-warnings-title'); mk('ul', 'business-warnings-list')
  mk('section', 'step-success', 'mobile-step-section')
  const fields = ID(new FakeEl('div'), 'fields-container'); stepFields.append(fields)
  const ids = {}
  for (const id of ['file-album-upload', 'btn-recognize', 'btn-confirm-fields', 'btn-check-duplicate', 'btn-final-upload', 'finalAck', 'uploaderAck', 'final-submit-group']) {
    ids[id] = mk(id.startsWith('btn') ? 'button' : 'input', id)
  }
  ids['btn-recognize'].textContent = '辨識內容'

  const calls = []
  const alerts = []
  const timers = []
  const json = (data, ok = true) => ({ ok, redirected: false, url: '', json: async () => data })
  const routes = {
    '/invoices/mobile-recognize': () => json(aiInvoice()),
    '/invoices/check-required': () => json({ required_complete: true, missing: [] }),
    '/invoices/check-duplicate': () => json({ is_duplicate: false }),
    '/invoices/mobile-upload': () => json({ status: 'pending_department_approval', modified_fields: [], warnings: [] })
  }
  const listeners = {}
  const store = {}
  const sandbox = {
    document: Object.assign(doc, {
      createElement: (t) => new FakeEl(t),
      createTextNode: (t) => new FakeText(t),
      addEventListener: (t, fn) => { listeners[t] = fn }
    }),
    alert: (m) => alerts.push(m),
    // 假計時器：不自動執行，測試用 flushTimers() 明確觸發（核對頁即時警示的延遲）
    setTimeout: (fn) => { timers.push(fn); return timers.length },
    clearTimeout: (id) => { if (id) timers[id - 1] = null },
    fetch: async (url, opts) => { calls.push({ url, opts }); return routes[url]() },
    URL: Object.assign(function () {}, { createObjectURL: () => 'blob:x', revokeObjectURL() {} }),
    FormData,
    Date,
    JSON,
    localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v } },
    console
  }
  sandbox.window = sandbox
  sandbox.window.scrollTo = () => {}
  sandbox.window.location = { pathname: '/invoices/upload', href: '' }
  sandbox.window.addEventListener = () => {}
  sandbox.window.isSecureContext = true
  sandbox.globalThis = sandbox
  vm.createContext(sandbox)
  vm.runInContext(SRC('invoice-field-rules.js'), sandbox)
  vm.runInContext(SRC('mobile-camera.js'), sandbox)
  listeners.DOMContentLoaded()

  // 電腦上傳頁：選單頁 PDF → 辨識（API 以替身回傳兩筆 AI 明細）
  const pdf = new File(['%PDF-1.4'], 'a.pdf', { type: 'application/pdf' })
  ids['file-album-upload'].onchange({ target: { files: [pdf] } })
  ids['btn-recognize'].click()
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(calls[0].url, '/invoices/mobile-recognize')

  const page = {
    calls, alerts, fields, ids, routes, json,
    async flushTimers() {
      const pending = timers.splice(0).filter(Boolean)
      pending.forEach((fn) => fn())
      await new Promise((r) => setTimeout(r, 0))
    },
    addButton: () => fields.querySelectorAll('button').find((b) => b.textContent === '新增明細'),
    rows: () => fields.querySelectorAll('.item-row'),
    input: (row, name) => row.querySelector(`[data-item-field="${name}"]`),
    type(row, name, value) {
      const el = page.input(row, name)
      el.value = value
      el.fire('input')
      el.fire('change')
    },
    async submit() {
      ids['uploaderAck'].checked = true
      ids['btn-confirm-fields'].click()
      await new Promise((r) => setTimeout(r, 0))
      return calls.filter((c) => c.url === '/invoices/check-required').length
    }
  }
  return page
}


// ---------- 測試輔助 ----------
const lastBody = (page, url) => JSON.parse([...page.calls].reverse().find((c) => c.url === url).opts.body)
async function load(override = {}) {
  AI_OVERRIDE = override
  try {
    return await setup()
  } finally {
    AI_OVERRIDE = {}
  }
}
const ctl = (page, field) => page.fields.querySelector(`#f-${field}`)
const hintOf = (page, field) => page.fields.querySelector(`#hint-f-${field}`)
const typeLive = (el, value) => { el.value = value; el.fire('input') } // 只觸發 input，不離開欄位
const rulesOf = async () => {
  const sandbox = { globalThis: {} }
  sandbox.window = sandbox
  vm.createContext(sandbox)
  vm.runInContext(SRC('invoice-field-rules.js'), sandbox)
  return sandbox.InvoiceFieldRules
}

// ---------- UX-01 即時格式檢核 ----------
test('UX-01：統編輸入中立即紅色，完成 8 碼半形數字立即綠色（不需離開欄位）', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  typeLive(el, '1234567')
  assert.ok(el.classList.contains('is-invalid'))
  assert.ok(!el.classList.contains('is-valid'))
  assert.ok(hintOf(page, 'seller_tax_id').classList.contains('field-hint--error'))
  typeLive(el, '12345678')
  assert.ok(el.classList.contains('is-valid'))
  assert.ok(!el.classList.contains('is-invalid'))
  assert.ok(hintOf(page, 'seller_tax_id').classList.contains('field-hint--ok'))
  typeLive(el, '1234567') // 刪除一碼又立即回到紅色
  assert.ok(el.classList.contains('is-invalid'))
})

test('UX-01：初次載入 AI 辨識值違反格式就顯示錯誤；格式正確的顯示綠色', async () => {
  const page = await load({ seller_tax_id: '1234567' })
  assert.ok(ctl(page, 'seller_tax_id').classList.contains('is-invalid'))
  assert.ok(ctl(page, 'invoice_number').classList.contains('is-valid'))
})

test('UX-01：「已修改」與「格式正確」分開——修改後同時有 is-modified 與 is-valid', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  typeLive(el, '12345678') // AI 值是 27601907，改過
  assert.ok(el.closest('.field-group').classList.contains('is-modified'))
  assert.ok(el.classList.contains('is-valid'))
  typeLive(el, '27601907') // 改回 AI 值：不再是已修改，仍是格式正確
  assert.ok(!el.closest('.field-group').classList.contains('is-modified'))
  assert.ok(el.classList.contains('is-valid'))
})

test('UX-01：選填欄位空白不報錯；有輸入但格式錯誤仍報錯', async () => {
  const page = await load()
  const el = ctl(page, 'buyer_tax_id')
  assert.ok(!el.classList.contains('is-invalid'))
  assert.ok(hintOf(page, 'buyer_tax_id').hidden)
  typeLive(el, 'abc')
  assert.ok(el.classList.contains('is-invalid'))
  typeLive(el, '')
  assert.ok(!el.classList.contains('is-invalid'))
  assert.ok(hintOf(page, 'buyer_tax_id').hidden)
})

test('UX-01：明細的數量與金額同樣即時檢核', async () => {
  const page = await load()
  const row = page.rows()[0]
  const qty = page.input(row, 'quantity')
  typeLive(qty, '1.23456')
  assert.ok(qty.classList.contains('is-invalid'))
  typeLive(qty, '2')
  assert.ok(qty.classList.contains('is-valid'))
})

// ---------- UX-02 必填顯示 ----------
test('UX-02：必填欄位從載入就有「*必填」，初次空白不畫紅框，但有 AI 缺漏提示', async () => {
  const page = await load({ invoice_date: '' })
  const label = ctl(page, 'invoice_date').closest('.field-group').querySelector('.field-required')
  assert.equal(label.textContent, '*必填')
  assert.ok(!ctl(page, 'invoice_date').classList.contains('is-missing'))
  const note = page.fields.querySelector('#ai-missing-note')
  assert.ok(!note.hidden)
  assert.match(note.textContent, /發票日期/)
  typeLive(ctl(page, 'invoice_date'), '2020-01-15') // 補上後從提示移除
  assert.ok(note.hidden)
})

test('UX-02：開始編輯後清空必填欄位立即標紅缺漏；補回後消失', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  typeLive(el, '')
  assert.ok(el.classList.contains('is-missing'))
  assert.match(page.fields.querySelector('.field-missing').textContent, /請補填/)
  typeLive(el, '27601907')
  assert.ok(!el.classList.contains('is-missing'))
})

// ---------- UX-03 未來日期 ----------
test('UX-03：選未來日期立即顯示警示、改回過去立即消失，且不阻擋確認', async () => {
  const page = await load()
  const el = ctl(page, 'invoice_date')
  typeLive(el, '2999-01-01')
  assert.equal(page.fields.querySelectorAll('.field-date-live-warning').length, 1)
  assert.ok(!el.classList.contains('is-invalid'))
  typeLive(el, '2020-01-15')
  assert.equal(page.fields.querySelectorAll('.field-date-live-warning').length, 0)
  typeLive(el, '2999-01-01')
  await page.submit() // 仍可進入後續流程（沒有阻擋性錯誤）
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-required').length, 1)
  assert.deepEqual(page.alerts, [])
})

test('UX-03：台灣日期判斷不受 UTC 日期影響', async () => {
  const Rules = await rulesOf()
  const now = new Date('2026-10-31T16:30:00Z') // 台灣已是 11/01 00:30
  assert.equal(Rules.taipeiToday(now), '2026-11-01')
  assert.equal(Rules.isFutureDate('2026-11-01', now), false)
  assert.equal(Rules.isFutureDate('2026-11-02', now), true)
  assert.equal(Rules.isFutureDate('2026-02-30', now), false) // 無效日期不算未來日期
  assert.equal(Rules.isFutureDate('', now), false)
})

// ---------- UX-04 全形轉半形 ----------
test('UX-04：全形數字自動轉半形並保留前導零，立即重新檢核', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  typeLive(el, '００１２３４５６')
  assert.equal(el.value, '00123456')
  assert.ok(el.classList.contains('is-valid'))
  const total = ctl(page, 'total_amount')
  typeLive(total, '１２３')
  assert.equal(total.value, '123')
})

test('UX-04：只轉全形數字，其他字元不刪除；字軌不套用', async () => {
  const Rules = await rulesOf()
  assert.equal(Rules.toHalfWidthDigits('Ａ１-２ x'), 'Ａ1-2 x')
  assert.equal(Rules.toHalfWidthDigits('０００'), '000')
  assert.ok(!Rules.HALF_WIDTH_FIELDS.includes('invoice_track'))
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  typeLive(el, '１２３４５６７Ａ')
  assert.equal(el.value, '1234567Ａ')
  assert.ok(el.classList.contains('is-invalid'))
})

// ---------- UX-05 空白新增明細 ----------
test('UX-05：完全空白的新增明細略過並通知筆數，不送出', async () => {
  const page = await load()
  page.addButton().click()
  page.addButton().click()
  await page.submit()
  const body = lastBody(page, '/invoices/check-required')
  assert.equal(body.items.length, 2) // 只有兩筆 AI 明細
  assert.match(globalSkipped(page), /已略過 2 筆空白的新增明細/)
  assert.equal(page.rows().length, 4) // 畫面上的列不被刪除
})

function globalSkipped(page) {
  let root = page.fields
  while (root.parent) root = root.parent
  return root.querySelector('#skipped-blank-items').textContent
}

test('UX-05：部分填寫的新增明細不略過、仍被攔截；數字 0 不是空白', async () => {
  const page = await load()
  page.addButton().click()
  page.type(page.rows()[2], 'quantity', '0')
  await page.submit()
  assert.equal(lastBody(page, '/invoices/check-required').items.length, 3) // 含該列
  assert.ok(page.alerts.some((m) => /明細 3/.test(m))) // 缺品名／金額被前端格式檢查擋下
  assert.equal(globalSkipped(page), '')
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-duplicate').length, 0)
})

test('UX-05：isBlankItem 前後端共用——空白字串、空白字元為空，"0" 與 0 不是', async () => {
  const Rules = await rulesOf()
  assert.equal(Rules.isBlankItem({ item_name: '', quantity: ' ', unit_price: '', line_amount: '' }), true)
  assert.equal(Rules.isBlankItem({ item_name: '', quantity: '', unit_price: '', line_amount: '0' }), false)
  assert.equal(Rules.isBlankItem({ item_name: '', quantity: 0, unit_price: '', line_amount: '' }), false)
})

// =====================================================================
// 修正批次回歸測試（Code Review P1-1、P1-2、P2-1、P2-2 與 UX-03 過期回應）
// 這些案例原本是探測腳本；修正前 P1-1、P1-2、P2-1、UX-03 必填檢核期間修改 的案例會失敗。
// =====================================================================
const tick = () => new Promise((r) => setTimeout(r, 0))
const pageRoot = (page) => { let r = page.fields; while (r.parent) r = r.parent; return r }
const skippedNote = (page) => pageRoot(page).querySelector('#skipped-blank-items')
const noApiCalls = (page, before) => page.calls.length === before

// ---------- P1-1 輸入法組字 ----------
test('P1-1：組字中（isComposing）全形輸入值不被改寫，也沒有 API 呼叫', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  const before = page.calls.length
  el.fire('compositionstart')
  el.value = '００１２'
  el.fire('input', { isComposing: true })
  assert.equal(el.value, '００１２')
  assert.ok(noApiCalls(page, before))
})

test('P1-1：只靠 compositionstart 追蹤（input 未帶 isComposing，如 Safari）也不改寫', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  el.fire('compositionstart')
  el.value = '００１２'
  el.fire('input')
  assert.equal(el.value, '００１２')
})

test('P1-1：compositionend 後轉半形、保留前導零、立即重新檢核並更新「已修改」', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  const before = page.calls.length
  el.fire('compositionstart')
  el.value = '００１２３４５６'
  el.fire('input', { isComposing: true })
  assert.equal(el.value, '００１２３４５６')
  el.fire('compositionend')
  assert.equal(el.value, '00123456')
  assert.ok(el.classList.contains('is-valid'))
  assert.ok(el.closest('.field-group').classList.contains('is-modified')) // AI 值是 27601907
  assert.match(el.closest('.field-group').querySelector('.field-modified').textContent, /27601907/) // AI 原值仍顯示
  assert.ok(noApiCalls(page, before))
})

test('P1-1：組字結束後格式錯誤也立即標紅；組字結束後狀態不再被視為組字中', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  el.fire('compositionstart')
  el.value = '１２３'
  el.fire('compositionend')
  assert.equal(el.value, '123')
  assert.ok(el.classList.contains('is-invalid'))
  typeLive(el, '４５６') // 之後的一般輸入照常轉換
  assert.equal(el.value, '456')
})

test('P1-1：明細欄位同樣遵守組字流程，結束後更新該列「已修改」', async () => {
  const page = await load()
  const input = page.input(page.rows()[0], 'line_amount') // AI 值 100
  input.fire('compositionstart')
  input.value = '２００'
  input.fire('input', { isComposing: true })
  assert.equal(input.value, '２００')
  input.fire('compositionend')
  assert.equal(input.value, '200')
  assert.ok(input.classList.contains('is-valid'))
  assert.ok(page.rows()[0].classList.contains('is-modified'))
})

test('P1-1：一般輸入與貼上（無組字）不退化', async () => {
  const page = await load()
  const el = ctl(page, 'total_amount')
  typeLive(el, '００１２') // 貼上整段全形
  assert.equal(el.value, '0012')
  typeLive(el, '315')
  assert.ok(el.classList.contains('is-valid'))
})

// ---------- P1-2 空白新增明細來源 ----------
test('P1-2：按「新增明細」建立的空白列，1 筆略過 1 筆', async () => {
  const page = await load()
  page.addButton().click()
  await page.submit()
  assert.match(skippedNote(page).textContent, /已略過 1 筆空白的新增明細/)
})

test('P1-2：清空 AI 明細不計入新增空白筆數，且該列與其修改都不送出', async () => {
  const page = await load()
  const row = page.rows()[1] // AI 明細 line_no 2
  for (const f of ['item_name', 'quantity', 'unit_price', 'line_amount']) page.type(row, f, '')
  await page.submit()
  assert.equal(skippedNote(page).textContent, '')
  assert.ok(skippedNote(page).hidden)
  const body = lastBody(page, '/invoices/check-required')
  assert.deepEqual(body.items.map((i) => i.source_line_no), [1])
})

test('P1-2：AI 明細被清空、另有新增空白列時只計新增的那一筆', async () => {
  const page = await load()
  for (const f of ['item_name', 'quantity', 'unit_price', 'line_amount']) page.type(page.rows()[1], f, '')
  page.addButton().click()
  await page.submit()
  assert.match(skippedNote(page).textContent, /已略過 1 筆/)
})

test('P1-2：系統補的占位列（AI 沒有明細）不是使用者新增的，不計數', async () => {
  const page = await load({ items: [] })
  assert.equal(page.rows().length, 1) // 占位列
  page.addButton().click() // 使用者新增一列
  const rows = page.rows()
  page.type(rows[1], 'item_name', '文具'); page.type(rows[1], 'line_amount', '300')
  await page.submit()
  assert.equal(skippedNote(page).textContent, '') // 占位列空白但不是使用者新增
  const body = lastBody(page, '/invoices/check-required')
  assert.equal(body.items.length, 1)
})

test('P1-2：完全沒有合格明細時仍阻擋，不進入查重', async () => {
  const page = await load({ items: [] })
  page.addButton().click()
  await page.submit()
  assert.ok(page.alerts.some((m) => /至少填寫一筆品名明細/.test(m)))
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-duplicate').length, 0)
})

test('P1-2：「0」與 "0" 不是空白——部分填寫仍阻擋、不計入略過', async () => {
  const page = await load()
  page.addButton().click()
  page.type(page.rows()[2], 'unit_price', '0')
  await page.submit()
  assert.ok(page.alerts.some((m) => /明細 3/.test(m)))
  assert.equal(skippedNote(page).textContent, '')
  assert.equal(lastBody(page, '/invoices/check-required').items.length, 3)
})

test('P1-2：必填檢核請求與實際提交（業務警示預覽）的明細內容一致', async () => {
  const page = await load()
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [], checked_on: '2026-10-31' })
  page.addButton().click() // 空白新增列：兩邊都不含
  await page.submit()
  await tick()
  const check = lastBody(page, '/invoices/check-required').items
  const payload = lastBody(page, '/invoices/check-warnings').items
  assert.equal(check.length, 2)
  assert.deepEqual(payload, check)
})

// ---------- P2-1 aria-invalid ----------
test('P2-1：必填缺漏解除後，仍是格式錯誤的欄位保留 aria-invalid', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  typeLive(el, '')
  assert.ok(el.classList.contains('is-missing'))
  assert.equal(el.getAttribute('aria-invalid'), 'true')
  typeLive(el, '123') // 缺漏解除，但格式錯誤
  assert.ok(!el.classList.contains('is-missing'))
  assert.ok(el.classList.contains('is-invalid'))
  assert.equal(el.getAttribute('aria-invalid'), 'true')
  typeLive(el, '27601907') // 沒有任何錯誤才移除
  assert.equal(el.getAttribute('aria-invalid'), null)
  assert.ok(el.classList.contains('is-valid'))
})

test('P2-1：aria-invalid 與紅色錯誤一致（錯誤時有、修正後沒有）', async () => {
  const page = await load()
  const el = ctl(page, 'seller_tax_id')
  typeLive(el, '1')
  assert.ok(el.classList.contains('is-invalid') && el.getAttribute('aria-invalid') === 'true')
  typeLive(el, '12345678')
  assert.ok(!el.classList.contains('is-invalid') && el.getAttribute('aria-invalid') === null)
})

// ---------- P2-2 AI 缺漏提示即時同步 ----------
test('P2-2：AI 沒辨識出明細時，在明細欄位打字（尚未離開欄位）提示就更新', async () => {
  const page = await load({ items: [] })
  const note = page.fields.querySelector('#ai-missing-note')
  assert.ok(!note.hidden)
  assert.match(note.textContent, /品名明細/)
  const el = page.input(page.rows()[0], 'item_name')
  el.value = '文具'
  el.fire('input') // 只觸發 input，沒有 change
  assert.ok(note.hidden)
  el.value = ''
  el.fire('input')
  assert.ok(!note.hidden)
})

// ---------- UX-03 過期 API 回應 ----------
test('UX-03：警示請求進行中改成非未來日期，舊回應不顯示警示、不進入確認頁', async () => {
  const page = await load()
  let release
  page.routes['/invoices/check-warnings'] = () =>
    new Promise((resolve) => {
      release = () => resolve(page.json({ warnings: [{ field: 'invoice_date', code: 'invoice_date_future', message: 'x' }], checked_on: '2026-10-31' }))
    })
  const el = ctl(page, 'invoice_date')
  typeLive(el, '2999-01-01')
  page.ids['uploaderAck'].checked = true
  page.ids['btn-confirm-fields'].click()
  await tick(); await tick()
  typeLive(el, '2020-01-15'); el.fire('change')
  release(); await tick(); await tick()
  assert.equal(page.fields.querySelectorAll('.field-business-warning').length, 0)
  assert.equal(page.fields.querySelectorAll('.field-date-live-warning').length, 0)
  assert.ok(page.alerts.some((m) => /檢查期間欄位又被修改/.test(m)))
})

test('UX-03：必填檢核進行中改日期，不會拿檢核前的舊日期去取警示或組送出內容', async () => {
  const page = await load()
  let release
  page.routes['/invoices/check-required'] = () =>
    new Promise((resolve) => { release = () => resolve(page.json({ required_complete: true, missing: [] })) })
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [], checked_on: '2026-10-31' })
  const el = ctl(page, 'invoice_date')
  page.ids['uploaderAck'].checked = true
  page.ids['btn-confirm-fields'].click()
  await tick()
  typeLive(el, '2999-01-01'); el.fire('change')
  release(); await tick(); await tick(); await tick()
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-warnings').length, 0)
  assert.ok(page.alerts.some((m) => /檢查期間欄位又被修改/.test(m)))
  assert.equal(page.fields.querySelectorAll('.field-date-live-warning').length, 1) // 即時警示仍在
})

test('UX-03：未來日期不阻擋——API 回報未來日期警示時仍可繼續到確認頁', async () => {
  const page = await load()
  page.routes['/invoices/check-warnings'] = () =>
    page.json({ warnings: [{ field: 'invoice_date', code: 'invoice_date_future', message: 'x' }], checked_on: '2026-10-31' })
  typeLive(ctl(page, 'invoice_date'), '2999-01-01')
  await page.submit(); await tick()
  assert.deepEqual(page.alerts, [])
  assert.equal(page.fields.querySelectorAll('.field-date-live-warning').length, 0) // 由 API 警示取代，沒有重複
  assert.equal(page.fields.querySelectorAll('.field-business-warning').length, 1)
})

// =====================================================================
// 最後一項 P2：整列明細逐欄清空後，不應殘留該列的必填缺漏提示
// （Chromium 實測：先清品名會標紅，之後其他欄位也清空、整列變成空白，標示仍留著直到按確認）
// =====================================================================
const ITEM_FIELD_LIST = ['item_name', 'quantity', 'unit_price', 'line_amount']
const clearField = (page, row, name) => page.type(row, name, '')
const clearRow = (page, row) => ITEM_FIELD_LIST.forEach((f) => clearField(page, row, f))
const missingIn = (row) => row.querySelectorAll('.is-missing')
const summaryBox = (page) => pageRoot(page).querySelector('#required-summary')

test('P2 殘留缺漏：部分填寫的明細（只清品名）顯示缺漏並進入摘要', async () => {
  const page = await load()
  const row = page.rows()[0]
  clearField(page, row, 'item_name')
  assert.equal(missingIn(row).length, 1)
  assert.match(summaryBox(page).textContent, /第 1 筆明細的品名/)
})

test('P2 殘留缺漏：逐欄清空到整列空白，該列缺漏標示與摘要都消失', async () => {
  const page = await load()
  const row = page.rows()[0]
  clearRow(page, row) // 品名最先被清，會先被標紅
  assert.equal(missingIn(row).length, 0)
  assert.equal(row.querySelectorAll('.field-missing').length, 0)
  assert.ok(summaryBox(page).hidden)
})

test('P2 殘留缺漏：清空後重新填入部分欄位，缺漏提示重新出現（已補上的不恢復）', async () => {
  const page = await load()
  const row = page.rows()[0]
  clearRow(page, row)
  assert.equal(missingIn(row).length, 0)
  page.type(row, 'quantity', '3') // 只填數量：品名仍缺
  assert.equal(missingIn(row).length, 1)
  assert.ok(page.input(row, 'item_name').classList.contains('is-missing'))
  assert.match(summaryBox(page).textContent, /第 1 筆明細的品名/)
  page.type(row, 'item_name', '文具') // 補上後該欄不再缺漏
  assert.equal(missingIn(row).length, 0)
})

test('P2 殘留缺漏：清空一列不影響其他列的缺漏與格式錯誤（含 aria-invalid）', async () => {
  const page = await load()
  const [row1, row2] = page.rows()
  clearField(page, row2, 'item_name') // 第 2 列缺品名
  const qty2 = page.input(row2, 'quantity')
  page.type(row2, 'quantity', '1.23456') // 第 2 列數量格式錯誤
  assert.ok(qty2.classList.contains('is-invalid'))
  clearRow(page, row1)
  assert.equal(missingIn(row1).length, 0)
  assert.equal(missingIn(row2).length, 1) // 第 2 列仍缺品名
  assert.ok(page.input(row2, 'item_name').classList.contains('is-missing'))
  assert.ok(qty2.classList.contains('is-invalid'))
  assert.equal(qty2.getAttribute('aria-invalid'), 'true')
  assert.match(summaryBox(page).textContent, /第 2 筆明細的品名/)
  assert.doesNotMatch(summaryBox(page).textContent, /第 1 筆明細/)
})

test('P2 殘留缺漏：輸入 0 不是空白——整列只剩 0 時缺漏仍在', async () => {
  const page = await load()
  const row = page.rows()[0]
  clearField(page, row, 'item_name')
  clearField(page, row, 'quantity')
  clearField(page, row, 'line_amount')
  page.type(row, 'unit_price', '0') // 單價改成 0（原為 50），其餘皆空
  assert.equal(page.input(row, 'unit_price').value, '0')
  assert.ok(page.input(row, 'item_name').classList.contains('is-missing'))
})

test('P2 殘留缺漏：清空 AI 明細整列仍不計入「空白新增明細」，且不送出', async () => {
  const page = await load()
  clearRow(page, page.rows()[1])
  assert.equal(missingIn(page.rows()[1]).length, 0)
  await page.submit()
  assert.equal(skippedNote(page).textContent, '')
  assert.deepEqual(lastBody(page, '/invoices/check-required').items.map((i) => i.source_line_no), [1])
})


// =====================================================================
// 第一批 UX 合併後的 3 個 bug：國字大寫同步、核對頁即時金額警示、AI 缺漏提示在使用者補填後清除
// =====================================================================
const warningsOf = (page) => page.fields.querySelectorAll('.field-business-warning')
const visibleAiWarnings = (page) => page.fields.querySelectorAll('.field-warning').filter((n) => !n.hidden)

test('Bug1：amountToChinese 轉換（含中間零、萬／億段、無法轉換回 null）', async () => {
  const R = await rulesOf()
  assert.equal(R.amountToChinese('3463'), '參仟肆佰陸拾參元整')
  assert.equal(R.amountToChinese('34630'), '參萬肆仟陸佰參拾元整')
  assert.equal(R.amountToChinese('1,050'), '壹仟零伍拾元整')
  assert.equal(R.amountToChinese('10005'), '壹萬零伍元整')
  assert.equal(R.amountToChinese('100000000'), '壹億元整')
  assert.equal(R.amountToChinese('100000005'), '壹億零伍元整')
  assert.equal(R.amountToChinese('0'), '零元整')
  assert.equal(R.amountToChinese('12.5'), null)
  assert.equal(R.amountToChinese(''), null)
  assert.equal(R.amountToChinese('abc'), null)
})

test('Bug1：修改總計後國字大寫即時更新，不殘留舊值，並記入修改紀錄', async () => {
  const page = await load({ sales_amount: '32981', tax_amount: '1649', total_amount: '34630', total_amount_zh: '參萬肆仟陸佰參拾元整' })
  typeLive(ctl(page, 'total_amount'), '3463')
  assert.equal(ctl(page, 'total_amount_zh').value, '參仟肆佰陸拾參元整')
  typeLive(ctl(page, 'total_amount'), '')
  assert.equal(ctl(page, 'total_amount_zh').value, '')
  typeLive(ctl(page, 'total_amount'), '34630')
  assert.equal(ctl(page, 'total_amount_zh').value, '參萬肆仟陸佰參拾元整')
  typeLive(ctl(page, 'total_amount'), '3463')
  await page.submit(); await tick()
  const body = lastBody(page, '/invoices/check-warnings')
  assert.equal(body.total_amount_zh, '參仟肆佰陸拾參元整')
})

test('Bug1：使用者自己改過國字大寫就不覆蓋；清空後恢復自動', async () => {
  const page = await load({ total_amount: '315', total_amount_zh: '' })
  typeLive(ctl(page, 'total_amount_zh'), '參佰壹拾伍元')
  typeLive(ctl(page, 'total_amount'), '3463')
  assert.equal(ctl(page, 'total_amount_zh').value, '參佰壹拾伍元')
  typeLive(ctl(page, 'total_amount_zh'), '')
  typeLive(ctl(page, 'total_amount'), '3464')
  assert.equal(ctl(page, 'total_amount_zh').value, '參仟肆佰陸拾肆元整')
})

test('Bug2：總計與銷售額＋稅額不一致時，核對頁稍後顯示警示；改回一致後消失', async () => {
  const page = await load({ sales_amount: '32981', tax_amount: '1649', total_amount: '34630' })
  let mismatch = true
  page.routes['/invoices/check-warnings'] = () =>
    page.json({ warnings: mismatch ? [{ field: 'total_amount', code: 'total_amount_mismatch', message: 'x' }] : [], checked_on: '2026-11-01' })
  typeLive(ctl(page, 'total_amount'), '3463')
  assert.equal(warningsOf(page).length, 0) // 尚未到延遲時間
  await page.flushTimers()
  assert.equal(warningsOf(page).length, 1)
  assert.deepEqual(lastBody(page, '/invoices/check-warnings').total_amount, '3463')
  mismatch = false
  typeLive(ctl(page, 'total_amount'), '34630')
  assert.equal(warningsOf(page).length, 0) // 修改當下舊警示立即清除
  await page.flushTimers()
  assert.equal(warningsOf(page).length, 0)
})

test('Bug2：即時警示請求進行中又修改，舊回應不顯示；API 失敗時不顯示也不阻擋', async () => {
  const page = await load()
  page.routes['/invoices/check-warnings'] = () =>
    page.json({ warnings: [{ field: 'total_amount', code: 'total_amount_mismatch', message: 'x' }], checked_on: '2026-11-01' })
  typeLive(ctl(page, 'total_amount'), '1')
  const flushing = page.flushTimers()
  typeLive(ctl(page, 'total_amount'), '315') // 回應回來前又修改
  await flushing
  assert.equal(warningsOf(page).length, 0)
  delete page.routes['/invoices/check-warnings'] // 之後的請求會丟錯
  typeLive(ctl(page, 'total_amount'), '2')
  await page.flushTimers()
  assert.equal(warningsOf(page).length, 0)
  assert.deepEqual(page.alerts, [])
})

test('Bug2：與警示無關的欄位（名稱）修改不呼叫 API 預覽', async () => {
  const page = await load()
  typeLive(ctl(page, 'seller_name'), '新商行')
  await page.flushTimers()
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-warnings').length, 0)
})

const DATE_MISSING = { field: 'invoice_date', code: 'invoice_date_invalid', message: '無法辨識發票日期，請輸入' }
async function loadWithWarnings(warnings, override = {}) {
  AI_WARNINGS = warnings
  try {
    return await load(override)
  } finally {
    AI_WARNINGS = []
  }
}
const summaryItems = (page) => pageRoot(page).querySelector('#recognition-warnings')

test('Bug3：AI 沒辨識到日期，使用者輸入有效日期後，「請輸入」提示移除；未來日期警示仍在', async () => {
  const page = await loadWithWarnings([DATE_MISSING], { invoice_date: null })
  assert.equal(visibleAiWarnings(page).length, 1) // 載入時顯示
  typeLive(ctl(page, 'invoice_date'), '2999-11-28')
  assert.equal(visibleAiWarnings(page).length, 0)
  assert.equal(page.fields.querySelectorAll('.field-date-live-warning').length, 1)
})

test('Bug3：使用者改回與 AI 相同的值（仍是空白）時提示恢復；有值又清空時以必填缺漏處理', async () => {
  const page = await loadWithWarnings([DATE_MISSING], { invoice_date: null })
  typeLive(ctl(page, 'invoice_date'), '2026-11-01')
  assert.equal(visibleAiWarnings(page).length, 0)
  typeLive(ctl(page, 'invoice_date'), '')
  assert.equal(visibleAiWarnings(page).length, 1)
})

test('Bug3：不相關欄位的 AI 提示、明細提示不受影響', async () => {
  const items = { field: 'items', code: 'items_missing', message: '未辨識到品名明細，請輸入' }
  const page = await loadWithWarnings([DATE_MISSING, items], { invoice_date: null })
  typeLive(ctl(page, 'invoice_date'), '2026-11-01')
  const kept = visibleAiWarnings(page).map((n) => n.textContent)
  assert.deepEqual(kept.filter((t) => t.includes('日期')), [])
})
