/**
 * 模組名稱：mobile-camera.js
 * 功能說明：發票上傳——手機拍照（外框對齊檢測）或電腦選取本機檔案、90° 旋轉預覽、AI 辨識、
 *   欄位核對（標記使用者修改的欄位）、查重與送出。手機拍照頁與電腦上傳頁共用，以 data-upload-mode 區分：
 *   camera（手機拍照頁，JPG／PNG）、file（電腦上傳頁，JPG／PNG 與單頁 PDF）。
 * 注意事項：
 *   - 辨識、查重、送出經本站 /invoices/mobile-recognize、/invoices/check-duplicate、/invoices/mobile-upload
 *     轉呼叫 API（fetch 帶 Accept: application/json，錯誤回 JSON）；送出時沿用 API 辨識時保存的影像
 *     （辨識後 1 小時內有效）。
 *   - 影像辨識前先縮成最長邊 2000px 的 JPEG（Vercel 請求上限 4.5 MB）；PDF 不轉換、不旋轉，原檔上傳（4 MB 以內）。
 *   - 與 AI 辨識值不同的欄位即時標記「已修改」；每次修改（欄位離開或選擇時）記入修改紀錄，送出時一併給 API，
 *     API 寫入 invoice_field_reviews（供審核標示）與 invoice_changes（逐次修改）。
 *     比對規則 canonicalValue 須與 API invoice_upload_service._canonical_value 相同。
 *   - 欄位值一律以 value／textContent 寫入，不拼接 HTML，避免辨識內容被當成標記執行。
 *   - 必填欄位標示 *必填（清單與 API InvoiceSubmitRequest 相同）；欄位離開時顯示格式提示（格式正確／格式相容／格式錯誤，
 *     不改動輸入內容、不呼叫 API）；按「上傳者確認」才經 /invoices/check-required 檢核必填缺漏並一次顯示。
 *     格式規則與送出前的資料整理在 invoice-field-rules.js（純函式，有 node 測試）。
 */

