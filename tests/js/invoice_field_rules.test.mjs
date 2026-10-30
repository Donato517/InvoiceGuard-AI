// 測試目標：app/static/js/invoice-field-rules.js——送出前的資料整理、欄位格式提示、必填缺漏對應與「上傳者確認」流程。
// 注意：這裡驗證的是純函式與流程順序（以替身注入 DOM／API 行為），不是真實瀏覽器的版面、捲動與互動；
//   真實畫面須另行手動驗收。不連網路、不呼叫任何 API。
// 執行：node --test tests/js/
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(import.meta.url)
const Rules = require('../../app/static/js/invoice-field-rules.js')

// ---- 原本寫在 buildPayload()／cleanNumber() 的整理運算式（抽成 helper 前的逐字複本）----
const originalTrack = (value) => value.toUpperCase().replace(/[\s-]/g, '')
const originalNumber = (value) => value.replace(/[\s-]/g, '')
const originalCleanNumber = (value) => String(value || '').replace(/[\s,，]/g, '')

const CORPUS = [
  '', ' ', 'ab', 'AB', 'Ab', ' a b ', 'a-b', 'A--B', 'Ａ-Ｂ', 'ß', '１２３４', '1,200', '1，200',
  ' 1 200.50 ', '　A　', '﻿AB', ' 7567-0992 ', '1-2', '-5', '12.50', '1,2,3',
  '\t7\n5', 'ＡＢ１２', '0', '00012', '１，２００．５０'
]

test('字軌／號碼／金額整理與抽出 helper 前的運算式結果完全一致', () => {
  for (const value of CORPUS) {
    assert.equal(Rules.normalizeTrack(value), originalTrack(value), JSON.stringify(value))
    assert.equal(Rules.normalizeNumber(value), originalNumber(value), JSON.stringify(value))
    assert.equal(Rules.cleanNumber(value), originalCleanNumber(value), JSON.stringify(value))
  }
  for (const value of [null, undefined, 0, '']) {
    assert.equal(Rules.cleanNumber(value), originalCleanNumber(value))
  }
})

test('格式常數與原本 mobile-camera.js 的定義相同', () => {
  assert.equal(Rules.AMOUNT_RE.source, /^\d{1,16}(\.\d{1,2})?$/.source)
  assert.equal(Rules.QUANTITY_RE.source, /^\d{1,14}(\.\d{1,4})?$/.source)
})

test('必填欄位清單：表頭 8 欄、明細 2 欄；選填欄位不在其中', () => {
  assert.deepEqual(Rules.REQUIRED_HEADER_FIELDS, [
    'invoice_track', 'invoice_number', 'invoice_date', 'seller_tax_id',
    'tax_type', 'sales_amount', 'tax_amount', 'total_amount'
  ])
  assert.deepEqual(Rules.REQUIRED_ITEM_FIELDS, ['item_name', 'line_amount'])
  for (const optional of ['seller_name', 'buyer_tax_id', 'buyer_name', 'total_amount_zh', 'quantity', 'unit_price']) {
    assert.ok(!Rules.REQUIRED_HEADER_FIELDS.includes(optional))
    assert.ok(!Rules.REQUIRED_ITEM_FIELDS.includes(optional))
  }
})

// ---- 格式提示 ----
const check = (field, raw) => Rules.evaluateField(field, raw)

test('尚未填寫（含只有空白）保持中性，不顯示紅叉', () => {
  for (const field of ['invoice_track', 'invoice_number', 'invoice_date', 'seller_tax_id', 'buyer_tax_id',
    'sales_amount', 'tax_amount', 'total_amount', 'line_amount', 'quantity', 'unit_price']) {
    for (const raw of ['', '   ', '　', null, undefined]) {
      assert.equal(check(field, raw).state, 'empty', `${field} ${JSON.stringify(raw)}`)
    }
  }
})

test('沒有明確格式規則的欄位不顯示綠勾', () => {
  for (const field of ['seller_name', 'buyer_name', 'total_amount_zh', 'tax_type', 'item_name', 'unknown']) {
    assert.equal(check(field, '範例').state, 'none', field)
    assert.equal(check(field, '').state, 'none', field)
  }
})

