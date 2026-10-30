/**
 * 模組名稱：invoice-field-rules.js
 * 功能說明：上傳核對頁的欄位規則（純函式，不碰 DOM、不呼叫 API）——
 *   1. 送出前既有的資料整理（字軌／號碼、金額與統編），由 mobile-camera.js 的 buildPayload() 與格式提示共用；
 *   2. 欄位格式提示的判斷（格式正確／格式相容／格式錯誤／尚未填寫／無明確規則）；
 *   3. 必填缺漏（API POST /invoices/check-required）對應到畫面欄位，以及「上傳者確認」的檢核流程；
 *   4. 業務警示（API POST /invoices/check-warnings：發票日期晚於今天、金額不一致）的解讀與顯示文字。
 * 注意事項：
 *   - 格式規則須與 API InvoiceSubmitRequest 相同（字軌 ^[A-Z]{2}$、號碼與統編 ^[0-9]{8}$、金額最多 16 位整數＋2 位小數、
 *     數量與單價最多 14 位整數＋4 位小數）；tests/unit/test_required_fields_contract.py 在兩站同目錄時比對。
 *   - 必填欄位清單同樣以 API InvoiceSubmitRequest 為準，這裡只是畫面標示用的副本，不是另一套規則。
 *   - 「格式正確」只代表輸入符合欄位格式，不代表發票真實、AI 辨識正確、統編存在或財會已核准；
 *     「格式相容」代表既有整理規則可把輸入轉成符合格式的值，輸入框的內容不會被改動；兩者都不代表整張發票已通過檢核。
 *   - 沒有明確格式規則的欄位（名稱、課稅別、國字大寫、品名）不顯示綠勾。
 */
