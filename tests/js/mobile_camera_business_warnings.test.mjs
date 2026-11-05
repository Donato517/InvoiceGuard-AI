// 測試目標：app/static/js/mobile-camera.js 核對頁的業務警示（發票日期晚於今天、金額不一致）——按「上傳者確認」取得警示、
//   顯示位置、修改後清除、預覽失敗、與 AI 辨識警示共存、重複點擊與過期結果，全部只提醒、不阻擋提交。
// 注意：專案沒有 jsdom，這裡用最小的「假 DOM」（含簡化的選擇器）在 node:vm 內執行原始碼，fetch 以替身取代；
//   驗證的是程式流程與送出資料，不是真實瀏覽器的版面、點擊與捲動，也不連 API／資料庫。真實瀏覽器須另行驗收。
//   假 DOM 與 mobile_camera_add_item_c.test.mjs 各自獨立（不互相 import）；兩者的類別須保持相同行為。
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

async function setup(extraGlobals = {}, recognition = null) {
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
  const stepConfirm = mk('section', 'step-confirm', 'mobile-step-section')
  mk('section', 'step-success', 'mobile-step-section')
  const fields = ID(new FakeEl('div'), 'fields-container'); stepFields.append(fields)
  const ids = {}
  for (const id of ['file-album-upload', 'btn-recognize', 'btn-confirm-fields', 'btn-check-duplicate', 'btn-final-upload', 'finalAck', 'uploaderAck', 'final-submit-group']) {
    ids[id] = mk(id.startsWith('btn') ? 'button' : 'input', id)
  }
  ids['btn-recognize'].textContent = '辨識內容'
  // 業務警示的顯示區（正式樣板在步驟 4）
  const box = ID(new FakeEl('div'), 'business-warnings'); box.hidden = true; stepConfirm.append(box)
  const boxTitle = ID(new FakeEl('p'), 'business-warnings-title'); box.append(boxTitle)
  const boxList = ID(new FakeEl('ul'), 'business-warnings-list'); boxList.hidden = true; box.append(boxList)

  const calls = []
  const alerts = []
  const json = (data, ok = true) => ({ ok, redirected: false, url: '', json: async () => data })
  const routes = {
    '/invoices/mobile-recognize': () => json(recognition ? recognition() : aiInvoice()),
    '/invoices/check-required': () => json({ required_complete: true, missing: [] }),
    '/invoices/check-warnings': () => json({ warnings: [], checked_on: '2026-10-30' }),
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
    console,
    ...extraGlobals
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
    calls, alerts, fields, ids, routes, json, stepConfirm, box, boxTitle, boxList,
    async submit() {
      ids['uploaderAck'].checked = true
      ids['btn-confirm-fields'].click()
      await new Promise((r) => setTimeout(r, 0))
      return calls.filter((c) => c.url === '/invoices/check-required').length
    }
  }
  return page
}

// ======== 業務警示（發票日期晚於今天、金額不一致）：只提醒，不阻擋 ========
const warnCalls = (page) => page.calls.filter((c) => c.url === '/invoices/check-warnings')
const totalMismatch = { field: 'total_amount', code: 'total_amount_mismatch', message: '銷售額＋稅額與總計不符，請確認' }
const futureDate = { field: 'invoice_date', code: 'invoice_date_future', message: '發票日期晚於今天，請核對原始發票。' }
const setHeader = (page, field, value) => {
  const el = page.fields.querySelector(`#f-${field}`)
  el.value = value
  el.fire('input')
  el.fire('change')
}
const businessNotes = (page) => page.fields.querySelectorAll('.field-business-warning')