test('字軌：2 碼大寫英文為格式正確；小寫、空白、連字號為格式相容；其他為錯誤', () => {
  assert.deepEqual(check('invoice_track', 'AB'), { state: 'ok', message: '格式正確' })
  for (const raw of ['ab', ' a-b ', 'A B', 'a　b']) {
    assert.deepEqual(check('invoice_track', raw), { state: 'compatible', message: '格式相容，可送出' }, raw)
  }
  for (const raw of ['A', 'ABC', 'A1', '12']) {
    assert.deepEqual(check('invoice_track', raw), { state: 'error', message: '請使用 2 碼半形大寫英文字母' }, raw)
  }
  const fullWidth = check('invoice_track', 'ＡＢ')
  assert.equal(fullWidth.state, 'error')
  assert.match(fullWidth.message, /半形/)
})

test('號碼：8 碼半形數字；空白與連字號可整理；全形數字與位數不足為錯誤', () => {
  assert.equal(check('invoice_number', '75670992').state, 'ok')
  assert.equal(check('invoice_number', '7567-0992').state, 'compatible')
  assert.equal(check('invoice_number', ' 75670992 ').state, 'compatible')
  assert.deepEqual(check('invoice_number', '7567099'), { state: 'error', message: '請輸入 8 碼半形數字' })
  assert.equal(check('invoice_number', '756709921').state, 'error')
  const fullWidth = check('invoice_number', '７５６７０９９２')
  assert.equal(fullWidth.state, 'error')
  assert.match(fullWidth.message, /半形/)
})

test('統編：既有整理只去空白與逗號，連字號不可接受；買受人統編選填', () => {
  assert.equal(check('seller_tax_id', '27601907').state, 'ok')
  assert.equal(check('seller_tax_id', '2760 1907').state, 'compatible')
  assert.equal(check('seller_tax_id', '2760,1907').state, 'compatible')
  assert.equal(check('seller_tax_id', '2760-1907').state, 'error')
  assert.equal(check('seller_tax_id', '2760190').state, 'error')
  assert.equal(check('buyer_tax_id', '04595257').state, 'ok')
  assert.equal(check('buyer_tax_id', '').state, 'empty')
  assert.equal(check('buyer_tax_id', '0459525').state, 'error')
})

test('統編的格式正確不代表檢查碼通過（檢查碼不屬於格式提示）', () => {
  assert.equal(check('seller_tax_id', '12345678').state, 'ok')
})

test('金額：半形數字最多 2 位小數；逗號與空白可整理；全形、負數、過多小數為錯誤', () => {
  for (const field of ['sales_amount', 'tax_amount', 'total_amount', 'line_amount']) {
    assert.equal(check(field, '1200').state, 'ok')
    assert.equal(check(field, '0').state, 'ok')
    assert.equal(check(field, '1200.5').state, 'ok')
    assert.equal(check(field, '1,200').state, 'compatible')
    assert.equal(check(field, '1，200').state, 'compatible')
    assert.equal(check(field, ' 1 200.50 ').state, 'compatible')
    assert.deepEqual(check(field, '1200.123'), { state: 'error', message: '金額格式不正確，最多 2 位小數' })
    assert.equal(check(field, '-5').state, 'error')
    assert.equal(check(field, '1200.').state, 'error')
    assert.equal(check(field, 'abc').state, 'error')
    assert.equal(check(field, '$1200').state, 'error')
    assert.deepEqual(check(field, '１２００'), { state: 'error', message: '請使用半形數字' })
    assert.deepEqual(check(field, '1'.repeat(17)), { state: 'error', message: '金額整數最多 16 位' })
    assert.equal(check(field, '1'.repeat(16)).state, 'ok')
  }
})

test('數量與單價：最多 4 位小數，選填', () => {
  for (const field of ['quantity', 'unit_price']) {
    assert.equal(check(field, '2').state, 'ok')
    assert.equal(check(field, '2.1234').state, 'ok')
    assert.equal(check(field, '1,000').state, 'compatible')
    assert.equal(check(field, '').state, 'empty')
    assert.equal(check(field, '2.12345').state, 'error')
  }
  assert.match(check('quantity', '2.12345').message, /^數量格式不正確，最多 4 位小數$/)
  assert.match(check('unit_price', '2.12345').message, /^單價格式不正確，最多 4 位小數$/)
})

test('日期：YYYY-MM-DD 且為實際存在的日期', () => {
  assert.equal(check('invoice_date', '2026-08-15').state, 'ok')
  assert.equal(check('invoice_date', '2024-02-29').state, 'ok')
  for (const raw of ['2026-02-30', '2026/08/15', '2026-8-15', '115-08-15', '2026-13-01']) {
    assert.equal(check('invoice_date', raw).state, 'error', raw)
  }
})