;(function (root) {
  'use strict';

  // ---- 與 API 相同的格式（API: app/schemas/invoice_upload.py）----
  var TRACK_RE = /^[A-Z]{2}$/;
  var NUMBER_RE = /^[0-9]{8}$/;
  var TAX_ID_RE = /^[0-9]{8}$/;
  var AMOUNT_RE = /^\d{1,16}(\.\d{1,2})?$/;
  var QUANTITY_RE = /^\d{1,14}(\.\d{1,4})?$/;

  // ---- 既有的資料整理（原本寫在 buildPayload()／cleanNumber()，行為不變）----
  function normalizeTrack(value) {
    return String(value).toUpperCase().replace(/[\s-]/g, '');
  }

  function normalizeNumber(value) {
    return String(value).replace(/[\s-]/g, '');
  }

  function cleanNumber(value) {
    return String(value || '').replace(/[\s,，]/g, '');
  }

  // ---- 必填欄位（與 API InvoiceSubmitRequest 沒有預設值的欄位相同；recognition_id 為內部欄位不列入）----
  var REQUIRED_HEADER_FIELDS = [
    'invoice_track',
    'invoice_number',
    'invoice_date',
    'seller_tax_id',
    'tax_type',
    'sales_amount',
    'tax_amount',
    'total_amount',
  ];
  var REQUIRED_ITEM_FIELDS = ['item_name', 'line_amount'];
  var ITEM_FIELDS = ['item_name', 'quantity', 'unit_price', 'line_amount'];

  var FULL_WIDTH_DIGITS = /[０-９．]/;

  // 必填檢核無法完成（網路、API 錯誤、回應異常）時給使用者的說明；此時資料尚未送出
  var CHECK_FAILURE_MESSAGE = '目前無法完成必填欄位檢查，請稍後再試。資料尚未送出。';

  function amountMessage(cleaned, label, maxInt, maxFraction) {
    if (FULL_WIDTH_DIGITS.test(cleaned)) return '請使用半形數字';
    var match = /^(\d+)(?:\.(\d+))?$/.exec(cleaned);
    if (match && match[2] && match[2].length > maxFraction) {
      return label + '格式不正確，最多 ' + maxFraction + ' 位小數';
    }
    if (match && match[1].length > maxInt) return label + '整數最多 ' + maxInt + ' 位';
    return '請輸入半形數字（可含小數點）';
  }

  // 代碼類欄位的錯誤說明；全形字元也落在這則說明（已明講「半形」），不另外疊加提示
  function codeMessage(text) {
    return function () {
      return text;
    };
  }

  // 有明確格式規則的欄位：整理函式、格式、錯誤說明（欄位不在此表＝沒有明確規則）
  var RULES = {
    invoice_track: {
      normalize: normalizeTrack,
      re: TRACK_RE,
      message: codeMessage('請使用 2 碼半形大寫英文字母'),
      // 既有 normalizeTrack 用 toUpperCase()，會把部分非英文字母轉成 ASCII（例如 ß→SS、ı→I、ſ→S、ﬁ→FI）。
      // 提示只在輸入本來就是半形英文字母（去掉空白與連字號後）時才說「相容」，不改動整理行為。
      preserved: function (text) {
        return /^[A-Za-z]*$/.test(text.replace(/[\s-]/g, ''));
      },
    },
    invoice_number: {
      normalize: normalizeNumber,
      re: NUMBER_RE,
      message: codeMessage('請輸入 8 碼半形數字'),
    },
    seller_tax_id: {
      normalize: cleanNumber,
      re: TAX_ID_RE,
      message: codeMessage('請輸入 8 碼半形數字'),
    },
    buyer_tax_id: {
      normalize: cleanNumber,
      re: TAX_ID_RE,
      message: codeMessage('請輸入 8 碼半形數字'),
    },
    sales_amount: {
      normalize: cleanNumber,
      re: AMOUNT_RE,
      message: function (c) { return amountMessage(c, '金額', 16, 2); },
    },
    tax_amount: {
      normalize: cleanNumber,
      re: AMOUNT_RE,
      message: function (c) { return amountMessage(c, '金額', 16, 2); },
    },
    total_amount: {
      normalize: cleanNumber,
      re: AMOUNT_RE,
      message: function (c) { return amountMessage(c, '金額', 16, 2); },
    },
    line_amount: {
      normalize: cleanNumber,
      re: AMOUNT_RE,
      message: function (c) { return amountMessage(c, '金額', 16, 2); },
    },
    quantity: {
      normalize: cleanNumber,
      re: QUANTITY_RE,
      message: function (c) { return amountMessage(c, '數量', 14, 4); },
    },
    unit_price: {
      normalize: cleanNumber,
      re: QUANTITY_RE,
      message: function (c) { return amountMessage(c, '單價', 14, 4); },
    },
  };

  function isValidIsoDate(text) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    if (!match) return false;
    var year = Number(match[1]);
    var month = Number(match[2]);
    var day = Number(match[3]);
    if (year < 1) return false;
    var date = new Date(Date.UTC(year, month - 1, day));
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
  }

  /**
   * 判斷單一欄位目前輸入的格式提示。
   * @param {string} field 欄位名稱（同 API）。
   * @param {string} raw 輸入框目前的原始內容（不整理、不修改）。
   * @returns {{state: string, message: string}} state：
   *   none（此欄位沒有明確格式規則，不顯示提示）、empty（尚未填寫，保持中性）、
   *   ok（格式正確）、compatible（格式相容，既有整理後符合）、error（格式錯誤，message 為原因）。
   */
  function evaluateField(field, raw) {
    var text = raw === null || raw === undefined ? '' : String(raw);
    if (field === 'invoice_date') {
      if (text.trim() === '') return { state: 'empty', message: '' };
      return isValidIsoDate(text)
        ? { state: 'ok', message: '格式正確' }
        : { state: 'error', message: '請選擇有效的日期' };
    }
    var rule = RULES[field];
    if (!rule) return { state: 'none', message: '' };
    var cleaned = rule.normalize(text);
    if (cleaned === '') return { state: 'empty', message: '' };
    if (rule.re.test(text)) return { state: 'ok', message: '格式正確' };
    if (rule.re.test(cleaned) && (!rule.preserved || rule.preserved(text))) {
      return { state: 'compatible', message: '格式相容，可送出' };
    }
    return { state: 'error', message: rule.message(cleaned) };
  }

  // ---- 必填缺漏對應畫面欄位 ----
  var ITEMS_KEY = 'items';

  function headerKey(field) {
    return 'h:' + field;
  }

  function itemKey(rowId, field) {
    return 'i:' + rowId + ':' + field;
  }

  /**
   * 把 API 回傳的 missing 對應到畫面欄位。
   * @param {Array} missing API 的 missing 清單（field、line_no、message）。
   * @param {Array<number>} rowIds 送出內容中第 n 筆明細（line_no = n）對應的畫面列 row_id。
   * @param {Object<string, string>} labels 欄位名稱 → 中文名稱。
   * @param {Array<number>} [rowNumbers] 各畫面列在畫面上顯示的「明細 N」編號（與 rowIds 同順序）；
   *   全空的明細列不會送出，送出順序的列號可能與畫面編號不同，摘要要用畫面上看得到的編號。省略時沿用 API 的列號。
   * @returns {{targets: Array, unmapped: Array, total: number}} targets 可在畫面標示（key、field、rowId、text、summary）；
   *   unmapped 找不到對應畫面元素的缺漏，仍須出現在摘要，不可忽略。
   */
  function planMissing(missing, rowIds, labels, rowNumbers) {
    var targets = [];
    var unmapped = [];
    var seen = {};
    (missing || []).forEach(function (entry) {
      var field = entry && typeof entry.field === 'string' ? entry.field : '';
      var lineNo = entry && Number.isInteger(entry.line_no) ? entry.line_no : null;
      var label = labels[field] || field || '未知欄位';
      var target = null;
      if (field === ITEMS_KEY && lineNo === null) {
        target = { key: ITEMS_KEY, field: field, rowId: null, text: '請至少填寫一筆品名明細', summary: '品名明細' };
      } else if (lineNo === null && REQUIRED_HEADER_FIELDS.indexOf(field) >= 0) {
        target = { key: headerKey(field), field: field, rowId: null, text: '請補填' + label, summary: label };
      } else if (lineNo !== null && ITEM_FIELDS.indexOf(field) >= 0 && lineNo >= 1 && lineNo <= rowIds.length) {
        target = {
          key: itemKey(rowIds[lineNo - 1], field),
          field: field,
          rowId: rowIds[lineNo - 1],
          text: '請補填' + label,
          summary: '第 ' + ((rowNumbers && rowNumbers[lineNo - 1]) || lineNo) + ' 筆明細的' + label,
        };
      }
      if (target === null) {
        var where = lineNo === null ? '' : '第 ' + lineNo + ' 筆明細的';
        unmapped.push({ field: field, line_no: lineNo, summary: where + label });
      } else if (!seen[target.key]) {
        seen[target.key] = true;
        targets.push(target);
      }
    });
    return { targets: targets, unmapped: unmapped, total: targets.length + unmapped.length };
  }

  /**
   * 把 API 的缺漏分成「畫面上有對應欄位」與「只能列在摘要」兩組；對應欄位實際不存在於畫面時一律改列摘要，不會被吞掉。
   * @param {Array} missing API 的 missing 清單。
   * @param {Array<number>} rowIds 同 planMissing。
   * @param {Object<string, string>} labels 同 planMissing。
   * @param {Array<number>} rowNumbers 同 planMissing。
   * @param {function(string): boolean} hasElement 判斷某個畫面欄位（key）目前是否存在。
   * @returns {{targets: Array, unmapped: Array, total: number}} total 一定等於 missing 中不重複的缺漏數。
   */
  function placeMissing(missing, rowIds, labels, rowNumbers, hasElement) {
    var plan = planMissing(missing, rowIds, labels, rowNumbers);
    var targets = [];
    var unmapped = plan.unmapped.slice();
    plan.targets.forEach(function (target) {
      if (hasElement(target.key)) targets.push(target);
      else unmapped.push({ field: target.field, line_no: null, summary: target.summary });
    });
    return { targets: targets, unmapped: unmapped, total: targets.length + unmapped.length };
  }

  /**
   * 把目前填寫的內容整理成必填檢核的請求（欄位同 POST /invoices；不驗證格式，缺漏與格式錯誤都照實送出）。
   * 使用與 buildPayload 相同的整理 helper，不新增任何整理規則。
   * @param {{items: Array}} draft 核對頁目前的欄位值（欄位已去除前後空白）。
   * @param {string} recognitionId 辨識紀錄 id（內部欄位）。
   * @returns {{body: Object, rowIds: Array<number>, rowNumbers: Array<number>}} 全空的明細列不送出（與 buildPayload 相同）：
   *   rowIds[n - 1] 是送出內容第 n 筆明細對應的畫面列，rowNumbers[n - 1] 是該列在畫面上的「明細 N」編號。
   */
  function buildCheckRequest(draft, recognitionId) {
    var rowIds = [];
    var rowNumbers = [];
    var items = [];
    draft.items.forEach(function (row, index) {
      var hasContent = ITEM_FIELDS.some(function (field) {
        return row[field];
      });
      if (!hasContent) return;
      rowIds.push(row.row_id);
      rowNumbers.push(index + 1);
      items.push({
        source_line_no: row.source_line_no,
        item_name: row.item_name,
        quantity: cleanNumber(row.quantity) || null,
        unit_price: cleanNumber(row.unit_price) || null,
        line_amount: cleanNumber(row.line_amount),
      });
    });
    var body = {
      recognition_id: recognitionId,
      invoice_track: normalizeTrack(draft.invoice_track),
      invoice_number: normalizeNumber(draft.invoice_number),
      invoice_date: draft.invoice_date,
      seller_name: draft.seller_name || null,
      seller_tax_id: cleanNumber(draft.seller_tax_id),
      buyer_name: draft.buyer_name || null,
      buyer_tax_id: cleanNumber(draft.buyer_tax_id) || null,
      tax_type: draft.tax_type,
      sales_amount: cleanNumber(draft.sales_amount),
      tax_amount: cleanNumber(draft.tax_amount),
      total_amount: cleanNumber(draft.total_amount),
      total_amount_zh: draft.total_amount_zh || null,
      items: items,
    };
    return { body: body, rowIds: rowIds, rowNumbers: rowNumbers };
  }

  /**
   * 解讀必填檢核 API 的結果；任何無法確認的結果都視為失敗，不可當成通過。
   * @param {{ok: boolean, data: *}} result 呼叫結果。
   * @returns {{kind: string, missing: Array, message: string}} kind：complete、missing 或 error。
   */
  function parseCheckResult(result) {
    var failure = { kind: 'error', missing: [], message: CHECK_FAILURE_MESSAGE };
    var data = result && result.data;
    if (!result || !result.ok || !data || typeof data !== 'object') return failure;
    if (typeof data.required_complete !== 'boolean' || !Array.isArray(data.missing)) return failure;
    var valid = data.missing.every(function (entry) {
      return entry && typeof entry === 'object' && typeof entry.field === 'string';
    });
    if (!valid) return failure;
    if (data.required_complete && data.missing.length === 0) return { kind: 'complete', missing: [], message: '' };
    if (!data.required_complete && data.missing.length > 0) {
      return { kind: 'missing', missing: data.missing, message: '' };
    }
    return failure; // 回應自相矛盾：不放行
  }

  // ---- 業務警示（規則全部在 API；這裡只負責解讀回應與組出顯示文字，不判斷日期或金額是否有問題）----
  var BUSINESS_WARNING_CODES = [
    'invoice_date_future',
    'total_amount_mismatch',
    'tax_amount_mismatch',
    'items_total_mismatch',
  ];
  // 業務警示預覽無法完成時的說明；不影響送出，正式送出時 API 仍會重新計算
  var WARNING_FAILURE_MESSAGE =
    '目前無法更新業務警示，請自行核對發票日期與金額。這不影響送出，送出時系統仍會重新檢核。';
  var WARNING_NOTE = '這是人工核對提醒，不代表已被拒絕提交。';

  /**
   * 解讀業務警示預覽 API 的結果；無法確認的結果一律視為失敗，不可當成「沒有警示」。
   * @param {{ok: boolean, data: *}} result 呼叫結果。
   * @returns {{kind: string, warnings: Array}} kind：ok 或 error；ok 只保留已知的業務警示代碼。
   */
  function parseWarningResult(result) {
    var failure = { kind: 'error', warnings: [] };
    var data = result && result.data;
    if (!result || !result.ok || !data || typeof data !== 'object' || !Array.isArray(data.warnings)) return failure;
    var valid = data.warnings.every(function (entry) {
      return (
        entry &&
        typeof entry === 'object' &&
        typeof entry.field === 'string' &&
        typeof entry.code === 'string' &&
        typeof entry.message === 'string'
      );
    });
    if (!valid) return failure;
    return {
      kind: 'ok',
      warnings: data.warnings.filter(function (entry) {
        return BUSINESS_WARNING_CODES.indexOf(entry.code) !== -1;
      }),
    };
  }

  /** 業務警示要掛在哪個畫面欄位：明細合計掛在明細區，其餘掛在同名表頭欄位。 */
  function warningKey(warning) {
    return warning.field === 'items' ? ITEMS_KEY : headerKey(warning.field);
  }

  // 金額字串（已整理成半形、最多 2 位小數）→ 以「分」計的整數；格式不符回傳 null
  function toCents(value) {
    var text = String(value === undefined || value === null ? '' : value);
    if (!AMOUNT_RE.test(text)) return null;
    var parts = text.split('.');
    return BigInt(parts[0]) * 100n + BigInt(((parts[1] || '') + '00').slice(0, 2));
  }

  function formatCents(cents) {
    var whole = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    var fraction = (cents % 100n).toString().padStart(2, '0').replace(/0+$/, '');
    return fraction ? whole + '.' + fraction : whole;
  }

  /**
   * 總計不一致時的差額說明；只用畫面上已有的三個數字做加減，不套用任何稅率或容差。
   * @param {{sales_amount: string, tax_amount: string, total_amount: string}} values 整理後的金額字串。
   * @returns {string} 三個金額都可解讀才有內容，否則為空字串（不顯示不確定的算式）。
   */
  function differenceText(values) {
    var sales = toCents(values.sales_amount);
    var tax = toCents(values.tax_amount);
    var total = toCents(values.total_amount);
    if (sales === null || tax === null || total === null) return '';
    var expected = sales + tax;
    var diff = total > expected ? total - expected : expected - total;
    return (
      '銷售額 ' + formatCents(sales) + ' ＋ 營業稅額 ' + formatCents(tax) + ' ＝ ' + formatCents(expected) +
      '；輸入總計 ' + formatCents(total) + '，差額 ' + formatCents(diff) + ' 元。'
    );
  }

  /**
   * 業務警示的顯示文字。總計不一致與未來日期使用核定文案，其餘沿用 API 的中文訊息。
   * @param {{code: string, message: string}} warning API 警示。
   * @param {Object} values 目前整理後的送出值（用來算差額）。
   * @returns {string}
   */
  function warningText(warning, values) {
    if (warning.code === 'invoice_date_future') return '發票日期晚於今天，請核對原始發票。';
    if (warning.code === 'total_amount_mismatch') {
      var detail = differenceText(values || {});
      return '總計與銷售額及營業稅額不一致，請核對。' + (detail ? detail : '');
    }
    return warning.message;
  }

  /**
   * 「上傳者確認」的檢核流程（依賴由呼叫端注入，方便離線測試）。
   * 順序：確認已勾選「我已核對」→ 鎖定避免重複點擊 → 收集欄位 → 呼叫必填檢核 API →
   * 有缺漏或檢核失敗就停止 → 全部必填完整才進行原有流程（proceed）。
   * @param {Object} ctx 注入的行為：isBusy、setBusy、isAcknowledged、notifyAck、collect、buildCheckBody、
   *   checkRequired、showMissing、clearMissing、showCheckFailure、proceed。檢核失敗時呼叫 showCheckFailure（呼叫端須清除
   *   上一次已過期的缺漏提示並顯示 CHECK_FAILURE_MESSAGE），不會呼叫 proceed，所以不會進入查重或正式提交。
   * @returns {Promise<{status: string}>} status：busy、not_acknowledged、redirected、error、missing、complete。
   */
  async function runConfirm(ctx) {
    if (ctx.isBusy()) return { status: 'busy' };
    if (!ctx.isAcknowledged()) {
      ctx.notifyAck();
      return { status: 'not_acknowledged' };
    }
    ctx.setBusy(true);
    try {
      ctx.collect();
      var request = ctx.buildCheckBody();
      var result;
      try {
        result = await ctx.checkRequired(request.body);
      } catch (error) {
        ctx.showCheckFailure(CHECK_FAILURE_MESSAGE);
        return { status: 'error' };
      }
      if (result === null || result === undefined) return { status: 'redirected' };
      var parsed = parseCheckResult(result);
      if (parsed.kind === 'error') {
        ctx.showCheckFailure(parsed.message);
        return { status: 'error' };
      }
      if (parsed.kind === 'missing') {
        ctx.showMissing(parsed.missing, request.rowIds, request.rowNumbers);
        return { status: 'missing' };
      }
      ctx.clearMissing();
      await ctx.proceed(); // proceed 可為非同步（取業務警示）；忙碌鎖在完成前不解除，避免重複點擊
      return { status: 'complete' };
    } finally {
      ctx.setBusy(false);
    }
  }

  var api = {
    TRACK_RE: TRACK_RE,
    NUMBER_RE: NUMBER_RE,
    TAX_ID_RE: TAX_ID_RE,
    AMOUNT_RE: AMOUNT_RE,
    QUANTITY_RE: QUANTITY_RE,
    REQUIRED_HEADER_FIELDS: REQUIRED_HEADER_FIELDS,
    REQUIRED_ITEM_FIELDS: REQUIRED_ITEM_FIELDS,
    ITEM_FIELDS: ITEM_FIELDS,
    normalizeTrack: normalizeTrack,
    normalizeNumber: normalizeNumber,
    cleanNumber: cleanNumber,
    evaluateField: evaluateField,
    headerKey: headerKey,
    itemKey: itemKey,
    ITEMS_KEY: ITEMS_KEY,
    CHECK_FAILURE_MESSAGE: CHECK_FAILURE_MESSAGE,
    BUSINESS_WARNING_CODES: BUSINESS_WARNING_CODES,
    WARNING_FAILURE_MESSAGE: WARNING_FAILURE_MESSAGE,
    WARNING_NOTE: WARNING_NOTE,
    parseWarningResult: parseWarningResult,
    warningKey: warningKey,
    differenceText: differenceText,
    warningText: warningText,
    planMissing: planMissing,
    placeMissing: placeMissing,
    buildCheckRequest: buildCheckRequest,
    parseCheckResult: parseCheckResult,
    runConfirm: runConfirm,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.InvoiceFieldRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
