/* 표시사항 사전검토 화면: 조회 → 제품 선택·등록 → 자료 연결(URL·사진) → 수집·판정 → 결과 */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtTs = (ts) => ts.slice(0, 10) + " " + ts.slice(11, 16);
  const STATUS_TEXT = { waiting: "대기", collecting: "수집 중", done: "완료", failed: "실패", skipped: "건너뜀" };

  async function api(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) {
      let msg = r.status + " " + r.statusText;
      try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) { /* noop */ }
      throw new Error(msg);
    }
    return r.json();
  }
  const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const showError = (e) => { $("#view").insertAdjacentHTML("afterbegin", '<div class="card error" role="alert">' + esc(e.message || e) + "</div>"); };

  const state = { meta: null, product: null, snapshots: [], current: null, compare: false };

  // ---------------------------------------------------------------- 채널·진행
  function renderChannels() {
    $("#channels").innerHTML = state.meta.channels.map((c) =>
      '<div><div class="row"><span' + (c.enabled ? "" : ' class="off"') + ">T" + c.tier + " · " + esc(c.label) + "</span><span>" +
      (c.enabled ? '<span class="pill done">사용</span>' : '<span class="pill skipped">꺼짐</span>') + "</span></div>" +
      (c.reason ? '<div class="why">' + esc(c.reason) + "</div>" : "") + "</div>").join("");
    const e = state.meta.engines;
    $("#engine-tag").textContent = "OCR " + e.ocr + " · 면 분류 " + e.classifier;
  }

  const channels = {};
  function renderProgress(stage) {
    const rows = Object.values(channels).sort((a, b) => a.tier - b.tier).map((c) =>
      '<div class="ch ' + c.status + '"><span class="tier">T' + c.tier + '</span><span class="name">' + esc(c.label) +
      '</span><span class="pill ' + c.status + '">' + (c.status === "collecting" ? '<span class="spin" aria-hidden="true"></span>' : "") +
      STATUS_TEXT[c.status] + '</span><span class="msg">' + esc(c.message) + "</span></div>").join("");
    $("#progress").innerHTML = rows + (stage ? '<p class="stage">' + stage + "</p>" : "");
  }

  // ---------------------------------------------------------------- 1. 후보
  async function search(e) {
    if (e) e.preventDefault();
    const q = $("#q").value.trim();
    if (!q) return;
    $("#view").innerHTML = '<div class="card empty"><span class="spin" aria-hidden="true"></span>찾는 중</div>';
    let res;
    try { res = await post("/api/candidates", { query: q, category: $("#cat").value || null }); } catch (err) { $("#view").innerHTML = ""; showError(err); return; }
    const known = res.known.map((p) => '<button type="button" class="cand" data-pid="' + p.id + '"><span class="src-tag">등록된 제품</span><strong>' +
      esc((p.brand ? p.brand + " " : "") + p.name) + '</strong><span class="num">' + esc(p.volume) + " · " + esc(p.category_label) +
      (p.barcode ? " · " + esc(p.barcode) : "") + "</span><small>연결 자료 " + p.listings.length + "건 · 사진 " + p.uploads.length + "장</small></button>").join("");
    const ext = res.external.map((c, i) => '<button type="button" class="cand" data-ext="' + i + '"><div class="row">' +
      (c.image_url ? '<img src="' + esc(c.image_url) + '" alt="" loading="lazy" referrerpolicy="no-referrer">' : "") +
      '<div><span class="src-tag">' + esc(c.channel_label) + " 후보</span><br><strong>" + esc((c.brand ? c.brand + " " : "") + c.name) +
      '</strong><br><span class="num">' + esc(c.volume || "용량 미상") + " · " + (c.category === "tube" ? "튜브" : "용기형") + "(추정)</span><br><small>" +
      esc(c.title_raw) + "</small></div></div></button>").join("");
    const notices = res.notices.length ? '<div class="notice-box">' + res.notices.map(esc).join("<br>") + "</div>" : "";
    $("#view").innerHTML = '<div class="card cands"><h2>"' + esc(q) + '" 검색 결과</h2><p class="muted">같은 이름이라도 기획세트·증정·리필은 표시사항이 다를 수 있어 자동으로 고르지 않습니다.</p>' +
      (known || ext ? '<div class="cand-list">' + known + ext + "</div>" : '<p class="muted" style="margin-top:12px">찾은 후보가 없습니다. 아래에서 직접 등록하세요.</p>') + notices + "</div>" +
      newProductForm(q);
    $$(".cand[data-pid]").forEach((b) => b.addEventListener("click", () => openProduct(Number(b.dataset.pid))));
    $$(".cand[data-ext]").forEach((b) => b.addEventListener("click", async () => {
      const c = res.external[Number(b.dataset.ext)];
      try {
        const p = await post("/api/products", { brand: c.brand, name: c.name, volume: c.volume, category: $("#cat").value || c.category,
          listing: { channel: c.channel, source_url: c.source_url, title_raw: c.title_raw, image_url: c.image_url, external_id: c.external_id, extra: c.extra } });
        openProduct(p.id);
      } catch (err) { showError(err); }
    }));
    $("#new-form").addEventListener("submit", createManual);
  }

  function newProductForm(q) {
    return '<section class="card"><div class="sec-title"><h3>직접 등록</h3><p>후보에 없으면 제품 정보를 넣고 사내 사진으로 검토합니다.</p></div>' +
      '<form id="new-form" class="form"><div class="inline"><div><label for="nf-brand">브랜드</label><input id="nf-brand"></div>' +
      '<div><label for="nf-name">제품명</label><input id="nf-name" required value="' + esc(q) + '"></div>' +
      '<div><label for="nf-vol">용량</label><input id="nf-vol" placeholder="50mL"></div></div>' +
      '<div class="inline"><div><label for="nf-cat">카테고리</label><select id="nf-cat"><option value="container">용기형</option><option value="tube">튜브</option></select></div>' +
      '<div><label for="nf-bc">바코드 (선택)</label><input id="nf-bc" inputmode="numeric"></div></div>' +
      '<button type="submit" class="primary">등록하고 열기</button></form></section>';
  }

  async function createManual(e) {
    e.preventDefault();
    try {
      const p = await post("/api/products", { brand: $("#nf-brand").value, name: $("#nf-name").value, volume: $("#nf-vol").value,
        category: $("#nf-cat").value, barcode: $("#nf-bc").value || null });
      openProduct(p.id);
    } catch (err) { showError(err); }
  }

  // ---------------------------------------------------------------- 2. 제품 화면
  async function openProduct(pid, selectId) {
    try { state.product = await api("/api/products/" + pid); } catch (e) { showError(e); return; }
    if (location.hash !== "#product-" + pid) history.replaceState(null, "", "#product-" + pid);
    state.snapshots = await api("/api/products/" + pid + "/snapshots?" + new URLSearchParams(filterDates()));
    state.current = null;
    const id = selectId || (state.snapshots[0] && state.snapshots[0].snapshot_id);
    if (id) state.current = await api("/api/snapshots/" + id);
    render();
  }

  function filterDates() {
    const o = {};
    if ($("#from").value) o.date_from = $("#from").value;
    if ($("#to").value) o.date_to = $("#to").value;
    return o;
  }

  function render(running) {
    const p = state.product;
    const sources = sourcesCard(p);
    const snapPills = state.snapshots.map((s) => '<button type="button" class="snap" data-id="' + s.snapshot_id + '" aria-pressed="' +
      (state.current && state.current.snapshot_id === s.snapshot_id) + '">' + fmtTs(s.collected_at) + "</button>").join("");
    const prev = prevSnapshot();
    let html = '<div class="card"><div class="prod"><div><h2>' + esc((p.brand ? p.brand + " " : "") + p.name) + '</h2><div class="meta"><span class="cat">' +
      esc(p.category_label) + '</span><span class="num">' + esc(p.volume || "용량 미상") + "</span>" + (p.barcode ? '<span class="mono">' + esc(p.barcode) + "</span>" : "") +
      (state.current ? "<span>룰셋 " + esc(state.current.ruleset_version) + '</span><span class="engine">OCR ' + esc(state.current.engine_info.ocr) +
        " (기준 " + esc(state.current.engine_info.ocr_line_conf) + ") · 면 분류 " + esc(state.current.engine_info.classifier) + "</span>" : "") +
      '</div></div></div><div class="run-bar"><button type="button" class="primary" id="run"' + (running ? " disabled" : "") + ">" +
      (running ? '<span class="spin" aria-hidden="true"></span>수집·판정 중' : "수집·판정 실행") + '</button><span class="muted">오늘 수집분이 있으면 그 결과를 보여주고, 다시 누르면 새로 수집합니다.</span></div>' +
      '<div class="snaps"><span class="lbl">수집일 스냅샷</span>' + (snapPills || '<span class="muted">아직 없음</span>') +
      '<label class="cmp-toggle"><input type="checkbox" id="cmp"' + (state.compare ? " checked" : "") + (prev ? "" : " disabled") + "> 이전 수집분과 비교</label></div>" +
      (state.current ? renderSummary(state.current) : "") + "</div>" + sources;
    if (state.current) html += '<div id="cmp-box"></div>' + renderFaces(state.current) + renderChecks(state.current);
    else html += '<div class="card empty">아직 판정 결과가 없습니다. 자료를 연결하거나 사진을 올린 뒤 "수집·판정 실행"을 누르세요.</div>';
    $("#view").innerHTML = html;
    bind();
    renderCompare();
  }

  function sourcesCard(p) {
    const listings = p.listings.map((l) => '<li><span><b>' + esc(l.channel_label) + '</b> <a href="' + esc(l.source_url) + '" target="_blank" rel="noopener">' +
      esc(l.title_raw || l.source_url) + '</a></span><button type="button" class="ghost" data-del-listing="' + l.id + '" aria-label="연결 삭제">삭제</button></li>').join("");
    const uploads = p.uploads.map((u) => '<figure><img src="' + esc(u.image_url) + '" alt="업로드 사진"><figcaption>' + esc(u.face_hint ? faceLabel(u.face_hint) : "자동") +
      '</figcaption><button type="button" data-del-upload="' + u.id + '" aria-label="사진 삭제">×</button></figure>').join("");
    const faceOpts = ["", "front", "back", "left", "right", "top", "bottom"].map((f) => '<option value="' + f + '">' + (f ? faceLabel(f) : "자동 분류") + "</option>").join("");
    return '<section class="card"><div class="sec-title"><h3>자료 연결</h3><p>여기 연결된 자료만 수집합니다.</p></div><div class="grid2"><div>' +
      '<ul class="src-list">' + (listings || '<li class="muted">연결된 채널 페이지가 없습니다.</li>') + "</ul>" +
      '<form id="listing-form" class="form"><label for="lf-ch">채널 페이지 URL 추가</label><div class="inline"><select id="lf-ch">' +
      '<option value="hwahae">화해</option><option value="brand">브랜드 자사몰</option></select>' +
      '<input id="lf-url" type="url" placeholder="https://..." required></div><button type="submit" class="ghost">URL 연결</button></form></div>' +
      '<div><form id="upload-form" class="form"><label for="uf-files">사내 사진 올리기 (실물·샘플·도면)</label><input id="uf-files" type="file" accept="image/*" multiple required>' +
      '<label for="uf-face">면 지정</label><select id="uf-face">' + faceOpts + '</select><label for="uf-text">상세 텍스트 (선택, 예: 전성분 원문)</label>' +
      '<textarea id="uf-text" placeholder="전성분: 정제수, 글리세린, ..."></textarea><button type="submit" class="ghost">올리기</button></form>' +
      (uploads ? '<div class="thumbs">' + uploads + "</div>" : "") + "</div></div></section>";
  }

  function faceLabel(f) { const p = state.product; return ((state.meta.face_labels[p ? p.category : "container"]) || {})[f] || f; }

  function bind() {
    const pid = state.product.id;
    $("#run").addEventListener("click", () => run(pid));
    $$(".snap").forEach((b) => b.addEventListener("click", async () => { state.current = await api("/api/snapshots/" + b.dataset.id); render(); }));
    const cmp = $("#cmp");
    if (cmp) cmp.addEventListener("change", () => { state.compare = cmp.checked; renderCompare(); });
    $$(".ev-btn").forEach((b) => b.addEventListener("click", () => {
      const box = document.getElementById(b.getAttribute("aria-controls"));
      const open = b.getAttribute("aria-expanded") === "true";
      b.setAttribute("aria-expanded", String(!open));
      box.hidden = open;
    }));
    $$("[data-del-listing]").forEach((b) => b.addEventListener("click", async () => {
      try { state.product = await api("/api/listings/" + b.dataset.delListing, { method: "DELETE" }); render(); } catch (e) { showError(e); }
    }));
    $$("[data-del-upload]").forEach((b) => b.addEventListener("click", async () => {
      try { state.product = await api("/api/uploads/" + b.dataset.delUpload, { method: "DELETE" }); render(); } catch (e) { showError(e); }
    }));
    $("#listing-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try { state.product = await post("/api/products/" + pid + "/listings", { channel: $("#lf-ch").value, url: $("#lf-url").value }); render(); } catch (err) { showError(err); }
    });
    $("#upload-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData();
      Array.from($("#uf-files").files).forEach((f) => fd.append("files", f));
      fd.append("face_hint", $("#uf-face").value);
      fd.append("detail_text", $("#uf-text").value);
      try {
        const r = await api("/api/products/" + pid + "/uploads", { method: "POST", body: fd });
        state.product = r.product;
        render();
        if (r.rejected.length) showError(new Error("올리지 못한 파일: " + r.rejected.join(", ")));
      } catch (err) { showError(err); }
    });
  }

  // ---------------------------------------------------------------- 3. 수집·판정
  async function run(pid) {
    let res;
    const refresh = !!(state.current && state.current.collected_at.slice(0, 10) === state.meta.today);
    try { res = await post("/api/products/" + pid + "/lookups", { refresh: refresh }); } catch (e) { showError(e); return; }
    if (res.status === "cached") { openProduct(pid, res.snapshot_id); return; }
    Object.keys(channels).forEach((k) => delete channels[k]);
    renderProgress('<span class="spin" aria-hidden="true"></span>시작');
    render(true);
    const es = new EventSource("/api/lookups/" + res.lookup_id + "/events");
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.type === "channel") { channels[ev.channel] = ev; renderProgress('<span class="spin" aria-hidden="true"></span>수집 중'); }
      if (ev.type === "stage") renderProgress('<span class="spin" aria-hidden="true"></span>' + esc(ev.message));
      if (ev.type === "done") { es.close(); renderProgress("완료 · 스냅샷 저장됨"); openProduct(pid, ev.snapshot_id); }
      if (ev.type === "error") { es.close(); renderProgress('<span class="error">' + esc(ev.message) + "</span>"); render(); }
    };
    es.onerror = () => { es.close(); renderProgress('<span class="error">진행 상태 연결이 끊겼습니다. 화면을 새로 고치세요.</span>'); };
  }

  // ---------------------------------------------------------------- 4. 결과
  function prevSnapshot() {
    if (!state.current) return null;
    const i = state.snapshots.findIndex((s) => s.snapshot_id === state.current.snapshot_id);
    return i >= 0 ? state.snapshots[i + 1] || null : null;
  }

  function renderSummary(s) {
    const items = [["ok", "있음"], ["none", "없음"], ["unreadable", "판독불가"], ["face_missing", "면 미확보"], ["conflict", "충돌"]];
    const captured = s.faces.filter((f) => f.status === "captured").length;
    return '<div class="summary">' + items.map(([k, l]) => '<div class="sum ' + (k === "conflict" ? "sum-conflict" : k) + '"><b>' + s.summary[k] + "</b><span>" + l + "</span></div>").join("") +
      '<div class="sum"><b>' + captured + "/6</b><span>면 확보</span></div></div>";
  }

  function ocrList(img, th) {
    if (!img.ocr_lines.length) return '<span class="muted">글자 없음</span>';
    return '<details><summary>OCR ' + img.ocr_lines.length + "줄 보기</summary><ol>" +
      img.ocr_lines.map((l) => '<li class="' + (l.conf < th ? "low" : "") + '">' + esc(l.text) + ' <span class="num">(' + l.conf.toFixed(2) + ")</span></li>").join("") + "</ol></details>";
  }

  function renderFaces(s) {
    const th = Number(s.engine_info.ocr_line_conf || 0.8);
    const tiles = s.faces.map((f) => {
      const r = f.representative;
      if (!r) return '<article class="face missing"><header><span>' + esc(f.label) + '</span><span class="state">미확보</span></header><div class="thumb"><p class="none">수집 이미지 중<br>이 면이 없음</p></div><footer><span>—</span></footer></article>';
      return '<article class="face captured"><header><span>' + esc(f.label) + '</span><span class="state">확보' + (f.extra.length ? " +" + f.extra.length : "") +
        '</span></header><div class="thumb"><a href="' + esc(r.image_url) + '" target="_blank" rel="noopener"><img src="' + esc(r.image_url) + '" alt="' + esc(f.label + " · " + r.channel_label) +
        '" loading="lazy"></a></div><footer><span>' + esc(r.channel_label) + (r.source_url && r.source_url.startsWith("http") ? ' · <a href="' + esc(r.source_url) + '" target="_blank" rel="noopener">원본</a>' : "") +
        '</span><span class="num">' + r.width + "×" + r.height + " · OCR " + Number(r.ocr_confidence).toFixed(2) + (r.sliced ? " · 분할컷" : "") +
        '</span><span title="' + esc(r.face_reason) + '">분류 ' + Number(r.face_conf).toFixed(2) + " · " + esc(r.face_reason) + '</span><span class="ocr">' + ocrList(r, th) + "</span></footer></article>";
    }).join("");
    const un = s.unclassified.length ? '<div class="uncls"><span>미분류·연출컷 ' + s.unclassified.length + "장 (면 배치 안 함):</span>" +
      s.unclassified.map((u) => '<a href="' + esc(u.image_url) + '" target="_blank" rel="noopener"><img src="' + esc(u.image_url) + '" alt="미분류 이미지" title="' +
        esc(u.channel_label + " · " + u.face_reason + " (" + Number(u.face_conf).toFixed(2) + ")") + '"></a>').join("") + "</div>" : "";
    const dedup = s.dedup_count ? " · 채널 간 같은 이미지 " + s.dedup_count + "장 중복 제거" : "";
    return '<section class="card"><div class="sec-title"><h3>면별 확보 현황</h3><p>대표 이미지 = 지정 업로드 > OCR 신뢰도 > 해상도' + dedup + '</p></div><div class="faces">' + tiles + "</div>" + un + "</section>";
  }

  function diffTokens(a, b) {
    const split = (x) => x.split(/,\s+/).map((t) => t.trim());
    const tb = new Set(split(b));
    return split(a).map((t) => (tb.has(t) ? esc(t) : "<mark>" + esc(t) + "</mark>")).join(", ");
  }

  function renderChecks(s) {
    const rows = s.checks.map((c, i) => {
      let vals = "";
      if (c.values.length) {
        const others = (v) => c.values.filter((x) => x !== v).map((x) => x.value_raw).join(", ");
        vals = '<div class="ev"><button type="button" class="ghost ev-btn" aria-expanded="' + c.conflict + '" aria-controls="ev-' + i + '">근거 ' + c.values.length +
          '건</button><ul class="ev-list" id="ev-' + i + '"' + (c.conflict ? "" : " hidden") + ">" + c.values.map((v) => '<li><span class="src">' +
          esc(v.face_label ? v.face_label + " OCR" : "상세 텍스트") + " · " + esc(v.channel_label) + "</span>" + (c.conflict ? diffTokens(v.value_raw, others(v)) : esc(v.value_raw)) + "</li>").join("") + "</ul></div>";
      }
      return '<tr class="' + c.status + '"><td><div class="item-name">' + esc(c.item_name) + '</div><div class="item-basis">' + esc(c.basis) + "</div></td><td>" +
        esc(c.face_labels.join(", ")) + '</td><td><span class="st ' + c.status + '">' + esc(c.status_label) + "</span>" + (c.conflict ? '<br><span class="conflict">충돌 · 확인</span>' : "") +
        '</td><td class="val">' + (c.value ? esc(c.value) : '<span class="muted">—</span>') + vals + '</td><td class="note">' + esc(c.note) + "</td></tr>";
    }).join("");
    return '<section class="card"><div class="sec-title"><h3>표시사항 체크리스트</h3><p>판독불가·면 미확보는 "없음"과 다릅니다. 확인하지 못했다는 뜻입니다.</p></div><div class="table-wrap"><table class="checks"><thead><tr>' +
      '<th scope="col">항목</th><th scope="col">확인 면</th><th scope="col">상태</th><th scope="col">추출 값</th><th scope="col">비고</th></tr></thead><tbody>' + rows + "</tbody></table></div></section>";
  }

  async function renderCompare() {
    const box = $("#cmp-box");
    const prev = prevSnapshot();
    if (!box || !state.compare || !prev) { if (box) box.innerHTML = ""; return; }
    const c = await api("/api/snapshots/compare?a=" + prev.snapshot_id + "&b=" + state.current.snapshot_id);
    box.innerHTML = '<section class="card cmp"><div class="sec-title"><h3>수집일 비교 · ' + c.changed_count + "개 항목 변경</h3><p>" + fmtTs(c.before.collected_at) + " → " + fmtTs(c.after.collected_at) +
      (c.ruleset_changed ? " · 룰셋 버전이 달라 판정 기준 변경 포함" : "") + '</p></div><div class="table-wrap"><table><thead><tr><th scope="col">항목</th><th scope="col">이전</th><th scope="col">이후</th></tr></thead><tbody>' +
      c.rows.map((r) => '<tr class="' + (r.changed ? "" : "same") + '"><td>' + esc(r.item_name) + (r.changed ? ' <span class="chg">변경</span>' : "") + "</td><td>" + esc(r.before.status_label) +
        '<br><span class="muted">' + esc(r.before.value || "—") + "</span></td><td>" + esc(r.after.status_label) + '<br><span class="muted">' + esc(r.after.value || "—") + "</span></td></tr>").join("") +
      "</tbody></table></div></section>";
  }

  // ---------------------------------------------------------------- 시작
  async function init() {
    state.meta = await api("/api/meta");
    renderChannels();
    $("#to").value = state.meta.today;
    $("#search-form").addEventListener("submit", search);
    const m = location.hash.match(/^#product-(\d+)$/);
    if (m) openProduct(Number(m[1]));
    else $("#view").innerHTML = '<div class="card empty">제품명이나 바코드로 찾으세요. 후보가 없으면 직접 등록하고 사내 사진으로 검토할 수 있습니다.</div>';
  }
  init().catch(showError);
})();