test('格式相容只在既有整理後確實符合時才出現，且不修改輸入', () => {
  const raw = ' 1,200 '
  const result = check('sales_amount', raw)
  assert.equal(result.state, 'compatible')
  assert.equal(raw, ' 1,200 ')
  assert.equal(check('sales_amount', '1,2a0').state, 'error')
})

// ---- 必填缺漏對應畫面 ----
const LABELS = {
  invoice_track: '字軌', invoice_number: '號碼', invoice_date: '發票日期', seller_tax_id: '賣方統一編號',
  tax_type: '課稅別', sales_amount: '銷售額合計', tax_amount: '營業稅額', total_amount: '總計',
  item_name: '品名', quantity: '數量', unit_price: '單價', line_amount: '金額'
}
const miss = (field, lineNo = null) => ({ field, code: 'required_missing', message: 'x', line_no: lineNo })

test('planMissing：表頭、明細整體、明細列依列號對應 row_id', () => {
  const rowIds = [11, 15, 17]
  const plan = Rules.planMissing(
    [miss('invoice_number'), miss('items'), miss('item_name', 2), miss('line_amount', 3)],
    rowIds, LABELS
  )
  assert.equal(plan.total, 4)
  assert.deepEqual(plan.unmapped, [])
  assert.deepEqual(plan.targets.map((t) => [t.key, t.text, t.summary]), [
    ['h:invoice_number', '請補填號碼', '號碼'],
    ['items', '請至少填寫一筆品名明細', '品名明細'],
    ['i:15:item_name', '請補填品名', '第 2 筆明細的品名'],
    ['i:17:line_amount', '請補填金額', '第 3 筆明細的金額']
  ])
  assert.equal(plan.targets[2].rowId, 15)
})

test('planMissing：摘要用畫面上的明細編號（空白列不送出時，與 API 列號不同）', () => {
  // 畫面第 1、3 列有內容、第 2 列是空白列：API 的第 2 筆就是畫面的「明細 3」
  const plan = Rules.planMissing([miss('item_name', 2)], [11, 17], LABELS, [1, 3])
  assert.equal(plan.targets[0].key, 'i:17:item_name')
  assert.equal(plan.targets[0].summary, '第 3 筆明細的品名')
  // 沒有提供畫面編號時沿用 API 的列號
  assert.equal(Rules.planMissing([miss('item_name', 2)], [11, 17], LABELS).targets[0].summary, '第 2 筆明細的品名')
})

test('planMissing：對不到畫面欄位的缺漏仍列入摘要，不會被忽略', () => {
  const plan = Rules.planMissing(
    [miss('mystery_field'), miss('item_name', 9), miss('item_name', 0), miss('seller_name'), miss('invoice_date')],
    [1, 2], LABELS
  )
  assert.equal(plan.total, 5)
  assert.deepEqual(plan.targets.map((t) => t.key), ['h:invoice_date'])
  assert.equal(plan.unmapped.length, 4)
  assert.deepEqual(plan.unmapped.map((u) => u.summary), [
    'mystery_field', '第 9 筆明細的品名', '第 0 筆明細的品名', 'seller_name'
  ])
})

test('planMissing：重複的缺漏只標示一次；空清單沒有缺漏', () => {
  const plan = Rules.planMissing([miss('tax_type'), miss('tax_type')], [], LABELS)
  assert.equal(plan.targets.length, 1)
  assert.deepEqual(Rules.planMissing([], [], LABELS), { targets: [], unmapped: [], total: 0 })
  assert.deepEqual(Rules.planMissing(undefined, [], LABELS).total, 0)
})

// ---- 檢核結果判讀 ----
test('parseCheckResult：只有結構正確且前後一致的回應才採信', () => {
  assert.equal(Rules.parseCheckResult({ ok: true, data: { required_complete: true, missing: [] } }).kind, 'complete')
  const missing = Rules.parseCheckResult({ ok: true, data: { required_complete: false, missing: [miss('tax_type')] } })
  assert.equal(missing.kind, 'missing')
  assert.equal(missing.missing.length, 1)
})