test('業務警示：總計 9999 時按「上傳者確認」取得警示，顯示在總計欄位旁與確認頁，且仍可繼續', async () => {
  const page = await setup()
  setHeader(page, 'sales_amount', '6000')
  setHeader(page, 'tax_amount', '300')
  setHeader(page, 'total_amount', '9999')
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [totalMismatch], checked_on: '2026-10-30' })
  await page.submit()
  assert.equal(warnCalls(page).length, 1)
  const sent = JSON.parse(warnCalls(page)[0].opts.body)
  assert.deepEqual([sent.sales_amount, sent.tax_amount, sent.total_amount], ['6000', '300', '9999'])
  const notes = businessNotes(page)
  assert.equal(notes.length, 1)
  assert.match(notes[0].textContent, /總計與銷售額及營業稅額不一致，請核對。/)
  assert.match(notes[0].textContent, /銷售額 6,000 ＋ 營業稅額 300 ＝ 6,300；輸入總計 9,999，差額 3,699 元。/)
  assert.ok(page.fields.querySelector('#f-total_amount').closest('.field-group').querySelectorAll('.field-business-warning').length === 1)
  // 進入確認頁，警示摘要顯示且說明不阻擋；查重與送出仍可進行
  assert.equal(page.stepConfirm.hidden, false)
  assert.equal(page.box.hidden, false)
  assert.match(page.boxTitle.textContent, /不代表已被拒絕提交/)
  assert.equal(page.boxList.children.length, 1)
  assert.deepEqual(page.alerts, [])
  page.ids['btn-check-duplicate'].click()
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-duplicate').length, 1)
})

test('業務警示：未來日期警示掛在日期欄位旁，與金額警示可同時存在', async () => {
  const page = await setup()
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [futureDate, totalMismatch], checked_on: '2026-10-30' })
  setHeader(page, 'invoice_date', '2099-01-01')
  await page.submit()
  const dateGroup = page.fields.querySelector('#f-invoice_date').closest('.field-group')
  assert.equal(dateGroup.querySelectorAll('.field-business-warning').length, 1)
  assert.equal(dateGroup.querySelector('.field-business-warning').textContent, '發票日期晚於今天，請核對原始發票。')
  assert.equal(businessNotes(page).length, 2)
  assert.equal(page.boxList.children.length, 2)
})

test('業務警示：修改金額後舊警示立即清除，再次確認重新取得，修正後不再顯示', async () => {
  const page = await setup()
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [totalMismatch], checked_on: '2026-10-30' })
  await page.submit()
  assert.equal(businessNotes(page).length, 1)
  setHeader(page, 'total_amount', '315') // 修改欄位：舊警示不可繼續冒充最新結果
  assert.equal(businessNotes(page).length, 0)
  assert.equal(page.box.hidden, true)
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [], checked_on: '2026-10-30' })
  await page.submit()
  assert.equal(warnCalls(page).length, 2)
  assert.equal(businessNotes(page).length, 0)
  assert.equal(page.box.hidden, true)
})

test('業務警示：必填缺漏或格式錯誤時不取警示（先由既有檢核擋下）', async () => {
  const page = await setup()
  page.routes['/invoices/check-required'] = () => page.json({ required_complete: false, missing: [{ field: 'tax_type', code: 'required_missing', message: '請選擇課稅別', line_no: null }] })
  await page.submit()
  assert.equal(warnCalls(page).length, 0)
  page.routes['/invoices/check-required'] = () => page.json({ required_complete: true, missing: [] })
  setHeader(page, 'total_amount', 'abc')
  await page.submit()
  assert.equal(warnCalls(page).length, 0)
  assert.ok(page.alerts.length > 0)
})

test('業務警示：預覽失敗時明確告知無法更新，不顯示舊警示、不說通過，也不阻擋流程', async () => {
  for (const failing of [
    () => { throw new Error('network down') },
    () => page.json({ error: { code: 'INTERNAL_ERROR' } }, false),
    () => page.json({ warnings: 'bad' }),
    () => page.json({})
  ]) {
    var page = await setup()
    page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [totalMismatch], checked_on: '2026-10-30' })
    await page.submit()
    assert.equal(businessNotes(page).length, 1)
    setHeader(page, 'total_amount', '316') // 令舊警示失效
    page.routes['/invoices/check-warnings'] = failing
    await page.submit()
    assert.equal(businessNotes(page).length, 0, '舊警示不可冒充最新結果')
    assert.equal(page.box.hidden, false)
    assert.match(page.boxTitle.textContent, /目前無法更新業務警示/)
    assert.equal(page.boxList.children.length, 0)
    assert.equal(page.stepConfirm.hidden, false, '警示預覽失敗不阻擋既有流程')
  }
})