(function () {
  'use strict';

  // 欄位名稱同 API／public.invoices、invoice_items
  const FIELD_LABELS = {
    invoice_track: '字軌',
    invoice_number: '號碼',
    invoice_date: '發票日期',
    buyer_name: '買受人名稱',
    buyer_tax_id: '買受人統一編號',
    seller_name: '賣方（銷貨人）名稱',
    seller_tax_id: '賣方統一編號',
    tax_type: '課稅別',
    sales_amount: '銷售額合計',
    tax_amount: '營業稅額',
    total_amount: '總計',
    total_amount_zh: '總計新臺幣（國字大寫）',
    item_name: '品名',
    quantity: '數量',
    unit_price: '單價',
    line_amount: '金額',
  };
  const HEADER_FIELDS = [
    'invoice_track',
    'invoice_number',
    'invoice_date',
    'buyer_name',
    'buyer_tax_id',
    'sales_amount',
    'tax_type',
    'tax_amount',
    'total_amount',
    'total_amount_zh',
    'seller_name',
    'seller_tax_id',
  ];
  const ITEM_FIELDS = ['item_name', 'quantity', 'unit_price', 'line_amount'];
  const AMOUNT_FIELDS = ['sales_amount', 'tax_amount', 'total_amount'];
  const INPUT_ATTRS = {
    invoice_track: { maxlength: '2', autocapitalize: 'characters', placeholder: 'AB' },
    invoice_number: { maxlength: '8', inputmode: 'numeric', placeholder: '12345678' },
    invoice_date: { type: 'date' },
    buyer_tax_id: { inputmode: 'numeric', maxlength: '8' },
    seller_tax_id: { inputmode: 'numeric', maxlength: '8' },
    sales_amount: { inputmode: 'decimal' },
    tax_amount: { inputmode: 'decimal' },
    total_amount: { inputmode: 'decimal' },
    quantity: { inputmode: 'decimal' },
    unit_price: { inputmode: 'decimal' },
    line_amount: { inputmode: 'decimal' },
  };
  // 比對規則（同 API）：數字去逗號、空白與尾端 0；字軌、號碼、統編去空白與連字號並轉大寫
  const NUMBER_FIELDS = new Set(['sales_amount', 'tax_amount', 'total_amount', 'quantity', 'unit_price', 'line_amount']);
  const CODE_FIELDS = new Set(['invoice_track', 'invoice_number', 'seller_tax_id', 'buyer_tax_id']);
  // 空白字元集合：與 API app/utils/invoice_format.py 的 WHITESPACE 相同（明列，不依賴各語言的 \s 定義）
  const SPACE_CHARS = '\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff';
  const EDGE_SPACES = new RegExp('^[' + SPACE_CHARS + ']+|[' + SPACE_CHARS + ']+$', 'g');
  const NUMBER_NOISE = new RegExp('[' + SPACE_CHARS + ',，]', 'g');
  const CODE_NOISE = new RegExp('[' + SPACE_CHARS + '-]', 'g');
  const TAX_TYPES = [
    ['', '請選擇課稅別'],
    ['taxable', '應稅'],
    ['zero_rated', '零稅率'],
    ['tax_exempt', '免稅'],
  ];
  const STATUS_LABELS = { pending_department_approval: '待單位核准' };
  // API 提醒的欄位 → 畫面上的輸入欄位
  const WARNING_TARGETS = { tax_period: 'invoice_date' };
  // 欄位格式與送出前的資料整理放在 invoice-field-rules.js（純函式，格式須與 API 相同），這裡與格式提示共用
  const Rules = window.InvoiceFieldRules;
  const AMOUNT_RE = Rules.AMOUNT_RE;
  const QUANTITY_RE = Rules.QUANTITY_RE;
  const MAX_TEXT = 200;
  const MAX_CHANGES = 500;
  const MAX_UPLOAD_SIDE = 2000;
  const MAX_UPLOAD_BYTES = 3.8 * 1024 * 1024;
  const MAX_SOURCE_IMAGE_BYTES = 10 * 1024 * 1024; // 選取的原始影像（辨識前會縮圖）
  const MAX_PDF_BYTES = 4 * 1024 * 1024; // PDF 原檔上傳，與 API 上限相同
  const MAX_ITEMS = 50;
  const HISTORY_KEY = 'ig-mobile-uploads';

  const ZONES = [
    ['發票字軌／號碼', 45, 8, 215, 43],
    ['三聯式／期別', 288, 5, 446, 65],
    ['買受人', 49, 72, 384, 25],
    ['買受人統編', 159, 100, 274, 34],
    ['開立日期', 445, 99, 309, 37],
    ['品名', 55, 169, 238, 211],
    ['數量', 293, 169, 89, 211],
    ['單價', 382, 169, 96, 211],
    ['明細金額', 478, 169, 170, 211],
    ['備註', 648, 169, 266, 103],
    ['銷售額合計', 55, 380, 593, 35],
    ['課稅別／稅額', 55, 415, 593, 45],
    ['總計', 55, 460, 593, 34],
    ['國字大寫', 55, 494, 593, 40],
    ['銷貨人章／統編', 648, 272, 266, 262],
  ];

  const REFERENCE_RATIO = 969 / 595;

  // 狀態管理
  // 影像：{ image: dataUrl, originalImage: dataUrl, rotation, name }；PDF：{ isPdf: true, file, url（object URL）, rotation: 0, name }
  let currentImage = null;
  let currentRecognition = null; // API 辨識回應（顯示於 AI 回傳 JSON）
  // 核對中的欄位值；items 每列有 row_id 與 source_line_no（對應 AI 明細序號，新增的明細為 null）
  let currentDraft = null;
  let currentPayload = null; // 核對完成、準備查重與送出的內容
  let aiItems = {}; // AI 辨識明細：line_no → 明細
  let committed = new Map(); // 各欄位最後一次記入修改紀錄的值
  let editLog = []; // 修改紀錄（依時間順序）：{ scope, rowId, field, old, new }
  let nextRowId = 1;
  let rotationBusy = false;
  let recognizing = false;
  let imageVersion = 0; // 每次換檔 +1；進行中的辨識若版本不同即丟棄結果
  let isDuplicateChecked = false;
  let isDuplicate = false;
  // 「上傳者確認」後 API 回報的必填缺漏：key（見 InvoiceFieldRules.headerKey／itemKey）→ 缺漏說明；
  // 初次載入與輸入期間不會有內容。unmapped 是畫面上找不到欄位、只列在摘要的缺漏。
  let missingState = new Map();
  let missingUnmapped = [];
  let confirmingRequired = false; // 必填檢核進行中（防止重複點擊）

  // 相機狀態
  let cameraStream = null;
  let cameraToken = 0;
  let cameraTimer = null;
  let cameraResize = null;
  let composition = 'landscape'; // 'landscape' | 'portrait'
  let stableFrames = 0;

  // DOM 輔助
  const $ = (selector) => document.querySelector(selector);

  function notify(msg) {
    alert(msg);
  }

  // =========================================================================
  // 邊緣偵測與外框對齊演算法 (Sobel Edge + Side Fitting)
  // =========================================================================
  function makeEdges(img) {
    const w = img.width;
    const h = img.height;
    const n = w * h;
    const d = img.data;
    const g = new Float32Array(n);
    const gx = new Float32Array(n);
    const gy = new Float32Array(n);

    for (let i = 0; i < n; i++) {
      g[i] = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2];
    }

    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const p = y * w + x;
        const a = p - w;
        const b = p + w;
        gx[p] = (-g[a - 1] + g[a + 1] - 2 * g[p - 1] + 2 * g[p + 1] - g[b - 1] + g[b + 1]) / 4;
        gy[p] = (-g[a - 1] - 2 * g[a] - g[a + 1] + g[b - 1] + 2 * g[b] + g[b + 1]) / 4;
      }
    }
    return { w, h, gx, gy };
  }

  function fitSide(ed, f, side) {
    const horizontal = side === 'top' || side === 'bottom';
    const length = horizontal ? f.w : f.h;
    const normalBase =
      side === 'top'
        ? f.y
        : side === 'bottom'
          ? f.y + f.h
          : side === 'left'
            ? f.x
            : f.x + f.w;
    const tangentBase = horizontal ? f.x : f.y;
    const radius = Math.max(4, Math.min(f.w, f.h) * 0.12);
    const step = Math.max(1, radius / 12);
    let best = null;

    for (let slopeIndex = -4; slopeIndex <= 4; slopeIndex++) {
      const slope = slopeIndex * 0.035;
      for (let offset = -radius; offset <= radius + 0.01; offset += step) {
        let hits = 0;
        let strength = 0;
        const samples = 26;

        for (let t = 0; t < samples; t++) {
          const fraction = 0.08 + (0.84 * t) / (samples - 1);
          const tangent = tangentBase + fraction * length;
          const normal = normalBase + offset + slope * (fraction - 0.5) * length;
          let local = 0;

          for (let n = -1; n <= 1; n++) {
            const x = Math.round(horizontal ? tangent : normal + n);
            const y = Math.round(horizontal ? normal + n : tangent);
            if (x < 1 || y < 1 || x >= ed.w - 1 || y >= ed.h - 1) continue;
            const p = y * ed.w + x;
            const gn = Math.abs(horizontal ? ed.gy[p] : ed.gx[p]);
            const gt = Math.abs(horizontal ? ed.gx[p] : ed.gy[p]);
            if (gn > gt * 1.4) local = Math.max(local, gn);
          }
          if (local >= 4.5) {
            hits++;
            strength += Math.min(local, 50) / 50;
          }
        }
        const coverage = hits / samples;
        const merit =
          coverage * 0.83 +
          (strength / samples) * 0.17 -
          (Math.abs(offset) / radius) * 0.025 -
          Math.abs(slope) * 0.03;
        if (!best || merit > best.merit) {
          best = { coverage, offset, slope, merit };
        }
      }
    }
    return best;
  }

  function assessBorder(ed, f) {
    const names = ['top', 'right', 'bottom', 'left'];
    const sides = {};
    names.forEach((n) => {
      sides[n] = fitSide(ed, f, n);
    });

    const count = names.filter((n) => sides[n] && sides[n].coverage >= 0.62).length;
    const scale = Math.min(f.w, f.h);
    const maxOffset = Math.max(...names.map((n) => Math.abs(sides[n].offset)));
    const maxSlope = Math.max(...names.map((n) => Math.abs(sides[n].slope)));

    let ok = count === 4 && maxOffset <= scale * 0.055 && maxSlope <= 0.0875;
    if (
      Math.abs(sides.top.slope - sides.bottom.slope) > 0.105 ||
      Math.abs(sides.left.slope - sides.right.slope) > 0.105
    ) {
      ok = false;
    }

    let msg = '';
    if (count < 4) msg = '外邊框不夠清楚，請保留四角並避開反光';
    else if (maxSlope > 0.0875) msg = '請把手機擺正，與發票紙面平行';
    else if (maxOffset > scale * 0.055) {
      const width = f.w + sides.right.offset - sides.left.offset;
      const height = f.h + sides.bottom.offset - sides.top.offset;
      if (width < f.w * 0.92 || height < f.h * 0.92) msg = '發票偏小，請靠近一些';
      else if (width > f.w * 1.08 || height > f.h * 1.08) msg = '發票偏大，請遠離一些';
      else msg = '請平移手機，讓發票外邊框對齊拍攝框';
    } else {
      msg = ok ? '外框已對齊，請保持穩定' : '請讓四角接近框線，手機與紙面平行';
    }

    return { ok, message: msg, count, sides };
  }

  // =========================================================================
  // 相機對齊取景框佈局與採樣
  // =========================================================================
  function referenceSVG() {
    return (
      '<svg id="fieldSvg" viewBox="0 0 969 595" preserveAspectRatio="none">' +
      '<image id="ghostRef" href="/static/img/reference_invoice.jpg" x="0" y="0" width="969" height="595" opacity="0"/>' +
      ZONES.map(function (z) {
        const x = z[1];
        const y = z[2];
        const w = z[3];
        const h = z[4];
        return (
          '<g class="zone">' +
          '<rect x="' +
          x +
          '" y="' +
          y +
          '" width="' +
          w +
          '" height="' +
          h +
          '" class="zoneBox"/>' +
          '<rect x="' +
          (x + 2) +
          '" y="' +
          (y + 2) +
          '" width="' +
          Math.min(w - 4, z[0].length * 11 + 10) +
          '" height="18" rx="3" fill="#071323b0"/>' +
          '<text x="' +
          (x + 5) +
          '" y="' +
          (y + 15) +
          '" fill="#e0efff" font-size="12" font-family="sans-serif">' +
          z[0] +
          '</text></g>'
        );
      }).join('') +
      '</svg>'
    );
  }

  function fitGuide() {
    const stage = $('#cameraStage');
    const g = $('#alignGuide');
    if (!stage || !g) return;

    const w = stage.clientWidth;
    const h = stage.clientHeight;
    const isWide = w > h;
    const portrait = composition === 'portrait';
    const ratio = portrait ? 1 / REFERENCE_RATIO : REFERENCE_RATIO;

    const left = isWide ? 88 : 12;
    const right = isWide ? 88 : 12;
    const top = isWide ? 8 : 112;
    const bottom = isWide ? 8 : 150;

    const aw = Math.max(100, w - left - right);
    const ah = Math.max(100, h - top - bottom);
    const gw = Math.min(aw, ah * ratio);
    const gh = gw / ratio;
    const x = left + (aw - gw) / 2;
    const y = top + (ah - gh) / 2;

    g.style.width = gw + 'px';
    g.style.height = gh + 'px';
    g.style.left = x + 'px';
    g.style.top = y + 'px';
    g.dataset.x = x;
    g.dataset.y = y;
    g.dataset.w = gw;
    g.dataset.h = gh;

    const svg = $('#fieldSvg');
    if (svg) {
      if (portrait) {
        svg.style.width = gh + 'px';
        svg.style.height = gw + 'px';
        svg.style.transformOrigin = '0 0';
        svg.style.transform = 'translate(' + gw + 'px,0) rotate(90deg)';
      } else {
        svg.style.width = '100%';
        svg.style.height = '100%';
        svg.style.transform = 'none';
      }
    }

    if ($('#modeL')) $('#modeL').className = portrait ? '' : 'selected';
    if ($('#modeP')) $('#modeP').className = portrait ? 'selected' : '';
    const overlay = $('#cameraOverlay');
    if (overlay) overlay.classList.toggle('wide', isWide);
    stableFrames = 0;
    g.style.setProperty('--align', '#ff6872');
  }

  function sampleAlignment(c, ctx) {
    const v = $('#liveCamera');
    const stage = $('#cameraStage');
    const g = $('#alignGuide');
    if (!v || !v.videoWidth || !g) return;

    try {
      const sw = stage.clientWidth;
      const sh = stage.clientHeight;
      const k = Math.min(1, 520 / sw, 520 / sh);
      c.width = Math.round(sw * k);
      c.height = Math.round(sh * k);
      const cover = Math.max(sw / v.videoWidth, sh / v.videoHeight);
      const vw = v.videoWidth * cover;
      const vh = v.videoHeight * cover;
      ctx.drawImage(v, ((sw - vw) / 2) * k, ((sh - vh) / 2) * k, vw * k, vh * k);

      const ed = makeEdges(ctx.getImageData(0, 0, c.width, c.height));
      const f = {
        x: +g.dataset.x * k,
        y: +g.dataset.y * k,
        w: +g.dataset.w * k,
        h: +g.dataset.h * k,
      };
      const r = assessBorder(ed, f);
      stableFrames = r.ok ? stableFrames + 1 : 0;
      const green = stableFrames >= 3;
      g.style.setProperty('--align', green ? '#49edab' : '#ff6872');

      const statusEl = $('#alignStatus');
      if (statusEl) {
        statusEl.style.color = green ? '#76ffca' : '#ffb5b9';
        statusEl.textContent = green
          ? '● 外框已對齊，可以拍攝'
          : r.ok
            ? '● 外框接近，請保持穩定'
            : '● ' + r.message;
      }
      const matchInfo = $('#matchInfo');
      if (matchInfo) {
        matchInfo.textContent = '已找到 ' + r.count + '/4 邊 · 內部欄位不參與判斷';
      }
    } catch {
      stableFrames = 0;
      g.style.setProperty('--align', '#ff6872');
      const statusEl = $('#alignStatus');
      if (statusEl) statusEl.textContent = '無法確認外框，請人工檢查後拍攝';
    }
  }

  function stopCamera() {
    cameraToken++;
    if (cameraTimer) {
      clearInterval(cameraTimer);
      cameraTimer = null;
    }
    if (cameraResize) {
      window.removeEventListener('resize', cameraResize);
      cameraResize = null;
    }
    if (cameraStream) {
      cameraStream.getTracks().forEach((t) => t.stop());
      cameraStream = null;
    }
    const o = $('#cameraOverlay');
    if (o) o.remove();
    document.body.style.overflow = '';
  }

  async function openCamera() {
    stopCamera();
    const token = cameraToken;
    const o = document.createElement('div');
    o.id = 'cameraOverlay';
    o.innerHTML =
      '<div id="cameraStage"><video id="liveCamera" autoplay muted playsinline></video>' +
      '<div id="alignGuide">' +
      referenceSVG() +
      '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i></div></div>' +
      '<div class="cameraTop"><b class="cameraTitle">只需對齊發票外框</b>' +
      '<div class="camControls">' +
      '<button type="button" id="modeL">橫向</button>' +
      '<button type="button" id="modeP">直向</button>' +
      '<button type="button" id="labelsToggle">欄位：開</button>' +
      '<button type="button" id="referenceToggle">參考圖</button>' +
      '<button type="button" id="cameraHelp">說明</button>' +
      '<button type="button" id="fullCamera">全螢幕</button>' +
      '<button type="button" id="cancelCamera">取消</button>' +
      '</div></div>' +
      '<div class="cameraBottom"><div class="feedback">' +
      '<div id="alignStatus">正在請求相機權限…</div>' +
      '<small id="matchInfo">僅判斷整張發票四邊，欄位僅供參考</small></div>' +
      '<button type="button" id="shutter" disabled aria-label="拍攝發票">●</button>' +
      '<small class="manualNote">只看外框，不必逐條對齊欄位。<br>紅框仍可人工確認拍攝。</small>' +
      '<div id="cameraError" style="display:none"></div></div>';

    document.body.appendChild(o);
    document.body.style.overflow = 'hidden';

    $('#cancelCamera').onclick = stopCamera;
    $('#modeL').onclick = function () {
      composition = 'landscape';
      fitGuide();
    };
    $('#modeP').onclick = function () {
      composition = 'portrait';
      fitGuide();
    };
    $('#labelsToggle').onclick = function () {
      const off = $('#alignGuide').classList.toggle('noLabels');
      this.textContent = off ? '欄位：關' : '欄位：開';
    };
    $('#referenceToggle').onclick = function () {
      const el = $('#ghostRef');
      if (el) {
        const show = el.getAttribute('opacity') === '0';
        el.setAttribute('opacity', show ? '0.26' : '0');
        this.classList.toggle('selected', show);
      }
    };
    $('#cameraHelp').onclick = function () {
      alert(
        '【外框對齊指南】\n' +
          '1. 只需對齊整張紙的外邊框。內部欄位是位置參考，不影響紅綠燈。\n' +
          '2. 綠框表示四邊位置及角度接近拍攝框，並連續穩定。\n' +
          '3. 輸出保留完整相機影像，不裁切。\n' +
          '4. 拍照後可於預覽頁自由旋轉方向（左轉、右轉 90°）及還原原圖。'
      );
    };

    function full() {
      if (o.requestFullscreen) {
        const p = o.requestFullscreen();
        if (p && p.catch) p.catch(() => notify('目前使用滿版取景'));
      }
    }
    $('#fullCamera').onclick = full;

    $('#shutter').onclick = function () {
      const v = $('#liveCamera');
      if (!v || !v.videoWidth) return;
      const c = document.createElement('canvas');
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext('2d').drawImage(v, 0, 0);
      const url = c.toDataURL('image/jpeg', 0.9);
      setImage({
        image: url,
        originalImage: url,
        rotation: 0,
        name: '相機拍攝_' + Date.now() + '.jpg',
      });
      stopCamera();
      showStep('step-preview');
    };

    cameraResize = fitGuide;
    window.addEventListener('resize', cameraResize);
    fitGuide();

    try {
      if (!window.isSecureContext) throw { name: 'InsecureContext' };
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw { name: 'Unsupported' };
      }
      const st = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1440 },
        },
      });
      if (token !== cameraToken) {
        st.getTracks().forEach((t) => t.stop());
        return;
      }
      cameraStream = st;
      const v = $('#liveCamera');
      v.srcObject = st;
      v.onloadedmetadata = function () {
        if (token !== cameraToken) return;
        $('#shutter').disabled = false;
        fitGuide();
      };
      await v.play();
      fitGuide();
      const c = document.createElement('canvas');
      const ctx = c.getContext('2d', { willReadFrequently: true });
      cameraTimer = setInterval(function () {
        if (token === cameraToken) sampleAlignment(c, ctx);
      }, 350);
    } catch (e) {
      if (token !== cameraToken) return;
      if (cameraStream) {
        cameraStream.getTracks().forEach((t) => t.stop());
        cameraStream = null;
      }
      const alignStatus = $('#alignStatus');
      if (alignStatus) alignStatus.textContent = '無法啟動相機';
      const camErr = $('#cameraError');
      if (camErr) {
        camErr.style.display = 'block';
        camErr.textContent =
          e.name === 'NotAllowedError'
            ? '請允許相機權限，並以獨立 Chrome／Safari 頁面開啟。'
            : e.name === 'InsecureContext'
              ? '手機相機請使用 HTTPS；電腦開發可用 localhost。'
              : e.name === 'NotFoundError'
                ? '找不到相機設備。'
                : e.name === 'NotReadableError'
                  ? '相機可能被其他應用程式占用。'
                  : '相機啟動失敗：' + (e.name || e.message);
      }
    }
  }

  // =========================================================================
  // 影像旋轉核心 (Canvas 2D Rotation)
  // =========================================================================
  function rotatePhoto(delta) {
    // PDF 以原檔辨識，不旋轉
    if (rotationBusy || !currentImage || currentImage.isPdf) return;

    const original = currentImage.originalImage || currentImage.image;
    const angle =
      delta === null ? 0 : ((currentImage.rotation || 0) + delta + 360) % 360;

    currentImage.originalImage = original;

    if (angle === 0) {
      currentImage.image = original;
      currentImage.rotation = 0;
      updatePreviewUI();
      return;
    }

    rotationBusy = true;
    updateRotateButtonsState();

    // 旋轉期間若換了檔案，結果不寫回新檔案
    const target = currentImage;
    const im = new Image();
    im.onload = function () {
      if (target !== currentImage) return;
      try {
        const c = document.createElement('canvas');
        const swap = angle === 90 || angle === 270;
        c.width = swap ? im.naturalHeight : im.naturalWidth;
        c.height = swap ? im.naturalWidth : im.naturalHeight;
        const ctx = c.getContext('2d');
        ctx.translate(c.width / 2, c.height / 2);
        ctx.rotate((angle * Math.PI) / 180);
        ctx.drawImage(im, -im.naturalWidth / 2, -im.naturalHeight / 2);

        currentImage.image = c.toDataURL('image/jpeg', 0.9);
        currentImage.rotation = angle;
        rotationBusy = false;
        updatePreviewUI();
      } catch (err) {
        rotationBusy = false;
        updatePreviewUI();
        notify('旋轉失敗，原照片未變更：' + err.message);
      }
    };
    im.onerror = function () {
      if (target !== currentImage) return;
      rotationBusy = false;
      updatePreviewUI();
      notify('無法讀取圖片');
    };
    im.src = original;
  }

  function updateRotateButtonsState() {
    const rotStatus = $('#rotation-angle-text');
    if (rotStatus) {
      rotStatus.textContent = rotationBusy
        ? '正在產生旋轉後影像…'
        : '目前方向：' + (currentImage.rotation || 0) + '°（順時針） · 後續辨識使用這個版本';
    }
    const btns = document.querySelectorAll('.rotate-toolbar button');
    btns.forEach((b) => {
      b.disabled = rotationBusy;
    });
  }

  function updatePreviewUI() {
    if (!currentImage) return;
    updateRotateButtonsState();
    const isPdf = Boolean(currentImage.isPdf);
    // 影像以 <img> 預覽；PDF 以 iframe 顯示原檔（電腦上傳頁），並提供另開分頁的連結
    ['#preview-img', '#check-preview-img'].forEach((selector) => {
      const img = $(selector);
      if (!img) return;
      img.hidden = isPdf;
      if (!isPdf) img.src = currentImage.image;
    });
    ['#preview-pdf', '#check-preview-pdf'].forEach((selector) => {
      const frame = $(selector);
      if (!frame) return;
      frame.hidden = !isPdf;
      if (isPdf && frame.src !== currentImage.url) frame.src = currentImage.url;
      if (!isPdf) frame.removeAttribute('src');
    });
    const link = $('#preview-pdf-link');
    if (link) {
      link.hidden = !isPdf;
      if (isPdf) link.href = currentImage.url;
    }
    const rotateControls = $('#rotate-controls');
    if (rotateControls) rotateControls.hidden = isPdf;
  }

  function setImage(imgObj) {
    releaseImage();
    currentImage = imgObj;
    updatePreviewUI();
  }

  // 放開目前的影像／PDF（PDF 預覽用的 object URL 需釋放）；版本號 +1，讓進行中的辨識與旋轉結果作廢
  function releaseImage() {
    if (currentImage && currentImage.url) URL.revokeObjectURL(currentImage.url);
    currentImage = null;
    imageVersion += 1;
    rotationBusy = false;
    resetRecognizeButton();
  }

  // =========================================================================
  // 手機步驟切換與畫面管理
  // =========================================================================
  function showStep(stepId) {
    document.querySelectorAll('.mobile-step-section').forEach((el) => {
      el.hidden = true;
    });
    const target = $('#' + stepId);
    if (target) {
      target.hidden = false;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }


  // =========================================================================
  // 共用：DOM 建立、API 呼叫與本機上傳紀錄
  // =========================================================================
  function make(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([name, value]) => node.setAttribute(name, value));
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function setText(selector, text) {
    const node = $(selector);
    if (node) node.textContent = text;
  }

  // Session 失效時本站回 303 導向登入頁；fetch 會跟著轉址（next 是 POST 端點），
  // 改由頁面整頁前往登入，登入後回到目前這一頁（手機拍照頁或電腦上傳頁）
  function isLoginRedirect(res) {
    if (res.redirected && new URL(res.url).pathname === '/login') {
      window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
      return true;
    }
    return false;
  }

  async function readJson(res) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }

  function errorOf(data) {
    const error = data && data.error;
    return error && typeof error === 'object' ? error : {};
  }

  function errorMessage(data, fallback) {
    const message = errorOf(data).message;
    return typeof message === 'string' && message ? message : fallback;
  }

  // isCurrent：回應抵達時這個請求是否仍有效（例如辨識期間已換檔）；無效時直接回 null，
  // 不做登入轉址等任何副作用
  async function sendRequest(url, options, isCurrent) {
    const headers = Object.assign({ Accept: 'application/json' }, options.headers);
    const res = await fetch(url, Object.assign({ method: 'POST' }, options, { headers }));
    if (isCurrent && !isCurrent()) return null;
    if (isLoginRedirect(res)) return null;
    return { ok: res.ok, data: await readJson(res) };
  }

  function postJson(url, payload) {
    return sendRequest(url, {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  function readHistory() {
    try {
      const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      return Array.isArray(list) ? list : [];
    } catch {
      return [];
    }
  }

  function saveHistory(entry) {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify([entry].concat(readHistory()).slice(0, 30)));
    } catch {
      // 無法寫入本機紀錄（例如私密瀏覽）不影響上傳結果
    }
  }

  // =========================================================================
  // 比對規則與修改紀錄（與 API _canonical_value 相同）
  // =========================================================================
  // 數字只以字串處理（去前導 0 與小數尾端 0），不轉成浮點數，任何位數都精確
  function canonicalValue(field, value) {
    if (value === null || value === undefined) return null;
    const text = String(value).replace(EDGE_SPACES, '');
    if (!text) return null;
    if (NUMBER_FIELDS.has(field)) {
      const cleaned = text.replace(NUMBER_NOISE, '');
      if (!/^[0-9]+(\.[0-9]+)?$/.test(cleaned)) return cleaned;
      const [intPart, fracPart = ''] = cleaned.split('.');
      const integer = intPart.replace(/^0+(?=[0-9])/, '');
      const fraction = fracPart.replace(/0+$/, '');
      return fraction ? integer + '.' + fraction : integer;
    }
    if (CODE_FIELDS.has(field)) return text.replace(CODE_NOISE, '').toUpperCase();
    return text;
  }

  function displayValue(field, value) {
    if (value === null || value === undefined || value === '') return '（空白）';
    if (field === 'tax_type') {
      const match = TAX_TYPES.find(([code]) => code === value);
      return match ? match[1] : value;
    }
    return String(value);
  }

  function aiHeaderValue(field) {
    return canonicalValue(field, (currentRecognition.invoice || {})[field]);
  }

  function aiItemValue(sourceLineNo, field) {
    const item = sourceLineNo ? aiItems[sourceLineNo] : null;
    return item ? canonicalValue(field, item[field]) : null;
  }

  function editKey(scope, rowId, field) {
    return scope === 'header' ? 'h:' + field : 'r:' + rowId + ':' + field;
  }

  function findRow(rowId) {
    return currentDraft.items.find((row) => row.row_id === rowId);
  }

  function baselineFor(scope, rowId, field) {
    if (scope === 'header') return aiHeaderValue(field);
    const row = findRow(rowId);
    return row ? aiItemValue(row.source_line_no, field) : null;
  }

  // 欄位值確定（離開欄位或選擇）時呼叫：與上次記錄的值不同才記一筆
  function recordEdit(scope, rowId, field, value) {
    const key = editKey(scope, rowId, field);
    const next = canonicalValue(field, value);
    const prev = committed.has(key) ? committed.get(key) : baselineFor(scope, rowId, field);
    if (prev === next) return;
    editLog.push({ scope, rowId, field, old: prev, new: next });
    committed.set(key, next);
  }

  // =========================================================================
  // 辨識：縮圖後上傳，取得 API 的辨識 JSON
  // =========================================================================
  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = () => reject(new Error('image'));
      im.src = src;
    });
  }

  function canvasBlob(canvas, quality) {
    return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
  }

  async function prepareUploadBlob(src) {
    const im = await loadImage(src);
    const scale = Math.min(1, MAX_UPLOAD_SIDE / Math.max(im.naturalWidth, im.naturalHeight));
    const c = document.createElement('canvas');
    c.width = Math.round(im.naturalWidth * scale);
    c.height = Math.round(im.naturalHeight * scale);
    const ctx = c.getContext('2d');
    // PNG 透明背景轉為白底
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(im, 0, 0, c.width, c.height);
    for (const quality of [0.85, 0.7, 0.55]) {
      const blob = await canvasBlob(c, quality);
      if (blob && blob.size <= MAX_UPLOAD_BYTES) return blob;
    }
    throw new Error('too-large');
  }

  function uploadName(name) {
    return String(name || 'mobile_capture').replace(/\.[^.]*$/, '') + '.jpg';
  }

  function newRow(sourceLineNo, values) {
    const row = { row_id: nextRowId++, source_line_no: sourceLineNo };
    ITEM_FIELDS.forEach((field) => {
      row[field] = (values && values[field]) || '';
    });
    return row;
  }

  function startReview(result) {
    currentRecognition = result;
    const invoice = result.invoice || {};
    aiItems = {};
    (invoice.items || []).forEach((item) => {
      aiItems[item.line_no] = item;
    });
    committed = new Map();
    editLog = [];
    currentPayload = null;
    missingState = new Map();
    missingUnmapped = [];
    currentDraft = { items: Object.values(aiItems).map((item) => newRow(item.line_no, item)) };
    HEADER_FIELDS.forEach((field) => {
      currentDraft[field] = invoice[field] || '';
    });
    if (!currentDraft.items.length) currentDraft.items.push(newRow(null));
  }

  async function recognizeCurrentImage(button) {
    if (!currentImage || recognizing) return;
    // 辨識期間若換了檔案（重新選擇、重拍），舊的縮圖與回應一律丟棄，不套用到新檔案
    const version = imageVersion;
    const image = currentImage;
    const stale = () => version !== imageVersion;
    recognizing = true;
    button.disabled = true;
    button.textContent = 'AI 辨識中…（約 10～20 秒）';
    try {
      const form = new FormData();
      if (image.isPdf) {
        // PDF 原檔上傳（選檔時已確認 4 MB 以內）
        form.append('file', image.file, image.name);
      } else {
        const blob = await prepareUploadBlob(image.image);
        if (stale()) return;
        form.append('file', blob, uploadName(image.name));
      }
      const result = await sendRequest('/invoices/mobile-recognize', { body: form }, () => !stale());
      if (stale() || !result) return;
      if (!result.ok) {
        notify(errorMessage(result.data, '辨識失敗，請稍後再試'));
        return;
      }
      startReview(result.data);
      populateFields();
      showStep('step-fields');
    } catch (err) {
      if (stale()) return;
      notify(
        err && err.message === 'too-large'
          ? '影像過大，請重新拍攝'
          : err && err.message === 'image'
            ? '無法讀取影像，請重新拍攝或選取'
            : '無法連線，請確認網路後再試'
      );
    } finally {
      // 已換檔時，按鈕狀態已由 releaseImage 重設，這裡不再更動
      if (!stale()) resetRecognizeButton();
    }
  }

  function resetRecognizeButton() {
    recognizing = false;
    const button = $('#btn-recognize');
    if (button) {
      button.disabled = false;
      button.textContent = '辨識內容';
    }
  }

  // =========================================================================
  // 核對修正：依辨識結果產生欄位；與 AI 值不同的欄位即時標記「已修改」
  // =========================================================================
  function warningsFor(key) {
    const warnings = (currentRecognition && currentRecognition.warnings) || [];
    return warnings.filter((w) => (WARNING_TARGETS[w.field] || w.field) === key);
  }

  function markHeaderField(field) {
    const input = $('#f-' + field);
    if (!input) return;
    const group = input.closest('.field-group');
    const ai = aiHeaderValue(field);
    const modified = canonicalValue(field, input.value) !== ai;
    group.classList.toggle('is-modified', modified);
    const note = group.querySelector('.field-modified');
    note.hidden = !modified;
    note.textContent = modified ? '已修改｜AI 辨識：' + displayValue(field, ai) : '';
  }

  function headerControl(field) {
    let control;
    if (field === 'tax_type') {
      control = make('select', { name: field });
      TAX_TYPES.forEach(([value, label]) => control.append(make('option', { value }, label)));
    } else {
      const attrs = Object.assign({ type: 'text', name: field, autocomplete: 'off', maxlength: String(MAX_TEXT) }, INPUT_ATTRS[field]);
      control = make('input', attrs);
    }
    control.value = currentDraft[field] || '';
    control.id = 'f-' + field;
    control.dataset.field = field;
    control.addEventListener('input', () => markHeaderField(field));
    control.addEventListener('change', () => {
      recordEdit('header', null, field, control.value);
      markHeaderField(field);
    });
    return control;
  }

  function requiredMark() {
    return make('span', { class: 'field-required' }, '*必填');
  }

  const HINT_ICONS = { ok: '✓', compatible: 'ℹ', error: '✕' };

  // 欄位格式提示：只在離開欄位時判斷（不逐字顯示、不呼叫 API）；沒有明確規則或尚未填寫時保持中性
  function showHint(hint, field, value) {
    const result = Rules.evaluateField(field, value);
    hint.textContent = '';
    hint.className = 'field-hint';
    if (result.state === 'none' || result.state === 'empty') {
      hint.hidden = true;
      return;
    }
    hint.classList.add('field-hint--' + result.state);
    hint.append(make('span', { class: 'field-hint__icon', 'aria-hidden': 'true' }, HINT_ICONS[result.state]));
    hint.append(document.createTextNode(result.message));
    hint.hidden = false;
  }

  // 輸入框下方的格式提示，以及補齊必填後清除該欄位的缺漏提示（不呼叫 API）
  function attachFeedback(control, field, hintId, missingKeys) {
    const hint = make('small', { class: 'field-hint', id: hintId, 'aria-live': 'polite', hidden: '' });
    control.after(hint);
    control.setAttribute('aria-describedby', hintId);
    const clearIfFilled = () => {
      if (control.value.trim() === '') return;
      const present = missingKeys.filter((key) => missingState.has(key));
      if (!present.length) return;
      present.forEach((key) => missingState.delete(key));
      renderMissing();
    };
    control.addEventListener('input', () => {
      hint.hidden = true; // 修改中先收起舊提示，離開欄位時再重新判斷
      clearIfFilled();
    });
    control.addEventListener('change', clearIfFilled);
    control.addEventListener('blur', () => showHint(hint, field, control.value));
  }

  function headerField(field) {
    const group = make('div', { class: 'field-group' });
    const control = headerControl(field);
    const label = make('label', { for: control.id }, FIELD_LABELS[field]);
    if (Rules.REQUIRED_HEADER_FIELDS.includes(field)) {
      label.append(requiredMark());
      control.setAttribute('aria-required', 'true');
    }
    group.append(label, control);
    attachFeedback(control, field, 'hint-' + control.id, [Rules.headerKey(field)]);
    group.append(make('small', { class: 'field-modified', hidden: '' }));
    warningsFor(field).forEach((w) => group.append(make('small', { class: 'field-warning' }, w.message)));
    return group;
  }

  function markItemRow(rowEl, row) {
    let modified = false;
    rowEl.querySelectorAll('[data-item-field]').forEach((input) => {
      const field = input.dataset.itemField;
      const ai = aiItemValue(row.source_line_no, field);
      const changed = canonicalValue(field, input.value) !== ai;
      input.classList.toggle('is-modified', Boolean(row.source_line_no) && changed);
      input.title = row.source_line_no && changed ? 'AI 辨識：' + displayValue(field, ai) : '';
      modified = modified || changed;
    });
    const isNew = !row.source_line_no;
    rowEl.classList.toggle('is-new', isNew);
    rowEl.classList.toggle('is-modified', !isNew && modified);
    const status = rowEl.querySelector('.item-row__status');
    status.textContent = isNew ? '新增（AI 未辨識）' : modified ? '已修改' : '';
    const note = rowEl.querySelector('.field-modified');
    const changes = isNew
      ? []
      : ITEM_FIELDS.filter((field) => {
          const input = rowEl.querySelector('[data-item-field="' + field + '"]');
          return canonicalValue(field, input.value) !== aiItemValue(row.source_line_no, field);
        });
    note.hidden = !changes.length;
    note.textContent = changes.length
      ? 'AI 辨識：' +
        changes.map((field) => FIELD_LABELS[field] + ' ' + displayValue(field, aiItemValue(row.source_line_no, field))).join('、')
      : '';
  }

  function renderDeletedItems() {
    const box = $('#deleted-items');
    if (!box) return;
    const kept = new Set(currentDraft.items.map((row) => row.source_line_no).filter(Boolean));
    const deleted = Object.values(aiItems).filter((item) => !kept.has(item.line_no));
    box.textContent = '';
    box.hidden = !deleted.length;
    deleted.forEach((item) => {
      box.append(
        make('small', { class: 'field-modified' }, '已刪除 AI 明細 ' + item.line_no + '：' + displayValue('item_name', item.item_name) + ' ' + displayValue('line_amount', item.line_amount))
      );
    });
  }

  function renderItems() {
    const box = $('#items-container');
    if (!box) return;
    box.textContent = '';
    currentDraft.items.forEach((row, index) => {
      const rowEl = make('div', { class: 'item-row', 'data-row-id': String(row.row_id) });
      const title = make('div', { class: 'item-row__title' }, '明細 ' + (index + 1) + ' ');
      title.append(make('span', { class: 'item-row__status' }));
      rowEl.append(title);
      ITEM_FIELDS.forEach((field) => {
        // 品名一整列、數量／單價／金額三欄上方加欄名，已有數值時仍看得出欄位；必填欄位標示 *必填
        const caption = (name) => {
          const node = make('span', { class: 'item-row__caption' }, FIELD_LABELS[name]);
          if (Rules.REQUIRED_ITEM_FIELDS.includes(name)) node.append(requiredMark());
          return node;
        };
        if (field === 'item_name') {
          const wide = caption(field);
          wide.classList.add('item-row__caption--wide');
          rowEl.append(wide);
        }
        if (field === 'quantity') {
          ITEM_FIELDS.slice(1).forEach((name) => rowEl.append(caption(name)));
        }
        const input = make(
          'input',
          Object.assign(
            {
              type: 'text',
              autocomplete: 'off',
              maxlength: String(MAX_TEXT),
              placeholder: FIELD_LABELS[field],
              'aria-label': '明細 ' + (index + 1) + ' ' + FIELD_LABELS[field],
              class: 'item-row__' + field,
            },
            INPUT_ATTRS[field]
          )
        );
        input.dataset.itemField = field;
        input.value = row[field] || '';
        if (Rules.REQUIRED_ITEM_FIELDS.includes(field)) input.setAttribute('aria-required', 'true');
        input.addEventListener('input', () => markItemRow(rowEl, row));
        input.addEventListener('change', () => {
          row[field] = input.value.trim();
          recordEdit('item', row.row_id, field, input.value);
          markItemRow(rowEl, row);
        });
        const cell = make('div', { class: 'item-row__cell item-row__cell--' + field });
        cell.append(input);
        rowEl.append(cell);
        attachFeedback(input, field, 'hint-r' + row.row_id + '-' + field, [
          Rules.itemKey(row.row_id, field),
          Rules.ITEMS_KEY,
        ]);
      });
      rowEl.append(make('small', { class: 'field-modified item-row__note', hidden: '' }));
      const remove = make('button', { type: 'button', class: 'btn btn--secondary item-row__remove' }, '刪除');
      remove.onclick = function () {
        collectDraft();
        currentDraft.items = currentDraft.items.filter((item) => item.row_id !== row.row_id);
        if (!currentDraft.items.length) currentDraft.items.push(newRow(null));
        renderItems();
      };
      rowEl.append(remove);
      box.append(rowEl);
      markItemRow(rowEl, row);
    });
    renderDeletedItems();
    renderMissing();
  }

  function itemsSection() {
    const section = make('div', { class: 'field-group items-section' });
    const sectionLabel = make('span', { class: 'items-section__label' }, '品名明細');
    sectionLabel.append(requiredMark());
    section.append(sectionLabel);
    warningsFor('items').forEach((w) => section.append(make('small', { class: 'field-warning' }, w.message)));
    section.append(make('div', { id: 'items-container' }), make('div', { id: 'deleted-items', hidden: '' }));
    const add = make('button', { type: 'button', class: 'btn btn--secondary' }, '新增明細');
    add.onclick = function () {
      collectDraft();
      if (currentDraft.items.length >= MAX_ITEMS) return notify('明細最多 ' + MAX_ITEMS + ' 筆');
      currentDraft.items.push(newRow(null));
      renderItems();
    };
    section.append(add);
    return section;
  }

  // =========================================================================
  // 「上傳者確認」後的必填缺漏顯示（初次載入與輸入期間不顯示；補齊後只在前端清除）
  // =========================================================================
  function missingElement(key) {
    const root = $('#fields-container');
    if (!root) return null;
    if (key === Rules.ITEMS_KEY) return root.querySelector('.items-section');
    if (key.startsWith('h:')) return root.querySelector('#f-' + key.slice(2));
    const match = /^i:(\d+):([a-z_]+)$/.exec(key);
    return match
      ? root.querySelector('[data-row-id="' + match[1] + '"] [data-item-field="' + match[2] + '"]')
      : null;
  }

  function requiredSummaryBox() {
    let box = $('#required-summary');
    if (!box) {
      box = make('div', { id: 'required-summary', class: 'required-summary', role: 'alert', hidden: '' });
      const container = $('#fields-container');
      if (container && container.parentNode) container.parentNode.insertBefore(box, container);
    }
    return box;
  }

  function renderMissing() {
    document.querySelectorAll('#fields-container .field-missing').forEach((node) => node.remove());
    document.querySelectorAll('#fields-container .is-missing').forEach((node) => {
      node.classList.remove('is-missing');
      node.removeAttribute('aria-invalid');
    });
    const names = [];
    missingState.forEach((target, key) => {
      const element = missingElement(key);
      if (!element) {
        missingState.delete(key); // 例如該筆明細已被刪除
        return;
      }
      names.push(target.summary);
      const message = make('small', { class: 'field-missing' }, target.text);
      element.classList.add('is-missing');
      if (key === Rules.ITEMS_KEY) {
        element.querySelector('.items-section__label').after(message);
      } else {
        element.setAttribute('aria-invalid', 'true');
        element.after(message);
      }
    });
    missingUnmapped.forEach((entry) => names.push(entry.summary));
    const box = requiredSummaryBox();
    box.textContent = '';
    box.classList.remove('required-summary--notice'); // 清掉檢核失敗時的說明
    if (!names.length) {
      box.hidden = true;
      return;
    }
    box.append(make('strong', {}, '尚缺 ' + names.length + ' 個必填欄位'));
    const list = make('ul');
    names.forEach((name) => list.append(make('li', {}, name)));
    box.append(list);
    box.hidden = false;
  }

  function clearMissing() {
    missingState = new Map();
    missingUnmapped = [];
    renderMissing();
  }

  function scrollToFirstMissing() {
    const first = $('#fields-container .is-missing');
    const target = first || requiredSummaryBox();
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    if (first && typeof first.focus === 'function' && first.matches('input, select')) {
      first.focus({ preventScroll: true });
    }
  }

  // API 回報缺漏：一次顯示全部；畫面上找不到欄位的缺漏仍列在摘要
  function showMissing(missing, rowIds, rowNumbers) {
    const plan = Rules.placeMissing(missing, rowIds, FIELD_LABELS, rowNumbers, (key) => Boolean(missingElement(key)));
    missingState = new Map(plan.targets.map((target) => [target.key, target]));
    missingUnmapped = plan.unmapped;
    renderMissing();
    scrollToFirstMissing();
  }

  // 必填檢核無法完成：上一次的缺漏結果已過期，一併清除（使用者填寫的內容不動），並說明資料尚未送出
  function showCheckFailure(message) {
    clearMissing();
    const box = requiredSummaryBox();
    box.textContent = '';
    box.classList.add('required-summary--notice');
    box.append(make('strong', {}, message));
    box.hidden = false;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    box.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
  }

  function renderRecognitionSummary() {
    const warnings = currentRecognition.warnings || [];
    setText(
      '#recognition-summary',
      (warnings.length ? 'AI 辨識完成，有 ' + warnings.length + ' 項需要核對：' : 'AI 辨識完成，請對照影像逐欄核對。') +
        '修改過的欄位會標示「已修改」，送出後一併標記給審核人員。'
    );
    const list = $('#recognition-warnings');
    if (list) {
      list.textContent = '';
      warnings.forEach((w) => list.append(make('li', {}, w.message)));
      list.hidden = !warnings.length;
    }
    setText('#ai-json', JSON.stringify(currentRecognition, null, 2));
  }

  function populateFields() {
    const container = $('#fields-container');
    if (!container || !currentDraft) return;
    container.textContent = '';
    const kind =
      currentRecognition.is_triplicate === true
        ? '三聯式統一發票'
        : currentRecognition.is_triplicate === false
          ? '非三聯式統一發票（請確認影像）'
          : '無法判斷（請確認影像）';
    container.append(make('p', { class: 'field-note' }, '發票聯式：' + kind));
    const pair = make('div', { class: 'field-pair' });
    pair.append(headerField('invoice_track'), headerField('invoice_number'));
    container.append(pair);
    HEADER_FIELDS.slice(2).forEach((field) => {
      if (field === 'sales_amount') container.append(itemsSection());
      container.append(headerField(field));
    });
    renderItems();
    HEADER_FIELDS.forEach(markHeaderField);
    renderRecognitionSummary();
    const ack = $('#uploaderAck');
    if (ack) ack.checked = false;
  }

  // 讀回畫面上的值；值與上次記錄不同的欄位補記一筆（例如未離開欄位就按按鈕）
  function collectDraft() {
    document.querySelectorAll('#fields-container [data-field]').forEach((input) => {
      const field = input.dataset.field;
      currentDraft[field] = input.value.trim();
      recordEdit('header', null, field, input.value);
    });
    document.querySelectorAll('#items-container [data-row-id]').forEach((rowEl) => {
      const row = findRow(Number(rowEl.dataset.rowId));
      if (!row) return;
      rowEl.querySelectorAll('[data-item-field]').forEach((input) => {
        const field = input.dataset.itemField;
        row[field] = input.value.trim();
        recordEdit('item', row.row_id, field, input.value);
      });
    });
  }

  function cleanNumber(value) {
    return Rules.cleanNumber(value);
  }

  // 檢查必要欄位與格式，組出 API 送出內容；回傳 { error } 或 { payload, rows }
  function buildPayload() {
    const d = currentDraft;
    const track = Rules.normalizeTrack(d.invoice_track);
    const number = Rules.normalizeNumber(d.invoice_number);
    if (!/^[A-Z]{2}$/.test(track)) return { error: '字軌需為 2 碼英文' };
    if (!/^\d{8}$/.test(number)) return { error: '號碼需為 8 碼數字' };
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d.invoice_date)) return { error: '請填寫發票日期' };
    const buyerTaxId = cleanNumber(d.buyer_tax_id);
    if (buyerTaxId && !/^\d{8}$/.test(buyerTaxId)) return { error: '買受人統一編號需為 8 碼數字' };
    const sellerTaxId = cleanNumber(d.seller_tax_id);
    if (!/^\d{8}$/.test(sellerTaxId)) return { error: '賣方統一編號需為 8 碼數字' };
    if (!d.tax_type) return { error: '請選擇課稅別' };
    const amounts = {};
    for (const field of AMOUNT_FIELDS) {
      amounts[field] = cleanNumber(d[field]);
      if (!AMOUNT_RE.test(amounts[field])) return { error: '請確認' + FIELD_LABELS[field] + '（數字，最多 2 位小數）' };
    }
    const items = [];
    const rows = [];
    for (const row of d.items) {
      if (!ITEM_FIELDS.some((field) => row[field])) continue;
      const line = items.length + 1;
      const lineAmount = cleanNumber(row.line_amount);
      const quantity = cleanNumber(row.quantity);
      const unitPrice = cleanNumber(row.unit_price);
      if (!row.item_name) return { error: '請填寫明細 ' + line + ' 的品名' };
      if (!AMOUNT_RE.test(lineAmount)) return { error: '請確認明細 ' + line + ' 的金額' };
      if ((quantity && !QUANTITY_RE.test(quantity)) || (unitPrice && !QUANTITY_RE.test(unitPrice))) {
        return { error: '請確認明細 ' + line + ' 的數量與單價（數字，最多 4 位小數）' };
      }
      rows.push(row);
      items.push({
        source_line_no: row.source_line_no,
        item_name: row.item_name,
        quantity: quantity || null,
        unit_price: unitPrice || null,
        line_amount: lineAmount,
      });
    }
    if (!items.length) return { error: '請至少填寫一筆品名明細' };
    // 修改紀錄：只送出仍在送出明細中的列，明細序號改為送出時的順序
    const lineOf = new Map(rows.map((row, i) => [row.row_id, i + 1]));
    const changes = editLog
      .filter((entry) => entry.scope === 'header' || lineOf.has(entry.rowId))
      .map((entry) => ({
        field_scope: entry.scope,
        line_no: entry.scope === 'header' ? null : lineOf.get(entry.rowId),
        field_name: entry.field,
        old_value: entry.old,
        new_value: entry.new,
      }));
    // 修改紀錄要完整保存（含中間修改），超過 API 上限時不壓縮、不刪減，請使用者重新辨識
    if (changes.length > MAX_CHANGES) {
      return {
        error: '修改次數已超過 ' + MAX_CHANGES + ' 次，無法完整保存修改紀錄；請重新拍攝辨識後再核對',
      };
    }
    return {
      rows,
      payload: Object.assign(
        {
          recognition_id: currentRecognition.recognition_id,
          invoice_track: track,
          invoice_number: number,
          invoice_date: d.invoice_date,
          seller_tax_id: sellerTaxId,
          seller_name: d.seller_name || null,
          buyer_tax_id: buyerTaxId || null,
          buyer_name: d.buyer_name || null,
          tax_type: d.tax_type,
          total_amount_zh: d.total_amount_zh || null,
          items,
          changes,
        },
        amounts
      ),
    };
  }

  // 必填欄位完整後，才進行原有的格式檢查，通過就進入查重與確認送出
  function continueAfterRequired() {
    const built = buildPayload();
    if (built.error) return notify(built.error);
    currentPayload = built.payload;
    setText('#sum-invoice-no', invoiceNoOf(currentPayload));
    setText('#sum-seller-tax-id', currentPayload.seller_tax_id);
    setText('#sum-sales-amount', currentPayload.sales_amount);
    setText('#sum-total-amount', currentPayload.total_amount);
    renderModifiedSummary(currentPayload);
    resetDuplicateState();
    showStep('step-confirm');
  }

  // 與 AI 辨識值不同的欄位（API 以相同規則寫入 invoice_field_reviews）
  function modifiedFields(payload) {
    const list = [];
    HEADER_FIELDS.forEach((field) => {
      const ai = aiHeaderValue(field);
      const now = canonicalValue(field, payload[field]);
      if (ai !== now) list.push({ label: FIELD_LABELS[field], field, ai, now });
    });
    payload.items.forEach((item, index) => {
      ITEM_FIELDS.forEach((field) => {
        const ai = aiItemValue(item.source_line_no, field);
        const now = canonicalValue(field, item[field]);
        if (ai !== now) {
          const prefix = '明細 ' + (index + 1) + (item.source_line_no ? '' : '（新增）') + ' ';
          list.push({ label: prefix + FIELD_LABELS[field], field, ai, now });
        }
      });
    });
    const kept = new Set(payload.items.map((item) => item.source_line_no).filter(Boolean));
    Object.values(aiItems)
      .filter((item) => !kept.has(item.line_no))
      .forEach((item) => {
        list.push({ label: '刪除 AI 明細 ' + item.line_no, field: 'item_name', ai: item.item_name, now: null });
      });
    return list;
  }

  function renderModifiedSummary(payload) {
    const box = $('#modified-summary');
    const list = $('#modified-list');
    if (!box || !list) return;
    const fields = modifiedFields(payload);
    list.textContent = '';
    fields.forEach((f) => {
      list.append(make('li', {}, f.label + '：' + displayValue(f.field, f.ai) + ' → ' + displayValue(f.field, f.now)));
    });
    setText(
      '#modified-title',
      fields.length ? '已修改 ' + fields.length + ' 個欄位（送出後標記給審核人員）：' : '未修改 AI 辨識內容。'
    );
    box.classList.toggle('alert--warning', Boolean(fields.length));
    list.hidden = !fields.length;
  }

  // =========================================================================
  // 查重與送出
  // =========================================================================
  function showDuplicateResult(kind, title, message) {
    const box = $('#dup-alert-box');
    if (!box) return;
    box.hidden = false;
    box.className = 'duplicate-alert duplicate-alert--' + kind;
    box.textContent = '';
    box.append(make('strong', {}, title), document.createTextNode(message));
  }

  function resetDuplicateState() {
    isDuplicateChecked = false;
    isDuplicate = false;
    const box = $('#dup-alert-box');
    if (box) box.hidden = true;
    const submitGroup = $('#final-submit-group');
    if (submitGroup) submitGroup.hidden = true;
    const btnCheckDup = $('#btn-check-duplicate');
    if (btnCheckDup) btnCheckDup.hidden = false;
    const finalAck = $('#finalAck');
    if (finalAck) finalAck.checked = false;
  }

  function invoiceNoOf(payload) {
    return payload.invoice_track + payload.invoice_number;
  }

  async function checkDuplicate(button) {
    button.disabled = true;
    button.textContent = '檢查中…';
    const no = invoiceNoOf(currentPayload);
    try {
      const result = await postJson('/invoices/check-duplicate', {
        invoice_track: currentPayload.invoice_track,
        invoice_number: currentPayload.invoice_number,
        seller_tax_id: currentPayload.seller_tax_id,
      });
      if (!result) return;
      if (!result.ok) {
        showDuplicateResult('warn', '無法查重：', errorMessage(result.data, '請稍後再試'));
        return;
      }
      isDuplicateChecked = true;
      isDuplicate = result.data.is_duplicate === true;
      button.hidden = true;
      const submitGroup = $('#final-submit-group');
      if (isDuplicate) {
        showDuplicateResult('warn', '⚠️ 發票重複！', '此發票（' + no + '）已存在於系統中，禁止重複上傳。');
        if (submitGroup) submitGroup.hidden = true;
      } else {
        showDuplicateResult('ok', '✓ 未重複！', '發票（' + no + '）經查核無重複紀錄。');
        if (submitGroup) submitGroup.hidden = false;
      }
    } catch {
      showDuplicateResult('warn', '無法查重：', '無法連線，請確認網路後再試');
    } finally {
      button.disabled = false;
      button.textContent = '系統檢查發票是否重複';
    }
  }

  function showSuccess(data) {
    const no = invoiceNoOf(currentPayload);
    saveHistory({
      no,
      date: new Date().toLocaleString('zh-TW'),
      sales: currentPayload.sales_amount,
      rotation: currentImage.rotation || 0,
    });
    setText('#success-invoice-no', no);
    setText('#success-rotation', currentImage.isPdf ? 'PDF（不旋轉）' : (currentImage.rotation || 0) + '°');
    setText('#success-status', STATUS_LABELS[data.status] || data.status || '');
    const modified = (data && data.modified_fields) || [];
    setText(
      '#success-modified',
      modified.length ? modified.length + ' 個欄位（已標記，審核人員會逐欄確認）' : '無（與 AI 辨識相同）'
    );
    const warnings = (data && data.warnings) || [];
    const box = $('#success-warnings');
    const list = $('#success-warning-list');
    if (box && list) {
      list.textContent = '';
      warnings.forEach((w) => list.append(make('li', {}, w.message)));
      box.hidden = !warnings.length;
    }
    showStep('step-success');
  }

  async function submitInvoice(button) {
    if (!isDuplicateChecked) return notify('請先點選查重');
    if (isDuplicate) return notify('發票已存在，無法上傳');
    const ack = $('#finalAck');
    if (!ack || !ack.checked) return notify('請勾選「確認將資料上傳至系統」');

    button.disabled = true;
    button.textContent = '上傳中…';
    try {
      const result = await postJson('/invoices/mobile-upload', currentPayload);
      if (!result) return;
      if (result.ok) {
        showSuccess(result.data);
        return;
      }
      if (errorOf(result.data).code === 'INVOICE_DUPLICATED') {
        isDuplicate = true;
        const submitGroup = $('#final-submit-group');
        if (submitGroup) submitGroup.hidden = true;
        showDuplicateResult('warn', '⚠️ 發票重複！', errorMessage(result.data, '此發票已存在於系統中'));
        return;
      }
      notify(errorMessage(result.data, '上傳失敗，請稍後再試'));
    } catch {
      notify('無法連線，請確認網路後再試');
    } finally {
      button.disabled = false;
      button.textContent = '確認上傳至系統';
    }
  }

  function renderHistory() {
    const container = $('#history-list-container');
    if (!container) return;
    container.textContent = '';
    const list = readHistory();
    if (!list.length) {
      container.append(make('p', { class: 'muted' }, '目前尚無本機上傳紀錄。'));
      return;
    }
    const ul = make('ul', { class: 'list' });
    list.forEach((item) => {
      const li = make('li');
      li.append(
        make('b', {}, String(item.no || '')),
        document.createTextNode(' · 銷售額 $' + String(item.sales || '') + ' · 旋轉 ' + String(item.rotation || 0) + '°'),
        make('br'),
        make('small', { class: 'muted' }, String(item.date || ''))
      );
      ul.append(li);
    });
    container.append(ul);
  }

  // =========================================================================
  // 事件綁定與初始化
  // =========================================================================
  document.addEventListener('DOMContentLoaded', () => {
    // 頁面模式：camera（手機拍照頁）或 file（電腦上傳頁，可另選單頁 PDF）
    const shell = $('[data-upload-mode]');
    const fileMode = Boolean(shell) && shell.dataset.uploadMode === 'file';

    // 1. 開啟相機；電腦上傳頁的「重新選擇檔案」回到選檔步驟
    const btnCamera = $('#btn-open-camera');
    if (btnCamera) btnCamera.onclick = openCamera;
    // 重拍／重新選擇：先作廢目前檔案與進行中的辨識，再回到第一步（手機頁接著開相機）
    const chooseAgain = () => {
      releaseImage();
      showStep('step-upload');
      if (!fileMode) openCamera();
    };
    const btnRetake1 = $('#btn-retake-preview');
    if (btnRetake1) btnRetake1.onclick = chooseAgain;
    const btnRetake2 = $('#btn-retake-fields');
    if (btnRetake2) btnRetake2.onclick = chooseAgain;

    // 2. 選取本機檔案：影像辨識前會縮圖，原檔可到 10 MB；PDF（只限電腦上傳頁）原檔上傳，4 MB 以內
    const fileInput = $('#file-album-upload');
    if (fileInput) {
      fileInput.onchange = function (e) {
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        fileInput.value = '';
        if (fileMode && f.type === 'application/pdf') {
          if (f.size > MAX_PDF_BYTES) return notify('PDF 需在 4 MB 以內');
          setImage({ isPdf: true, file: f, url: URL.createObjectURL(f), rotation: 0, name: f.name });
          showStep('step-preview');
          return;
        }
        if (!['image/jpeg', 'image/png'].includes(f.type) || f.size > MAX_SOURCE_IMAGE_BYTES) {
          return notify(fileMode ? '請選取 JPG、PNG（10 MB 以內）或 PDF（4 MB 以內）' : '請選取 JPG 或 PNG 格式，10 MB 以內');
        }
        // 讀檔是非同步的：選檔當下就作廢先前的檔案與讀檔，讀完時若已再選其他檔案（或拍照、示範）即丟棄
        releaseImage();
        const version = imageVersion;
        const rd = new FileReader();
        rd.onload = function () {
          if (version !== imageVersion) return;
          setImage({
            image: rd.result,
            originalImage: rd.result,
            rotation: 0,
            name: f.name,
          });
          showStep('step-preview');
        };
        rd.readAsDataURL(f);
      };
    }

    // 3. 使用示範發票（同樣送 API 辨識）
    const btnDemo = $('#btn-use-demo');
    if (btnDemo) {
      btnDemo.onclick = function () {
        setImage({
          image: '/static/img/reference_invoice.jpg',
          originalImage: '/static/img/reference_invoice.jpg',
          rotation: 0,
          name: '示範發票樣張.jpg',
        });
        showStep('step-preview');
      };
    }

    // 4. 旋轉操作
    const btnRotLeft = $('#btn-rotate-left');
    if (btnRotLeft) btnRotLeft.onclick = () => rotatePhoto(-90);

    const btnRotRight = $('#btn-rotate-right');
    if (btnRotRight) btnRotRight.onclick = () => rotatePhoto(90);

    const btnRestore = $('#btn-rotate-restore');
    if (btnRestore) btnRestore.onclick = () => rotatePhoto(null);

    // 5. AI 辨識（API：存圖、OCR、20B 整理欄位）
    const btnRecognize = $('#btn-recognize');
    if (btnRecognize) btnRecognize.onclick = () => recognizeCurrentImage(btnRecognize);

    // 6. 核對修正完成
    const btnConfirmFields = $('#btn-confirm-fields');
    if (btnConfirmFields) {
      const confirmLabel = btnConfirmFields.textContent;
      btnConfirmFields.onclick = function () {
        if (!currentDraft || !currentRecognition) return;
        // 先勾選「我已核對」→ 鎖定按鈕 → 收集欄位 → API 必填檢核（缺漏或失敗就停止）→ 才進行原有的格式檢查、查重與送出
        Rules.runConfirm({
          isBusy: () => confirmingRequired,
          setBusy: (busy) => {
            confirmingRequired = busy;
            btnConfirmFields.disabled = busy;
            btnConfirmFields.textContent = busy ? '檢查中…' : confirmLabel;
          },
          isAcknowledged: () => {
            const ack = $('#uploaderAck');
            return Boolean(ack && ack.checked);
          },
          notifyAck: () => notify('請勾選「我已核對影像與辨識內容，確認資料正確」'),
          collect: collectDraft,
          buildCheckBody: () => Rules.buildCheckRequest(currentDraft, currentRecognition.recognition_id),
          checkRequired: (body) => postJson('/invoices/check-required', body),
          showMissing,
          clearMissing,
          showCheckFailure,
          proceed: continueAfterRequired,
        }).catch(() => showCheckFailure(Rules.CHECK_FAILURE_MESSAGE));
      };
    }

    // 7. 返回核對修正
    const btnBackFields = $('#btn-back-fields');
    if (btnBackFields) {
      btnBackFields.onclick = () => showStep('step-fields');
    }

    // 8. 系統查重
    const btnCheckDup = $('#btn-check-duplicate');
    if (btnCheckDup) btnCheckDup.onclick = () => checkDuplicate(btnCheckDup);

    // 9. 最終送出上傳
    const btnFinalSubmit = $('#btn-final-upload');
    if (btnFinalSubmit) btnFinalSubmit.onclick = () => submitInvoice(btnFinalSubmit);

    // 10. 繼續上傳下一張
    const btnNext = $('#btn-upload-next');
    if (btnNext) {
      btnNext.onclick = function () {
        releaseImage();
        currentRecognition = null;
        currentDraft = null;
        currentPayload = null;
        editLog = [];
        committed = new Map();
        showStep('step-upload');
      };
    }

    // 11. 查看紀錄
    const btnHistory = $('#btn-view-history');
    if (btnHistory) {
      btnHistory.onclick = function () {
        renderHistory();
        showStep('step-history');
      };
    }

    const btnBackFromHistory = $('#btn-back-from-history');
    if (btnBackFromHistory) {
      btnBackFromHistory.onclick = () => showStep('step-upload');
    }
  });
})();
