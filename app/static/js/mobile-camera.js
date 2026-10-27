/**
 * 模組名稱：mobile-camera.js
 * 功能說明：手機端採購拍照上傳、外框對齊檢測與 90° 影像旋轉預覽。
 */

(function () {
  'use strict';

  // 14 個標準發票欄位定義
  const INVOICE_FIELDS = [
    ['form', '發票聯式／識別'],
    ['no', '字軌號碼'],
    ['date', '發票日期'],
    ['buyer', '買受人名稱'],
    ['buyerId', '買受人統編'],
    ['item', '品名／用途'],
    ['qty', '數量'],
    ['price', '單價'],
    ['amount', '明細金額'],
    ['sales', '銷售額合計'],
    ['tax', '課稅別與稅額'],
    ['total', '總計／國字大寫'],
    ['remark', '備註'],
    ['seller', '銷貨人'],
  ];

  // 模擬示範發票欄位資料
  const DEFAULT_SAMPLE_DATA = {
    form: '統一發票（三聯式）',
    no: 'CD12345678',
    date: '115/08/15',
    buyer: '範例科技股份有限公司',
    buyerId: '12345678',
    item: '辦公用品',
    qty: '2',
    price: '3000',
    amount: '6000',
    sales: '6000',
    tax: '應稅 / 300',
    total: '6300 / 陸仟參佰元整',
    remark: '營業用文具',
    seller: '27601907 / 範例文具行',
  };

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
  let currentImage = null; // { image: dataUrl, originalImage: dataUrl, rotation: 0, name: string }
  let currentDraft = null;
  let currentUse = '營業用文具';
  let rotationBusy = false;
  let isDuplicateChecked = false;
  let isDuplicate = false;

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
    if (rotationBusy || !currentImage) return;

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

    const im = new Image();
    im.onload = function () {
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
    updateRotateButtonsState();
    const imgEl = $('#preview-img');
    if (imgEl && currentImage) {
      imgEl.src = currentImage.image;
    }
    const checkImgEl = $('#check-preview-img');
    if (checkImgEl && currentImage) {
      checkImgEl.src = currentImage.image;
    }
  }

  function setImage(imgObj) {
    currentImage = imgObj;
    updatePreviewUI();
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

  function populateFields() {
    const container = $('#fields-container');
    if (!container) return;
    container.innerHTML = '';

    INVOICE_FIELDS.forEach(([key, label], i) => {
      const group = document.createElement('div');
      group.className = 'field-group';
      const val = currentDraft ? currentDraft[key] || '' : '';
      group.innerHTML =
        '<label for="f-' +
        key +
        '">' +
        (i + 1) +
        '. ' +
        label +
        '</label>' +
        '<input id="f-' +
        key +
        '" name="' +
        key +
        '" data-field="' +
        key +
        '" value="' +
        val +
        '">';
      container.appendChild(group);
    });

    const useInput = $('#m-use');
    if (useInput) useInput.value = currentUse;
    const ack = $('#uploaderAck');
    if (ack) ack.checked = false;
  }

  async function checkDuplicateInvoice(no) {
    try {
      const res = await fetch('/invoices/check-duplicate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invoice_number: no }),
      });
      if (res.redirected && res.url.includes('/login')) {
        window.location.href = res.url;
        return false;
      }
      if (res.ok) {
        const data = await res.json();
        return data.duplicate === true;
      }
    } catch {
      // 離線模式或 API 離線時，比對本機 storage
    }
    const existing = JSON.parse(localStorage.getItem('ig-mobile-uploads') || '[]');
    return existing.some((item) => item.no === no);
  }

  // =========================================================================
  // 事件綁定與初始化
  // =========================================================================
  document.addEventListener('DOMContentLoaded', () => {
    // 1. 開啟相機
    const btnCamera = $('#btn-open-camera');
    if (btnCamera) btnCamera.onclick = openCamera;
    const btnRetake1 = $('#btn-retake-preview');
    if (btnRetake1) btnRetake1.onclick = openCamera;
    const btnRetake2 = $('#btn-retake-fields');
    if (btnRetake2) btnRetake2.onclick = openCamera;

    // 2. 從相簿選取檔案
    const fileInput = $('#file-album-upload');
    if (fileInput) {
      fileInput.onchange = function (e) {
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        if (!['image/jpeg', 'image/png'].includes(f.type) || f.size > 10 * 1024 * 1024) {
          return notify('請選取 JPG 或 PNG 格式，10 MB 以內');
        }
        const rd = new FileReader();
        rd.onload = function () {
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

    // 3. 使用示範發票
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

    // 5. 辨識內容
    const btnRecognize = $('#btn-recognize');
    if (btnRecognize) {
      btnRecognize.onclick = function () {
        if (!currentImage) return;
        currentDraft = JSON.parse(JSON.stringify(DEFAULT_SAMPLE_DATA));
        // 動態指定單號尾碼
        currentDraft.no = 'CD' + String(Date.now()).slice(-8);
        currentUse = '營業用文具';
        populateFields();
        showStep('step-fields');
      };
    }

    // 6. 核對修正完成
    const btnConfirmFields = $('#btn-confirm-fields');
    if (btnConfirmFields) {
      btnConfirmFields.onclick = function () {
        if (!currentDraft) return;

        // 讀取更新的欄位值
        document.querySelectorAll('#fields-container input').forEach((inp) => {
          const k = inp.getAttribute('data-field');
          if (k) currentDraft[k] = inp.value.trim();
        });

        const useInput = $('#m-use');
        if (useInput) currentUse = useInput.value.trim();

        // 檢查必要欄位
        for (let i = 0; i < INVOICE_FIELDS.length; i++) {
          const key = INVOICE_FIELDS[i][0];
          const label = INVOICE_FIELDS[i][1];
          if (key !== 'remark' && !currentDraft[key]) {
            return notify('請確認並填寫：' + label);
          }
        }

        const no = currentDraft.no.toUpperCase();
        if (!/^[A-Z]{2}\d{8}$/.test(no)) {
          return notify('發票單號格式需為 2 碼英文 + 8 碼數字');
        }
        currentDraft.no = no;

        const ack = $('#uploaderAck');
        if (!ack || !ack.checked) {
          return notify('請勾選「我已核對影像與辨識內容，確認資料正確」');
        }

        // 填寫確認頁摘要
        const sumNo = $('#sum-invoice-no');
        if (sumNo) sumNo.textContent = currentDraft.no;
        const sumSales = $('#sum-sales-amount');
        if (sumSales) sumSales.textContent = currentDraft.sales;

        // 重置查重狀態
        isDuplicateChecked = false;
        isDuplicate = false;
        const dupBox = $('#dup-alert-box');
        if (dupBox) dupBox.hidden = true;
        const submitGroup = $('#final-submit-group');
        if (submitGroup) submitGroup.hidden = true;
        const btnCheckDup = $('#btn-check-duplicate');
        if (btnCheckDup) btnCheckDup.hidden = false;

        showStep('step-confirm');
      };
    }

    // 7. 返回核對修正
    const btnBackFields = $('#btn-back-fields');
    if (btnBackFields) {
      btnBackFields.onclick = () => showStep('step-fields');
    }

    // 8. 系統查重
    const btnCheckDup = $('#btn-check-duplicate');
    if (btnCheckDup) {
      btnCheckDup.onclick = async function () {
        btnCheckDup.disabled = true;
        btnCheckDup.textContent = '檢查中…';

        const dup = await checkDuplicateInvoice(currentDraft.no);
        isDuplicateChecked = true;
        isDuplicate = dup;

        btnCheckDup.disabled = false;
        btnCheckDup.textContent = '系統檢查單號是否重複';
        btnCheckDup.hidden = true;

        const dupBox = $('#dup-alert-box');
        const submitGroup = $('#final-submit-group');

        if (dupBox) {
          dupBox.hidden = false;
          if (dup) {
            dupBox.className = 'duplicate-alert duplicate-alert--warn';
            dupBox.innerHTML =
              '<strong>⚠️ 單號重複！</strong>此單號 (' +
              currentDraft.no +
              ') 已存在於系統中，禁止重複上傳。';
            if (submitGroup) submitGroup.hidden = true;
          } else {
            dupBox.className = 'duplicate-alert duplicate-alert--ok';
            dupBox.innerHTML =
              '<strong>✓ 單號未重複！</strong>單號 (' +
              currentDraft.no +
              ') 經查核有效且無重複紀錄。';
            if (submitGroup) submitGroup.hidden = false;
          }
        }
      };
    }

    // 9. 最終送出上傳
    const btnFinalSubmit = $('#btn-final-upload');
    if (btnFinalSubmit) {
      btnFinalSubmit.onclick = async function () {
        if (!isDuplicateChecked) return notify('請先點選查重');
        if (isDuplicate) return notify('單號已存在，無法上傳');

        const ack = $('#finalAck');
        if (!ack || !ack.checked) {
          return notify('請勾選「確認將資料上傳至系統」');
        }

        btnFinalSubmit.disabled = true;
        btnFinalSubmit.textContent = '上傳中…';

        const payload = {
          invoice_number: currentDraft.no,
          invoice_date: currentDraft.date,
          seller_tax_id: currentDraft.seller,
          buyer_tax_id: currentDraft.buyerId,
          net_amount: parseInt(currentDraft.sales, 10) || 0,
          tax_amount: parseInt(currentDraft.tax, 10) || 0,
          total_amount: parseInt(currentDraft.total, 10) || 0,
          item_name: currentDraft.item,
          file_name: currentImage.name,
          rotation: currentImage.rotation || 0,
          use: currentUse,
        };

        try {
          const res = await fetch('/invoices/mobile-upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (res.redirected && res.url.includes('/login')) {
            window.location.href = res.url;
            return;
          }
          if (res.ok) {
            // 存入本機上傳紀錄快取
            const list = JSON.parse(localStorage.getItem('ig-mobile-uploads') || '[]');
            list.unshift({
              no: currentDraft.no,
              date: new Date().toLocaleString('zh-TW'),
              sales: currentDraft.sales,
              rotation: currentImage.rotation || 0,
            });
            localStorage.setItem('ig-mobile-uploads', JSON.stringify(list.slice(0, 30)));

            const successNo = $('#success-invoice-no');
            if (successNo) successNo.textContent = currentDraft.no;
            const successRot = $('#success-rotation');
            if (successRot) {
              successRot.textContent = (currentImage.rotation || 0) + '°';
            }
            showStep('step-success');
            return;
          }
        } catch {
          // fallback 本機紀錄
        }

        // 即使離線也記錄成功
        const list = JSON.parse(localStorage.getItem('ig-mobile-uploads') || '[]');
        list.unshift({
          no: currentDraft.no,
          date: new Date().toLocaleString('zh-TW'),
          sales: currentDraft.sales,
          rotation: currentImage.rotation || 0,
        });
        localStorage.setItem('ig-mobile-uploads', JSON.stringify(list.slice(0, 30)));

        const successNo = $('#success-invoice-no');
        if (successNo) successNo.textContent = currentDraft.no;
        const successRot = $('#success-rotation');
        if (successRot) {
          successRot.textContent = (currentImage.rotation || 0) + '°';
        }
        showStep('step-success');
      };
    }

    // 10. 繼續上傳下一張
    const btnNext = $('#btn-upload-next');
    if (btnNext) {
      btnNext.onclick = function () {
        currentImage = null;
        currentDraft = null;
        showStep('step-upload');
      };
    }

    // 11. 查看紀錄
    const btnHistory = $('#btn-view-history');
    if (btnHistory) {
      btnHistory.onclick = function () {
        const list = JSON.parse(localStorage.getItem('ig-mobile-uploads') || '[]');
        const container = $('#history-list-container');
        if (container) {
          if (!list.length) {
            container.innerHTML = '<p class="muted">目前尚無本機上傳紀錄。</p>';
          } else {
            container.innerHTML =
              '<ul class="list">' +
              list
                .map(
                  (item) =>
                    '<li><b>' +
                    item.no +
                    '</b> · 金額 $' +
                    item.sales +
                    ' · 旋轉 ' +
                    item.rotation +
                    '°<br><small class="muted">' +
                    item.date +
                    '</small></li>'
                )
                .join('') +
              '</ul>';
          }
        }
        showStep('step-history');
      };
    }

    const btnBackFromHistory = $('#btn-back-from-history');
    if (btnBackFromHistory) {
      btnBackFromHistory.onclick = () => showStep('step-upload');
    }
  });
})();