test('業務警示：與 AI 辨識警示、必填提示分開顯示，互不覆蓋', async () => {
  const page = await setup()
  const original = page.routes['/invoices/mobile-recognize']
  // 本測試的 setup 已辨識完成；直接在畫面上加入 AI 警示元素模擬共存
  const group = page.fields.querySelector('#f-total_amount').closest('.field-group')
  const ai = new FakeEl('small'); ai.attrs.class = 'field-warning'; ai.append('AI 辨識提醒'); group.append(ai)
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [totalMismatch], checked_on: '2026-10-30' })
  await page.submit()
  assert.equal(group.querySelectorAll('.field-warning').length, 1)
  assert.equal(group.querySelectorAll('.field-business-warning').length, 1)
  assert.ok(original)
})

test('業務警示：取警示期間欄位又被修改，不採用過期結果，也不進入確認頁', async () => {
  const page = await setup()
  let release
  const gate = new Promise((resolve) => { release = resolve })
  page.routes['/invoices/check-warnings'] = async () => { await gate; return page.json({ warnings: [totalMismatch], checked_on: '2026-10-30' }) }
  page.ids['uploaderAck'].checked = true
  page.ids['btn-confirm-fields'].click()
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(warnCalls(page).length, 1)
  setHeader(page, 'total_amount', '1') // 請求進行中修改欄位
  release()
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(businessNotes(page).length, 0)
  assert.equal(page.stepConfirm.hidden, true)
  assert.deepEqual(page.alerts, ['檢查期間欄位又被修改，請再按一次「上傳者確認」。'])
})

test('業務警示：取警示期間重複點擊不會多送請求', async () => {
  const page = await setup()
  let release
  const gate = new Promise((resolve) => { release = resolve })
  page.routes['/invoices/check-warnings'] = async () => { await gate; return page.json({ warnings: [], checked_on: '2026-10-30' }) }
  page.ids['uploaderAck'].checked = true
  page.ids['btn-confirm-fields'].click()
  await new Promise((r) => setTimeout(r, 0))
  page.ids['btn-confirm-fields'].click()
  page.ids['btn-confirm-fields'].click()
  release()
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(page.calls.filter((c) => c.url === '/invoices/check-required').length, 1)
  assert.equal(warnCalls(page).length, 1)
})

test('業務警示：切換到確認頁時瀏覽器補送的 change（值沒有改變）不會清掉剛顯示的警示', async () => {
  const page = await setup()
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [totalMismatch], checked_on: '2026-10-30' })
  const total = page.fields.querySelector('#f-total_amount')
  total.value = '9999'
  total.fire('input') // 使用者輸入
  await page.submit()
  assert.equal(businessNotes(page).length, 1)
  total.fire('change') // 輸入框被隱藏時瀏覽器補送，值沒有變
  assert.equal(businessNotes(page).length, 1)
  assert.equal(page.box.hidden, false)
  total.value = '6300' // 真的修改過（即使只有 change 沒有 input，例如自動填入）
  total.fire('change')
  assert.equal(businessNotes(page).length, 0)
  assert.equal(page.box.hidden, true)
})

// ======== 國字大寫警示（API 規則：total_amount_zh_unreadable／total_amount_zh_mismatch）========
const zhUnreadable = { field: 'total_amount_zh', code: 'total_amount_zh_unreadable', message: '國字大寫金額格式無法辨識，請對照票面人工確認' }
const zhMismatch = { field: 'total_amount_zh', code: 'total_amount_zh_mismatch', message: '國字大寫金額與總計不符，請確認' }
const zhGroup = (page) => page.fields.querySelector('#f-total_amount_zh').closest('.field-group')

test('國字大寫警示：金額與國字一致時 API 無警示，畫面不出現國字提醒', async () => {
  const page = await setup()
  setHeader(page, 'total_amount', '14858')
  setHeader(page, 'total_amount_zh', '壹萬肆仟捌佰伍拾捌元整')
  await page.submit()
  const sent = JSON.parse(warnCalls(page)[0].opts.body)
  assert.equal(sent.total_amount_zh, '壹萬肆仟捌佰伍拾捌元整')
  assert.equal(businessNotes(page).length, 0)
  assert.equal(zhGroup(page).querySelectorAll('.field-business-warning').length, 0)
})