test('parseCheckResult：錯誤、格式不符、自相矛盾都不能當成通過', () => {
  const bad = [
    null, undefined, { ok: false, data: null }, { ok: true, data: null }, { ok: true, data: 'x' },
    { ok: true, data: {} }, { ok: true, data: { required_complete: true } },
    { ok: true, data: { required_complete: 'yes', missing: [] } },
    { ok: true, data: { required_complete: true, missing: [miss('tax_type')] } },
    { ok: true, data: { required_complete: false, missing: [] } },
    { ok: true, data: { required_complete: false, missing: [{ code: 'x' }] } },
    { ok: true, data: { required_complete: false, missing: 'tax_type' } },
    { ok: false, data: { required_complete: true, missing: [] } }
  ]
  for (const result of bad) assert.equal(Rules.parseCheckResult(result).kind, 'error', JSON.stringify(result))
})

const FAILURE = '目前無法完成必填欄位檢查，請稍後再試。資料尚未送出。'

test('parseCheckResult：任何失敗都用固定說明（資料尚未送出），不轉述伺服器內容', () => {
  assert.equal(Rules.CHECK_FAILURE_MESSAGE, FAILURE)
  const withServerMessage = Rules.parseCheckResult({ ok: false, data: { error: { code: 'X', message: '內部細節' } } })
  assert.equal(withServerMessage.message, FAILURE)
  assert.equal(Rules.parseCheckResult({ ok: false, data: null }).message, FAILURE)
  assert.equal(Rules.parseCheckResult({ ok: true, data: {} }).message, FAILURE)
})

// ---- 「上傳者確認」流程 ----
function makeCtx(overrides = {}) {
  const log = []
  const state = { busy: false }
  const ctx = {
    log,
    state,
    isBusy: () => state.busy,
    setBusy: (busy) => { state.busy = busy; log.push(`busy:${busy}`) },
    isAcknowledged: () => true,
    notifyAck: () => log.push('notifyAck'),
    collect: () => log.push('collect'),
    buildCheckBody: () => { log.push('build'); return { body: { a: 1 }, rowIds: [7, 9], rowNumbers: [1, 3] } },
    checkRequired: async (body) => { log.push(`check:${JSON.stringify(body)}`); return { ok: true, data: { required_complete: true, missing: [] } } },
    showMissing: (missing, rowIds, rowNumbers) => log.push(`showMissing:${missing.length}:${rowIds.join(',')}:${rowNumbers.join(',')}`),
    clearMissing: () => log.push('clearMissing'),
    showCheckFailure: (message) => log.push(`failure:${message}`),
    proceed: () => log.push('proceed'),
    ...overrides
  }
  return ctx
}

test('流程：先檢查「我已核對」，未勾選時不鎖定、不收集、不呼叫 API', async () => {
  const ctx = makeCtx({ isAcknowledged: () => false })
  assert.deepEqual(await Rules.runConfirm(ctx), { status: 'not_acknowledged' })
  assert.deepEqual(ctx.log, ['notifyAck'])
})

test('流程：必填完整才進行原有流程；順序為鎖定→收集→檢核→清除缺漏→繼續→解除鎖定', async () => {
  const ctx = makeCtx()
  assert.deepEqual(await Rules.runConfirm(ctx), { status: 'complete' })
  assert.deepEqual(ctx.log, ['busy:true', 'collect', 'build', 'check:{"a":1}', 'clearMissing', 'proceed', 'busy:false'])
})

test('流程：有缺漏就停止，不繼續原有流程，並把列號對照一併交給畫面', async () => {
  const ctx = makeCtx({
    checkRequired: async () => ({ ok: true, data: { required_complete: false, missing: [miss('tax_type'), miss('item_name', 2)] } })
  })
  assert.deepEqual(await Rules.runConfirm(ctx), { status: 'missing' })
  assert.ok(ctx.log.includes('showMissing:2:7,9:1,3'))
  assert.ok(!ctx.log.includes('proceed'))
  assert.equal(ctx.state.busy, false)
})

test('流程：連續快速點擊只會觸發一次檢核', async () => {
  let release
  const gate = new Promise((resolve) => { release = resolve })
  let calls = 0
  const ctx = makeCtx({
    checkRequired: async () => {
      calls += 1
      await gate
      return { ok: true, data: { required_complete: true, missing: [] } }
    }
  })
  const first = Rules.runConfirm(ctx)
  const second = await Rules.runConfirm(ctx)
  const third = await Rules.runConfirm(ctx)
  assert.deepEqual([second, third], [{ status: 'busy' }, { status: 'busy' }])
  release()
  assert.deepEqual(await first, { status: 'complete' })
  assert.equal(calls, 1)
  assert.equal(ctx.log.filter((entry) => entry === 'proceed').length, 1)
})

