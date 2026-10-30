// 測試目標：app/static/js/mobile-camera.js 核對頁既有的「新增明細」按鈕——新增空白明細、連續新增、50 筆上限、
//   source_line_no 為 null、送出 payload、數量／單價／金額驗證、不影響 AI 辨識的明細。
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

function aiInvoice() {
  return {
    recognition_id: 'rec-1',
    is_triplicate: true,
    warnings: [],
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
  mk('section', 'step-success', 'mobile-step-section')
  const fields = ID(new FakeEl('div'), 'fields-container'); stepFields.append(fields)
  const ids = {}
  for (const id of ['file-album-upload', 'btn-recognize', 'btn-confirm-fields', 'btn-check-duplicate', 'btn-final-upload', 'finalAck', 'uploaderAck', 'final-submit-group']) {
    ids[id] = mk(id.startsWith('btn') ? 'button' : 'input', id)
  }
  ids['btn-recognize'].textContent = '辨識內容'

  const calls = []
  const alerts = []
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

const lastBody = (page, url) => JSON.parse([...page.calls].reverse().find((c) => c.url === url).opts.body)

test('品名明細區有既有的「新增明細」按鈕，且只有一個', async () => {
  const page = await setup()
  assert.ok(page.addButton())
  assert.equal(page.fields.querySelectorAll('button').filter((b) => b.textContent === '新增明細').length, 1)
})

test('點擊後新增一筆可輸入的空白明細，AI 明細保留', async () => {
  const page = await setup()
  assert.equal(page.rows().length, 2)
  page.addButton().click()
  const rows = page.rows()
  assert.equal(rows.length, 3)
  for (const name of ['item_name', 'quantity', 'unit_price', 'line_amount']) {
    assert.equal(page.input(rows[2], name).value, '')
  }
  assert.equal(page.input(rows[0], 'item_name').value, '原子筆')
  assert.equal(page.input(rows[1], 'item_name').value, '筆記本')
  assert.match(rows[2].querySelector('.item-row__status').textContent, /新增/)
})

test('連續新增多筆，原有輸入（含尚未離開欄位的修改）不遺失', async () => {
  const page = await setup()
  page.addButton().click()
  page.type(page.rows()[2], 'item_name', '膠帶')
  // 只輸入、尚未觸發 change，模擬「未離開欄位就按新增」
  page.input(page.rows()[0], 'item_name').value = '鋼筆'
  page.addButton().click()
  page.addButton().click()
  const rows = page.rows()
  assert.equal(rows.length, 5)
  assert.equal(page.input(rows[0], 'item_name').value, '鋼筆')
  assert.equal(page.input(rows[2], 'item_name').value, '膠帶')
  assert.equal(page.input(rows[3], 'item_name').value, '')
  page.type(rows[3], 'item_name', '剪刀')
  assert.equal(page.input(page.rows()[4], 'item_name').value, '', '各列獨立，不互相影響')
})

test('達到 50 筆上限後不再新增並提示', async () => {
  const page = await setup()
  for (let i = 0; i < 48; i++) page.addButton().click()
  assert.equal(page.rows().length, 50)
  assert.deepEqual(page.alerts, [])
  page.addButton().click()
  assert.equal(page.rows().length, 50)
  assert.deepEqual(page.alerts, ['明細最多 50 筆'])
})

test('新增明細進入送出 payload，source_line_no 為 null，AI 明細的來源序號不變', async () => {
  const page = await setup()
  page.addButton().click()
  const row = page.rows()[2]
  page.type(row, 'item_name', '膠帶')
  page.type(row, 'quantity', '1')
  page.type(row, 'unit_price', '10')
  page.type(row, 'line_amount', '10')
  assert.equal(await page.submit(), 1)
  // 必填檢核請求與正式送出資料都含新增列
  const check = lastBody(page, '/invoices/check-required')
  assert.equal(check.items[2].source_line_no, null)
  page.ids['btn-check-duplicate'].click()
  await new Promise((r) => setTimeout(r, 0))
  page.ids['finalAck'].checked = true
  page.ids['btn-final-upload'].click()
  await new Promise((r) => setTimeout(r, 0))
  const sent = lastBody(page, '/invoices/mobile-upload')
  assert.equal(sent.items.length, 3)
  assert.deepEqual(sent.items.map((i) => i.source_line_no), [1, 2, null])
  assert.deepEqual(sent.items[2], { source_line_no: null, item_name: '膠帶', quantity: '1', unit_price: '10', line_amount: '10' })
  assert.deepEqual(sent.items[0], { source_line_no: 1, item_name: '原子筆', quantity: '2', unit_price: '50', line_amount: '100' })
  // 修改紀錄只含新增列自己的欄位（AI 明細未改動，沒有紀錄）
  const itemChanges = sent.changes.filter((c) => c.field_scope === 'item')
  assert.ok(itemChanges.length > 0)
  assert.ok(itemChanges.every((c) => c.line_no === 3))
})

test('新增明細的數量／單價／金額沿用既有驗證：無效值被攔截且不送出', async () => {
  const page = await setup()
  page.addButton().click()
  const row = page.rows()[2]
  page.type(row, 'item_name', '膠帶')
  page.type(row, 'line_amount', 'abc')
  await page.submit()
  assert.deepEqual(page.alerts, ['請確認明細 3 的金額'])
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-duplicate').length, 0)

  page.alerts.length = 0
  page.type(page.rows()[2], 'line_amount', '10')
  page.type(page.rows()[2], 'quantity', '1x')
  await page.submit()
  assert.deepEqual(page.alerts, ['請確認明細 3 的數量與單價（數字，最多 4 位小數）'])
})

test('新增列缺品名被攔截；整列空白的新增列不送出', async () => {
  const page = await setup()
  page.addButton().click()
  page.type(page.rows()[2], 'line_amount', '10')
  await page.submit()
  assert.deepEqual(page.alerts, ['請填寫明細 3 的品名'])

  // 整列空白：不進 payload
  const page2 = await setup()
  page2.addButton().click()
  await page2.submit()
  assert.equal(lastBody(page2, '/invoices/check-required').items.length, 2)
})