test('國字大寫警示：格式無法辨識時顯示在國字欄位旁與確認頁，原值不被改寫，仍可繼續', async () => {
  const page = await setup()
  setHeader(page, 'total_amount', '14858')
  setHeader(page, 'total_amount_zh', '億仟佰拾壹萬肆仟捌佰伍拾捌元')
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [zhUnreadable], checked_on: '2026-11-05' })
  await page.submit()
  const notes = zhGroup(page).querySelectorAll('.field-business-warning')
  assert.equal(notes.length, 1)
  assert.equal(notes[0].textContent, zhUnreadable.message)
  assert.equal(page.fields.querySelector('#f-total_amount_zh').value, '億仟佰拾壹萬肆仟捌佰伍拾捌元')
  assert.equal(page.box.hidden, false)
  assert.equal(page.boxList.children.length, 1)
  assert.deepEqual(page.alerts, [])
})

test('國字大寫警示：金額不符時顯示 API 訊息，且與總計警示互不覆蓋', async () => {
  const page = await setup()
  setHeader(page, 'total_amount_zh', '壹萬肆仟捌佰伍拾玖元整')
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [totalMismatch, zhMismatch], checked_on: '2026-11-05' })
  await page.submit()
  assert.equal(businessNotes(page).length, 2)
  assert.equal(zhGroup(page).querySelector('.field-business-warning').textContent, zhMismatch.message)
  assert.equal(page.fields.querySelector('#f-total_amount').closest('.field-group').querySelectorAll('.field-business-warning').length, 1)
  assert.equal(page.boxList.children.length, 2)
})

test('國字大寫警示：人工修改國字後舊警示立即清除，再次確認重新取得', async () => {
  const page = await setup()
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [zhUnreadable], checked_on: '2026-11-05' })
  await page.submit()
  assert.equal(businessNotes(page).length, 1)
  setHeader(page, 'total_amount_zh', '壹萬肆仟捌佰伍拾捌元整')
  assert.equal(businessNotes(page).length, 0)
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [], checked_on: '2026-11-05' })
  await page.submit()
  assert.equal(businessNotes(page).length, 0)
  assert.equal(page.box.hidden, true)
})

test('國字大寫警示：修改國字欄位會排程即時預覽並顯示警示', async () => {
  const page = await setup({ setTimeout, clearTimeout })
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [zhMismatch], checked_on: '2026-11-05' })
  setHeader(page, 'total_amount_zh', '壹萬肆仟捌佰伍拾玖元整')
  await new Promise((r) => setTimeout(r, 800)) // 即時預覽延遲 500ms
  assert.equal(warnCalls(page).length, 1)
  assert.equal(JSON.parse(warnCalls(page)[0].opts.body).total_amount_zh, '壹萬肆仟捌佰伍拾玖元整')
  assert.equal(zhGroup(page).querySelectorAll('.field-business-warning').length, 1)
})

test('國字大寫警示：未知代碼仍被濾掉，新代碼在白名單內', async () => {
  const Rules = (await import('node:module')).createRequire(import.meta.url)('../../app/static/js/invoice-field-rules.js')
  const parsed = Rules.parseWarningResult({
    ok: true,
    data: { warnings: [zhUnreadable, zhMismatch, { field: 'total_amount_zh', code: 'something_else', message: 'x' }] }
  })
  assert.deepEqual(parsed.warnings.map((w) => w.code), ['total_amount_zh_unreadable', 'total_amount_zh_mismatch'])
  assert.equal(Rules.warningKey(zhMismatch), 'h:total_amount_zh')
  assert.equal(Rules.warningText(zhMismatch, {}), zhMismatch.message)
})