test('流程：再次點擊一定重新檢核，不沿用上次結果', async () => {
  let calls = 0
  const ctx = makeCtx({
    checkRequired: async () => {
      calls += 1
      return calls === 1
        ? { ok: true, data: { required_complete: false, missing: [miss('tax_type')] } }
        : { ok: true, data: { required_complete: true, missing: [] } }
    }
  })
  assert.equal((await Rules.runConfirm(ctx)).status, 'missing')
  assert.equal((await Rules.runConfirm(ctx)).status, 'complete')
  assert.equal(calls, 2)
})

test('流程：網路失敗、5xx、401 以外的錯誤與矛盾回應都停止，不當成通過', async () => {
  const cases = [
    async () => { throw new Error('network') },
    async () => ({ ok: false, data: { error: { code: 'SERVICE_UNAVAILABLE', message: '服務暫時無法使用' } } }),
    async () => ({ ok: false, data: null }),
    async () => ({ ok: true, data: { required_complete: true, missing: [miss('tax_type')] } }),
    async () => ({ ok: true, data: {} })
  ]
  for (const checkRequired of cases) {
    const ctx = makeCtx({ checkRequired })
    assert.deepEqual(await Rules.runConfirm(ctx), { status: 'error' })
    assert.deepEqual(ctx.log.filter((entry) => entry.startsWith('failure:')), [`failure:${FAILURE}`])
    assert.ok(!ctx.log.includes('proceed'))
    assert.ok(!ctx.log.includes('clearMissing'))
    assert.ok(!ctx.log.some((entry) => entry.startsWith('showMissing')))
    assert.equal(ctx.state.busy, false)
  }
})

test('流程：Session 失效導向登入時（結果為 null）不顯示錯誤也不繼續', async () => {
  const ctx = makeCtx({ checkRequired: async () => null })
  assert.deepEqual(await Rules.runConfirm(ctx), { status: 'redirected' })
  assert.ok(!ctx.log.some((entry) => entry.startsWith('failure:')))
  assert.ok(!ctx.log.includes('proceed'))
  assert.equal(ctx.state.busy, false)
})

test('流程：收集欄位時發生例外，鎖定仍會解除', async () => {
  const ctx = makeCtx({ collect: () => { throw new Error('boom') } })
  await assert.rejects(Rules.runConfirm(ctx), /boom/)
  assert.equal(ctx.state.busy, false)
  assert.ok(!ctx.log.includes('proceed'))
})

// ---- 最後一輪補強 ----

test('流程：檢核失敗後按鈕恢復，再次按下會重新檢核，通過後才繼續', async () => {
  let calls = 0
  const ctx = makeCtx({
    checkRequired: async () => {
      calls += 1
      if (calls === 1) throw new Error('network')
      return { ok: true, data: { required_complete: true, missing: [] } }
    }
  })
  assert.deepEqual(await Rules.runConfirm(ctx), { status: 'error' })
  assert.equal(ctx.state.busy, false)
  assert.ok(!ctx.log.includes('proceed'))
  assert.deepEqual(await Rules.runConfirm(ctx), { status: 'complete' })
  assert.equal(calls, 2)
  assert.equal(ctx.log.filter((entry) => entry === 'proceed').length, 1)
})

test('流程：先有缺漏、之後檢核失敗，失敗處理在缺漏顯示之後且不放行', async () => {
  let calls = 0
  const ctx = makeCtx({
    checkRequired: async () => {
      calls += 1
      if (calls === 1) return { ok: true, data: { required_complete: false, missing: [miss('tax_type')] } }
      return { ok: false, data: null }
    }
  })
  assert.equal((await Rules.runConfirm(ctx)).status, 'missing')
  assert.equal((await Rules.runConfirm(ctx)).status, 'error')
  const order = ctx.log.filter((entry) => entry.startsWith('showMissing') || entry.startsWith('failure'))
  assert.deepEqual(order, ['showMissing:1:7,9:1,3', `failure:${FAILURE}`])
  assert.ok(!ctx.log.includes('proceed'))
})

