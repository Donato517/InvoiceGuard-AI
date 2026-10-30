// 測試目標：app/static/js/image-picker.js 的選取／預覽狀態邏輯。
// 注意：這裡用「假 DOM」模擬元素與 object URL，驗證的是狀態機與資源釋放，
// 不是真實瀏覽器的檔案對話框、圖片解碼與版面；真實瀏覽器互動須另行手動或 E2E 驗證。
// 執行：node --test tests/js/
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(import.meta.url)
const { createPicker, validateFile } = require('../../app/static/js/image-picker.js')

const LIMIT = 1024
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, ...new Array(20).fill(0)])
const PNG = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0x0d, 0x49, 0x48, 0x44, 0x52,
  ...new Array(10).fill(0)
])

const file = (bytes, name, type) => new File([bytes], name, { type })

function fakeEl() {
  const listeners = {}
  const attrs = {}
  return {
    hidden: false,
    textContent: '',
    value: '',
    files: [],
    attrs,
    setAttribute(k, v) { attrs[k] = String(v) },
    getAttribute(k) { return k in attrs ? attrs[k] : null },
    removeAttribute(k) { delete attrs[k] },
    addEventListener(t, fn) { listeners[t] = fn },
    removeEventListener(t) { delete listeners[t] },
    fire(t, ev = {}) { return listeners[t] && listeners[t](ev) },
    focus() {},
    closest() { return null }
  }
}

function setup() {
  const parts = {
    'input[type="file"]': fakeEl(),
    '[data-image-picker-preview]': fakeEl(),
    '[data-image-picker-image]': fakeEl(),
    '[data-image-picker-name]': fakeEl(),
    '[data-image-picker-size]': fakeEl(),
    '[data-image-picker-error]': fakeEl(),
    '[data-image-picker-clear]': fakeEl()
  }
  const container = fakeEl()
  container.setAttribute('data-max-bytes', LIMIT)
  container.querySelector = (sel) => parts[sel]
  const live = new Set()
  let n = 0
  const urls = {
    createObjectURL() { const u = `blob:${++n}`; live.add(u); return u },
    revokeObjectURL(u) { live.delete(u) }
  }
  const picker = createPicker(container, urls)
  const input = parts['input[type="file"]']
  const choose = async (f) => {
    input.files = f ? [f] : []
    input.fire('change')
    await new Promise((r) => setTimeout(r, 5))
  }
  return { container, parts, live, picker, input, choose }
}

const state = (s) => s.container.getAttribute('data-state')
const err = (s) => s.parts['[data-image-picker-error]']

test('valid JPG and PNG show preview', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'a.jpg', 'image/jpeg'))
  assert.equal(state(s), 'selected')
  assert.equal(s.parts['[data-image-picker-image]'].getAttribute('src'), 'blob:1')
  assert.equal(s.parts['[data-image-picker-name]'].textContent, 'a.jpg')
  await s.choose(file(PNG, 'b.png', 'image/png'))
  assert.equal(state(s), 'selected')
})

test('replacing A with B shows B and releases A', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'A.jpg', 'image/jpeg'))
  await s.choose(file(PNG, 'B.png', 'image/png'))
  assert.equal(s.parts['[data-image-picker-name]'].textContent, 'B.png')
  assert.equal(s.parts['[data-image-picker-image]'].getAttribute('src'), 'blob:2')
  assert.deepEqual([...s.live], ['blob:2'])
})

test('cancel selection returns to idle and releases url', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'a.jpg', 'image/jpeg'))
  await s.choose(null)
  assert.equal(state(s), 'idle')
  assert.equal(s.live.size, 0)
  assert.equal(s.parts['[data-image-picker-preview]'].hidden, true)
  assert.equal(s.picker.hasValidFile(), false)
})

const bad = [
  ['unsupported format', file(JPEG, 'a.gif', 'image/gif'), '只支援'],
  ['empty file', file(new Uint8Array(0), 'a.jpg', 'image/jpeg'), '空的'],
  ['too large', file(new Uint8Array(LIMIT + 1), 'a.jpg', 'image/jpeg'), '過大'],
  ['fake content', file(new TextEncoder().encode('hello world, not image'), 'a.jpg', 'image/jpeg'), '內容'],
  ['png disguised as jpg', file(PNG, 'a.jpg', 'image/jpeg'), '內容']
]
for (const [name, f, text] of bad) {
  test(`invalid (${name}) shows error, no preview, input cleared`, async () => {
    const s = setup()
    await s.choose(f)
    assert.equal(state(s), 'error')
    assert.ok(err(s).textContent.includes(text), err(s).textContent)
    assert.equal(err(s).hidden, false)
    assert.equal(s.parts['[data-image-picker-preview]'].hidden, true)
    assert.equal(s.live.size, 0)
    assert.equal(s.input.value, '')
    assert.equal(s.picker.hasValidFile(), false)
  })
}

test('valid file after error clears the error', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'a.gif', 'image/gif'))
  assert.equal(state(s), 'error')
  await s.choose(file(JPEG, 'a.jpg', 'image/jpeg'))
  assert.equal(state(s), 'selected')
  assert.equal(err(s).hidden, true)
  assert.equal(err(s).textContent, '')
})

test('valid file replaced by invalid file drops old preview', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'a.jpg', 'image/jpeg'))
  await s.choose(file(JPEG, 'b.pdf', 'application/pdf'))
  assert.equal(state(s), 'error')
  assert.equal(s.live.size, 0)
  assert.equal(s.parts['[data-image-picker-image]'].getAttribute('src'), null)
})

test('clear button resets to idle', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'a.jpg', 'image/jpeg'))
  s.parts['[data-image-picker-clear]'].fire('click')
  assert.equal(state(s), 'idle')
  assert.equal(s.live.size, 0)
})

test('image load error becomes preview_failed, not success', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'a.jpg', 'image/jpeg'))
  s.parts['[data-image-picker-image]'].fire('error')
  assert.equal(state(s), 'error')
  assert.equal(s.live.size, 0)
  assert.equal(s.picker.hasValidFile(), false)
})

test('stale async validation cannot overwrite a newer selection', async () => {
  const s = setup()
  s.input.files = [file(JPEG, 'old.jpg', 'image/jpeg')]
  s.input.fire('change')
  s.input.files = [file(PNG, 'new.png', 'image/png')]
  s.input.fire('change')
  await new Promise((r) => setTimeout(r, 10))
  assert.equal(s.parts['[data-image-picker-name]'].textContent, 'new.png')
  assert.equal(s.live.size, 1)
})

test('submit without a valid file is blocked and shows no_file error', async () => {
  const s = setup()
  let prevented = false
  const form = fakeEl()
  s.container.closest = () => form
  const s2Picker = createPicker(s.container, { createObjectURL() {}, revokeObjectURL() {} })
  form.fire('submit', { preventDefault() { prevented = true } })
  assert.equal(prevented, true)
  assert.ok(err(s).textContent.includes('請選擇'))
  s2Picker.destroy()
})

test('destroy releases the object url', async () => {
  const s = setup()
  await s.choose(file(JPEG, 'a.jpg', 'image/jpeg'))
  s.picker.destroy()
  assert.equal(s.live.size, 0)
})

test('validateFile never reports success for missing file', async () => {
  assert.deepEqual(await validateFile(null, LIMIT), { ok: false, code: 'no_file' })
})