// ======== 國字大寫自動建議值（無法判讀或空白時，依數字總計帶入標準國字）========
const TOLERANT_ZH = '億仟佰拾壹萬肆仟捌佰伍拾捌元' // 預印單位殘留，但 API 容錯解析為 14858
const STANDARD_ZH = '壹萬肆仟捌佰伍拾捌元整'
const recWith = (invoice, warnings = []) => () => {
  const base = aiInvoice()
  return { ...base, warnings, invoice: { ...base.invoice, sales_amount: '14150', tax_amount: '708', total_amount: '14858', ...invoice } }
}
const zhInput = (page) => page.fields.querySelector('#f-total_amount_zh')
const suggestionNotes = (page) => page.fields.querySelectorAll('.field-suggestion')
const zhUnreadableWarning = { field: 'total_amount_zh', code: 'total_amount_zh_unreadable', message: '無法判讀國字大寫金額，請對照票面確認' }
const zhMismatchWarning = { field: 'total_amount_zh', code: 'total_amount_zh_mismatch', message: '國字大寫金額（14,859）與總計不符，請確認' }
const upload = async (page) => {
  await page.submit()
  page.ids['btn-check-duplicate'].click()
  await new Promise((r) => setTimeout(r, 0))
  page.ids['finalAck'].checked = true
  page.ids['btn-final-upload'].click()
  await new Promise((r) => setTimeout(r, 0))
  return JSON.parse([...page.calls].reverse().find((c) => c.url === '/invoices/mobile-upload').opts.body)
}
const zhChanges = (sent) => sent.changes.filter((c) => c.field_name === 'total_amount_zh')

test('國字建議：預印單位殘留但容錯解析一致（API 無警示）→ 改成標準國字、提醒保留原字串、記為修改', async () => {
  const page = await setup({}, recWith({ total_amount_zh: TOLERANT_ZH }))
  assert.equal(zhInput(page).value, STANDARD_ZH)
  const notes = suggestionNotes(page)
  assert.equal(notes.length, 1)
  assert.match(notes[0].textContent, new RegExp(TOLERANT_ZH)) // 原始 OCR 字串保留在提醒
  assert.match(notes[0].textContent, /寫法不標準/)
  assert.match(zhInput(page).closest('.field-group').querySelector('.field-modified').textContent, /AI 辨識：億仟佰拾壹萬/)
  const sent = await upload(page)
  assert.equal(sent.total_amount_zh, STANDARD_ZH)
  assert.equal(zhChanges(sent).length, 1) // AI 原值由 changes 與 API 的辨識紀錄保存
})

test('國字建議：標準國字（只差結尾「整」）不改值、不提示', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '壹萬肆仟捌佰伍拾捌元' }))
  assert.equal(zhInput(page).value, '壹萬肆仟捌佰伍拾捌元')
  assert.equal(suggestionNotes(page).length, 0)
})

test('國字建議：API 回報無法判讀、總計 14858 → 自動填入標準國字並顯示含原值的核對提醒', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '約壹萬四' }, [zhUnreadableWarning]))
  assert.equal(zhInput(page).value, STANDARD_ZH)
  const notes = suggestionNotes(page)
  assert.equal(notes.length, 1)
  assert.match(notes[0].textContent, /約壹萬四/) // 原始 OCR 國字
  assert.match(notes[0].textContent, new RegExp(STANDARD_ZH)) // 建議值
  assert.match(notes[0].textContent, /核對/)
  assert.equal(notes[0].hidden, false)
  // 欄位旁仍顯示「已修改｜AI 辨識：原值」
  assert.match(zhInput(page).closest('.field-group').querySelector('.field-modified').textContent, /AI 辨識：約壹萬四/)
})

test('國字建議：AI 國字空白、總計 14858 → 自動填入並提醒（沒有 AI 原值可顯示）', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '' }))
  assert.equal(zhInput(page).value, STANDARD_ZH)
  const notes = suggestionNotes(page)
  assert.equal(notes.length, 1)
  assert.match(notes[0].textContent, /沒有辨識到/)
  assert.match(notes[0].textContent, new RegExp(STANDARD_ZH))
})

test('國字建議：自動填入使用既有修改紀錄（AI 原值→建議值），送出時保留 AI 原值作為 old_value', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '約壹萬四' }, [zhUnreadableWarning]))
  const sent = await upload(page)
  assert.equal(sent.total_amount_zh, STANDARD_ZH)
  const changes = zhChanges(sent)
  assert.equal(changes.length, 1)
  assert.equal(changes[0].old_value, '約壹萬四')
  assert.equal(changes[0].new_value, STANDARD_ZH)
})

test('國字建議：空白時的修改紀錄 old_value 為空', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '' }))
  const changes = zhChanges(await upload(page))
  assert.equal(changes.length, 1)
  assert.equal(changes[0].old_value, null)
})