// ---- 字軌提示：只對半形英文字母說「相容」（不改 normalizeTrack）----
test('字軌：ab、a-b 仍是藍色相容；ß 與其他會被 toUpperCase 轉成 ASCII 的字元是紅叉', () => {
  assert.equal(check('invoice_track', 'ab').state, 'compatible')
  assert.equal(check('invoice_track', 'a-b').state, 'compatible')
  assert.equal(check('invoice_track', 'AB').state, 'ok')
  for (const raw of ['ß', 'ßß', 'ŉ', 'ǰ', 'ﬁ', 'ﬀ', 'ﬃ', 'ı', 'ıı', 'ſ', 'ſſ', 'ΐ', 'ﬅ', 'ᾳ', 'ǈ', '\u212a', 'ａｂ', 'Ａb', 'a\u0301', 'İ']) {
    const result = check('invoice_track', raw)
    assert.equal(result.state, 'error', `${raw} (${[...raw].map((c) => c.codePointAt(0).toString(16)).join(',')})`)
    assert.equal(result.message, '請使用 2 碼半形大寫英文字母')
  }
})

test('字軌提示不改動 normalizeTrack：既有整理對特殊字元的結果維持原樣', () => {
  // 這些輸入在既有正式提交流程會被整理成符合格式的值；提示刻意比它保守（見 DEVELOPMENT_STATUS 的限制說明）
  assert.equal(Rules.normalizeTrack('ß'), 'SS')
  assert.equal(Rules.normalizeTrack('ıı'), 'II')
  assert.equal(Rules.normalizeTrack('ſſ'), 'SS')
  assert.equal(Rules.normalizeTrack('ﬁ'), 'FI')
})

test('字軌：掃描所有 BMP 字元，只有半形英文字母、空白與連字號能讓提示變成相容', () => {
  const fields = {
    invoice_track: { noise: /[\s-]/g, upper: true, re: /^[A-Z]{2}$/, samples: (c) => [c + 'B', 'A' + c, c + c, 'A' + c + 'B'] },
    invoice_number: { noise: /[\s-]/g, upper: false, re: /^[0-9]{8}$/, samples: (c) => ['1234567' + c, c + '1234567', '123' + c + '4567'] },
    seller_tax_id: { noise: /[\s,，]/g, upper: false, re: /^[0-9]{8}$/, samples: (c) => ['1234567' + c, c + '1234567', '123' + c + '4567'] },
    sales_amount: { noise: /[\s,，]/g, upper: false, re: /^\d{1,16}(\.\d{1,2})?$/, samples: (c) => ['12' + c + '3', c + '12', '12' + c] }
  }
  for (const [field, cfg] of Object.entries(fields)) {
    for (let code = 0; code <= 0xffff; code += 1) {
      if (code >= 0xd800 && code <= 0xdfff) continue
      const c = String.fromCharCode(code)
      for (const raw of cfg.samples(c)) {
        // 獨立的判斷：只去掉該欄位既有整理會去掉的雜訊；字軌再把「半形」小寫轉大寫（不用 toUpperCase）
        let oracle = raw.replace(cfg.noise, '')
        if (cfg.upper) oracle = oracle.replace(/[a-z]/g, (ch) => ch.toUpperCase())
        const strictlyOk = cfg.re.test(raw)
        const expected = strictlyOk ? 'ok' : cfg.re.test(oracle) ? 'compatible' : 'error'
        const actual = check(field, raw).state
        // 輸入全是雜訊（整理後為空）時是中性，不屬於這個比較
        if (oracle === '') { assert.equal(actual, 'empty'); continue }
        assert.equal(actual, expected, `${field} ${JSON.stringify(raw)} U+${code.toString(16)}`)
      }
    }
  }
})

// ---- buildCheckRequest：中間有完全空白的明細列 ----
const row = (rowId, values = {}, source = null) => ({
  row_id: rowId, source_line_no: source, item_name: '', quantity: '', unit_price: '', line_amount: '', ...values
})
const baseDraft = (items) => ({
  invoice_track: 'ab', invoice_number: '7567-0992', invoice_date: '2026-08-15', seller_name: '範例文具行',
  seller_tax_id: '2760 1907', buyer_name: '', buyer_tax_id: '', tax_type: 'taxable',
  sales_amount: '1,200', tax_amount: '60', total_amount: '1,260', total_amount_zh: '', items
})