test('國字建議：國字可解析但與總計不符 → 只提示，不自動覆寫', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '壹萬肆仟捌佰伍拾玖元整' }, [zhMismatchWarning]))
  assert.equal(zhInput(page).value, '壹萬肆仟捌佰伍拾玖元整')
  assert.equal(suggestionNotes(page).length, 0)
  const warn = zhInput(page).closest('.field-group').querySelectorAll('.field-warning')
  assert.equal(warn.length, 1)
  assert.equal(warn[0].textContent, zhMismatchWarning.message)
  assert.deepEqual(zhChanges(await upload(page)), [])
})

test('國字建議：總計空白、非法或非整數 → 不產生建議國字', async () => {
  for (const total of ['', 'abc', '14858.5', '-5']) {
    const page = await setup({}, recWith({ total_amount: total, total_amount_zh: '' }))
    assert.equal(zhInput(page).value, '', JSON.stringify(total))
    assert.equal(suggestionNotes(page).length, 0, JSON.stringify(total))
    const unreadable = await setup({}, recWith({ total_amount: total, total_amount_zh: '約壹萬' }, [zhUnreadableWarning]))
    assert.equal(zhInput(unreadable).value, '約壹萬', JSON.stringify(total))
    assert.equal(suggestionNotes(unreadable).length, 0, JSON.stringify(total))
  }
})

test('國字建議：原值含 HTML 字元只當純文字顯示，不被當成標籤', async () => {
  const evil = '<img src=x onerror=alert(1)>'
  const page = await setup({}, recWith({ total_amount_zh: evil }, [zhUnreadableWarning]))
  const note = suggestionNotes(page)[0]
  assert.ok(note.textContent.includes(evil))
  assert.ok(note.children.every((child) => child.nodeType === 3)) // 只有文字節點：沒有被解析成 HTML 元素
})

test('國字建議：使用者手動改國字後提醒消失、不再被自動覆寫；清空後恢復自動', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '約壹萬四' }, [zhUnreadableWarning]))
  setHeader(page, 'total_amount_zh', '壹萬肆仟捌佰伍拾捌圓整') // 人工
  assert.equal(suggestionNotes(page)[0].hidden, true)
  setHeader(page, 'total_amount', '20000')
  assert.equal(zhInput(page).value, '壹萬肆仟捌佰伍拾捌圓整')
  setHeader(page, 'total_amount_zh', '')
  setHeader(page, 'total_amount', '30000')
  assert.equal(zhInput(page).value, '參萬元整')
})

test('國字建議：按確認（取得業務警示）與重新預覽後，核對提醒不消失也不重複填值', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '約壹萬四' }, [zhUnreadableWarning]))
  page.routes['/invoices/check-warnings'] = () => page.json({ warnings: [totalMismatch], checked_on: '2026-11-05' })
  await page.submit()
  assert.equal(suggestionNotes(page).length, 1)
  assert.equal(suggestionNotes(page)[0].hidden, false)
  assert.equal(zhInput(page).value, STANDARD_ZH)
  setHeader(page, 'sales_amount', '14150') // 觸發舊警示清除
  assert.equal(suggestionNotes(page)[0].hidden, false)
  const sent = await upload(page)
  assert.equal(zhChanges(sent).length, 1) // 修改紀錄沒有因重複流程而重複
})

test('國字建議：總計改動使國字被自動重算後，舊的建議提醒隱藏', async () => {
  const page = await setup({}, recWith({ total_amount_zh: '' }))
  assert.equal(suggestionNotes(page)[0].hidden, false)
  setHeader(page, 'total_amount', '20000') // 國字自動改成 貳萬元整，已不是當初的建議值
  assert.equal(zhInput(page).value, '貳萬元整')
  assert.equal(suggestionNotes(page)[0].hidden, true)
})

test('國字建議：重新辨識另一張時依新結果重新判斷，不沿用上一張的建議', async () => {
  const first = await setup({}, recWith({ total_amount_zh: '' }))
  assert.equal(suggestionNotes(first).length, 1)
  const second = await setup({}, recWith({ total_amount_zh: '壹萬肆仟捌佰伍拾捌元整' }))
  assert.equal(suggestionNotes(second).length, 0)
})