test('buildCheckRequest：中間的完全空白列不送出，API 列號可對回畫面列與畫面編號', () => {
  const draft = baseDraft([
    row(11, { item_name: '甲', line_amount: '100' }, 1),
    row(12), // 完全空白：不送出
    row(17, { quantity: '3' }),               // 第 3 列：只填數量（缺品名與金額）
    row(19),                                  // 完全空白：不送出
    row(23, { item_name: '丁', line_amount: '' })
  ])
  const request = Rules.buildCheckRequest(draft, 'rec-1')

  assert.equal(request.body.items.length, 3)
  assert.deepEqual(request.rowIds, [11, 17, 23])
  assert.deepEqual(request.rowNumbers, [1, 3, 5])
  assert.deepEqual(request.body.items.map((item) => item.item_name), ['甲', '', '丁'])

  // API 以送出順序回報：第 2 筆缺品名與金額、第 3 筆缺金額 → 對到畫面第 3、5 列
  const plan = Rules.planMissing(
    [miss('item_name', 2), miss('line_amount', 2), miss('line_amount', 3)], request.rowIds, LABELS, request.rowNumbers
  )
  assert.deepEqual(plan.targets.map((t) => [t.key, t.summary]), [
    ['i:17:item_name', '第 3 筆明細的品名'],
    ['i:17:line_amount', '第 3 筆明細的金額'],
    ['i:23:line_amount', '第 5 筆明細的金額']
  ])
})

test('buildCheckRequest：全部明細列都是空白時 items 為空；使用與 buildPayload 相同的整理', () => {
  const empty = Rules.buildCheckRequest(baseDraft([row(1), row(2)]), 'rec-1')
  assert.deepEqual(empty.body.items, [])
  assert.deepEqual(empty.rowIds, [])

  const request = Rules.buildCheckRequest(baseDraft([row(1, { item_name: '甲', quantity: '1,000', unit_price: ' ', line_amount: '1，200' })]), 'rec-1')
  assert.deepEqual(request.body, {
    recognition_id: 'rec-1', invoice_track: 'AB', invoice_number: '75670992', invoice_date: '2026-08-15',
    seller_name: '範例文具行', seller_tax_id: '27601907', buyer_name: null, buyer_tax_id: null, tax_type: 'taxable',
    sales_amount: '1200', tax_amount: '60', total_amount: '1260', total_amount_zh: null,
    items: [{ source_line_no: null, item_name: '甲', quantity: '1000', unit_price: null, line_amount: '1200' }]
  })
})

test('buildCheckRequest：不改動傳入的內容（使用者填寫的值保持原樣）', () => {
  const draft = baseDraft([row(1, { item_name: '甲', line_amount: '1,200' })])
  const before = JSON.stringify(draft)
  Rules.buildCheckRequest(draft, 'rec-1')
  assert.equal(JSON.stringify(draft), before)
})

// ---- placeMissing：畫面上找不到欄位時仍保留摘要 ----
test('placeMissing：找得到的欄位標示在畫面，找不到的一律改列摘要，總數不變', () => {
  const missing = [miss('invoice_number'), miss('tax_type'), miss('items'), miss('item_name', 1), miss('mystery_field')]
  const present = new Set(['h:invoice_number', 'i:17:item_name'])
  const plan = Rules.placeMissing(missing, [17], LABELS, [3], (key) => present.has(key))

  assert.deepEqual(plan.targets.map((t) => t.key), ['h:invoice_number', 'i:17:item_name'])
  assert.deepEqual(plan.unmapped.map((u) => u.summary).sort(), ['mystery_field', '課稅別', '品名明細'].sort())
  assert.equal(plan.total, 5)
})

test('placeMissing：畫面上完全沒有任何對應欄位時，全部缺漏都在摘要，一個都不會被吞掉', () => {
  const missing = [miss('invoice_track'), miss('invoice_date'), miss('item_name', 2), miss('line_amount', 2), miss('items')]
  const plan = Rules.placeMissing(missing, [5, 6], LABELS, [1, 2], () => false)

  assert.equal(plan.targets.length, 0)
  assert.equal(plan.unmapped.length, 5)
  assert.equal(plan.total, missing.length)
  assert.deepEqual(plan.unmapped.map((u) => u.summary), [
    '字軌', '發票日期', '第 2 筆明細的品名', '第 2 筆明細的金額', '品名明細'
  ])
  for (const entry of plan.unmapped) assert.ok(entry.summary && entry.summary.length > 0)
})

test('placeMissing：重複的缺漏不會讓總數虛增', () => {
  const plan = Rules.placeMissing([miss('tax_type'), miss('tax_type')], [], LABELS, [], () => false)
  assert.equal(plan.total, 1)
})
