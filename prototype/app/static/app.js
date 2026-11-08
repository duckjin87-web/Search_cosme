/* 표시사항 사전검토 프로토타입 화면.
   서버 모드: /api 호출.  정적 데모 모드: window.STATIC_DATA 를 같은 모양으로 흉내 낸다. */
(function () {
  "use strict";

  // ---------------------------------------------------------------- API
  function HttpApi() {
    async function j(url, opts) {
      const r = await fetch(url, opts);
      if (!r.ok) {
        let msg = r.status + " " + r.statusText;
        try { msg = (await r.json()).detail || msg; } catch (e) { /* noop */ }
        throw new Error(msg);
      }
      return r.json();
    }
    const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();
    return {
      meta: () => j("/api/meta"),
      lookup: (body) => j("/api/lookups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
      events(id, onEvent) {
        const es = new EventSource("/api/lookups/" + id + "/events");
        es.onmessage = (m) => {
          const ev = JSON.parse(m.data);
          onEvent(ev);
          if (ev.type === "done" || ev.type === "error") es.close();
        };
        es.onerror = () => { es.close(); onEvent({ type: "error", message: "진행 상태 연결이 끊겼습니다. 다시 조회하세요." }); };
      },
      snapshots: (key, from, to) => j("/api/products/" + encodeURIComponent(key) + "/snapshots?" + qs({ date_from: from, date_to: to })),
      snapshot: (id) => j("/api/snapshots/" + id),
      compare: (a, b) => j("/api/snapshots/compare?" + qs({ a: a, b: b })),
    };
  }

  function StaticApi(D) {
    const collected = new Set(D.precollected);
    const norm = (s) => s.replace(/\s+/g, "").toLowerCase();
    const matches = (q, p) => {
      const hay = norm(p.brand + p.name + p.volume);
      return q.split(/\s+/).filter(Boolean).every((t) => hay.includes(norm(t)));
    };
    const inRange = (s, from, to) => (!from || s.collected_at.slice(0, 10) >= from) && (!to || s.collected_at.slice(0, 10) <= to);
    const list = (key, from, to) => (D.snapshots[key] || [])
      .filter((s) => !s.pending || collected.has(key))
      .filter((s) => inRange(s, from, to))
      .map((s) => ({ snapshot_id: s.snapshot_id, product_key: key, collected_at: s.collected_at, ruleset_version: s.ruleset_version }));
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    return {
      meta: async () => D.meta,
      async lookup(body) {
        let key = body.product_key;
        if (!key) {
          const q = (body.query || "").trim();
          if (!q) throw new Error("제품명을 입력하세요.");
          const c = D.catalog.filter((c) => matches(q, c.product) && (!body.category || c.product.category === body.category));
          if (!c.length) return { status: "not_found", query: q };
          if (c.length > 1) return { status: "needs_selection", query: q, candidates: c };
          key = c[0].product.product_key;
        }
        const product = D.catalog.find((c) => c.product.product_key === key).product;
        const snaps = list(key, body.date_from, body.date_to);
        if (collected.has(key) && !body.refresh) return { status: "cached", product: product, snapshots: snaps };
        return { status: "collecting", lookup_id: key, product: product, snapshots: snaps };
      },
      async events(id, onEvent) {
        for (const ev of D.events[id]) {
          if (ev.type === "channel" && ev.status === "collecting") await wait(250);
          if (ev.type === "channel" && ev.status !== "waiting" && ev.status !== "collecting") await wait(ev.tier === 1 ? 600 : 1500);
          if (ev.type === "done") { await wait(400); collected.add(id); }
          onEvent(ev);
        }
      },
      snapshots: async (key, from, to) => list(key, from, to),
      snapshot: async (id) => D.views[id],
      compare: async (a, b) => D.compares[a + "-" + b],
    };
  }

  const STATIC = !!window.STATIC_DATA;
  const Api = STATIC ? StaticApi(window.STATIC_DATA) : HttpApi();

  // ---------------------------------------------------------------- helpers
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtTs = (ts) => ts.slice(0, 10) + " " + ts.slice(11, 16);
  const STATUS_TEXT = { waiting: "대기", collecting: "수집 중", done: "완료", failed: "실패" };

  const state = { meta: null, product: null, snapshots: [], current: null, compare: false, form: null };

  // ---------------------------------------------------------------- 진행부
  const channels = {};
  function renderProgress(stage, cached) {
    const rows = Object.values(channels).sort((a, b) => a.tier - b.tier).map((c) => (
      '<div class="ch"><span class="tier">T' + c.tier + '</span><span class="name">' + esc(c.label) +
      '</span><span class="pill ' + c.status + '">' + (c.status === "collecting" ? '<span class="spin" aria-hidden="true"></span>' : "") +
      STATUS_TEXT[c.status] + '</span><span class="msg">' + esc(c.message) + "</span></div>"
    )).join("");
    const head = cached
      ? '<div class="ch"><span class="tier">캐시</span><span class="name">오늘 수집분 있음</span><span class="pill cached">즉시 표시</span>' +
        '<span class="msg">다시 수집하려면 아래 버튼을 누르세요.</span></div><button type="button" class="ghost" id="refresh">채널에서 다시 수집</button>'
      : "";
    $("#progress").innerHTML = head + rows + (stage ? '<p class="stage">' + stage + "</p>" : "");
    const r = $("#refresh");
    if (r) r.addEventListener("click", () => runLookup({ product_key: state.product.product_key, refresh: true }));
  }

  // ---------------------------------------------------------------- 조회 흐름
  async function runLookup(extra) {
    const f = state.form = Object.assign({
      query: $("#q").value.trim(), date_from: $("#from").value, date_to: $("#to").value, category: $("#cat").value,
    }, extra || {});
    $("#candidates").innerHTML = "";
    let res;
    try { res = await Api.lookup(f); } catch (e) { $("#result").innerHTML = '<div class="card error">' + esc(e.message) + "</div>"; return; }

    if (res.status === "not_found") {
      $("#result").innerHTML = '<div class="card empty">"' + esc(res.query) + '"에 맞는 제품을 찾지 못했습니다. 제품명을 줄여서 다시 조회해 보세요.</div>';
      return;
    }
    if (res.status === "needs_selection") { renderCandidates(res); return; }

    state.product = res.product;
    Object.keys(channels).forEach((k) => delete channels[k]);
    if (res.status === "cached") {
      renderProgress("", true);
      await loadSnapshots();
      return;
    }
    renderProgress('<span class="spin" aria-hidden="true"></span>Tier 1부터 수집을 시작합니다');
    state.snapshots = res.snapshots;
    renderShell(true);
    Api.events(res.lookup_id, async (ev) => {
      if (ev.type === "channel") { channels[ev.channel] = ev; renderProgress('<span class="spin" aria-hidden="true"></span>수집 중'); }
      if (ev.type === "stage") renderProgress('<span class="spin" aria-hidden="true"></span>' + esc(ev.message));
      if (ev.type === "done") { renderProgress("완료 · 스냅샷 저장됨"); await loadSnapshots(ev.snapshot_id); }
      if (ev.type === "error") renderProgress('<span class="error">' + esc(ev.message) + "</span>");
    });
  }

  function renderCandidates(res) {
    $("#result").innerHTML = "";
    $("#candidates").innerHTML = '<div class="card cands"><h2>같은 이름의 제품이 ' + res.candidates.length + "개 있습니다</h2>" +
      '<p class="muted">기획세트·증정·리필은 표시사항이 다를 수 있어 자동으로 고르지 않습니다. 확인할 제품을 고르세요.</p><div class="cand-list">' +
      res.candidates.map((c) => '<button type="button" class="cand" data-key="' + esc(c.product.product_key) + '"><strong>' +
        esc(c.product.brand + " " + c.product.name) + '</strong><span class="num">' + esc(c.product.volume) + " · " + esc(c.product.category_label) +
        (c.product.barcode ? " · " + esc(c.product.barcode) : "") + "</span><small>" +
        c.listings.map((l) => esc(l.channel_label) + ": " + esc(l.title_raw)).join("<br>") + "</small></button>").join("") + "</div></div>";
    document.querySelectorAll(".cand").forEach((b) => b.addEventListener("click", () => runLookup({ product_key: b.dataset.key })));
  }

  async function loadSnapshots(selectId) {
    const f = state.form;
    state.snapshots = await Api.snapshots(state.product.product_key, f.date_from, f.date_to);
    if (!state.snapshots.length) {
      $("#result").innerHTML = '<div class="card empty">선택한 수집일 기간에 스냅샷이 없습니다. 기간을 넓혀 보세요.</div>';
      return;
    }
    await selectSnapshot(selectId || state.snapshots[0].snapshot_id);
  }

  async function selectSnapshot(id) {
    state.current = await Api.snapshot(id);
    renderShell(false);
  }

  // ---------------------------------------------------------------- 결과부
  function renderShell(loading) {
    const p = state.product;
    const snapPills = state.snapshots.map((s) => '<button type="button" class="snap" data-id="' + s.snapshot_id + '" aria-pressed="' +
      (state.current && state.current.snapshot_id === s.snapshot_id && !loading) + '">' + fmtTs(s.collected_at) + "</button>").join("");
    const prev = prevSnapshot();
    let html = '<div class="card"><div class="prod"><div><h2>' + esc(p.brand + " " + p.name) + '</h2><div class="meta"><span class="cat">' +
      esc(p.category_label) + '</span><span class="num">' + esc(p.volume) + "</span>" + (p.barcode ? '<span class="mono">' + esc(p.barcode) + "</span>" : "") +
      (state.current && !loading ? "<span>룰셋 " + esc(state.current.ruleset_version) + "</span>" : "") + "</div></div></div>" +
      '<div class="snaps"><span class="lbl">수집일 스냅샷</span>' + (snapPills || '<span class="muted">아직 없음</span>') +
      (loading ? '<span class="muted"><span class="spin" aria-hidden="true"></span>새 스냅샷 수집 중</span>' : "") +
      '<label class="cmp-toggle"><input type="checkbox" id="cmp"' + (state.compare ? " checked" : "") + (prev && !loading ? "" : " disabled") +
      "> 이전 수집분과 비교</label></div>";
    if (!loading && state.current) html += renderSummary(state.current);
    html += "</div>";
    if (!loading && state.current) {
      html += '<div id="cmp-box"></div>' + renderFaces(state.current) + renderChecks(state.current);
    }
    $("#result").innerHTML = html;
    document.querySelectorAll(".snap").forEach((b) => b.addEventListener("click", () => selectSnapshot(Number(b.dataset.id))));
    const cmp = $("#cmp");
    if (cmp) cmp.addEventListener("change", () => { state.compare = cmp.checked; renderCompare(); });
    document.querySelectorAll(".ev-btn").forEach((b) => b.addEventListener("click", () => {
      const box = document.getElementById(b.getAttribute("aria-controls"));
      const open = b.getAttribute("aria-expanded") === "true";
      b.setAttribute("aria-expanded", String(!open));
      box.hidden = open;
    }));
    if (!loading) renderCompare();
  }

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

  function renderFaces(s) {
    const tiles = s.faces.map((f) => {
      const r = f.representative;
      if (!r) {
        return '<article class="face missing"><header><span>' + esc(f.label) + '</span><span class="state">미확보</span></header>' +
          '<div class="thumb"><p class="none">수집 이미지 중<br>이 면이 없음</p></div><footer><span>—</span></footer></article>';
      }
      return '<article class="face captured"><header><span>' + esc(f.label) + '</span><span class="state">확보' +
        (f.extra.length ? " +" + f.extra.length : "") + '</span></header><div class="thumb"><img src="' + esc(r.image_url) + '" alt="' +
        esc(f.label + " 이미지 · " + r.channel_label) + '" loading="lazy"></div><footer><span>' + esc(r.channel_label) +
        ' · <a href="' + esc(r.source_url) + '" target="_blank" rel="noopener">원본(예시 URL)</a></span><span class="num">' + r.width + "×" + r.height +
        " · OCR " + Number(r.ocr_confidence).toFixed(2) + "</span></footer></article>";
    }).join("");
    const un = s.unclassified.length
      ? '<div class="uncls"><span>미분류·연출컷 ' + s.unclassified.length + "장 (면 배치 안 함):</span>" +
        s.unclassified.map((u) => '<img src="' + esc(u.image_url) + '" alt="미분류 이미지 · 면 분류 신뢰도 ' + Number(u.face_conf).toFixed(2) + '" title="' +
          esc(u.channel_label + " · 면 분류 신뢰도 " + Number(u.face_conf).toFixed(2)) + '">').join("") + "</div>"
      : "";
    const dedup = s.dedup_count ? " · 채널 간 같은 이미지 " + s.dedup_count + "장 중복 제거" : "";
    return '<section class="card"><div class="sec-title"><h3>면별 확보 현황</h3><p>대표 이미지 = OCR 신뢰도·해상도 최고' + dedup +
      '</p></div><div class="faces">' + tiles + "</div>" + un + "</section>";
  }

  function diffTokens(a, b) {
    const split = (x) => x.split(/,\s+/).map((t) => t.trim());
    const ta = split(a);
    const tb = new Set(split(b));
    return ta.map((t) => (tb.has(t) ? esc(t) : "<mark>" + esc(t) + "</mark>")).join(", ");
  }

  function renderChecks(s) {
    const rows = s.checks.map((c, i) => {
      let vals = "";
      if (c.values.length) {
        const others = (v) => c.values.filter((x) => x !== v).map((x) => x.value_raw).join(",");
        vals = '<div class="ev"><button type="button" class="ghost ev-btn" aria-expanded="' + (c.conflict ? "true" : "false") +
          '" aria-controls="ev-' + i + '">근거 ' + c.values.length + "건</button><ul class=\"ev-list\" id=\"ev-" + i + '"' + (c.conflict ? "" : " hidden") + ">" +
          c.values.map((v) => '<li><span class="src">' + esc(v.face_label ? v.face_label + " OCR" : "상세 텍스트") + " · " + esc(v.channel_label) + "</span>" +
            (c.conflict ? diffTokens(v.value_raw, others(v)) : esc(v.value_raw)) + "</li>").join("") + "</ul></div>";
      }
      return '<tr class="' + c.status + '"><td><div class="item-name">' + esc(c.item_name) + '</div><div class="item-basis">' + esc(c.basis) +
        "</div></td><td>" + esc(c.face_labels.join(", ")) + '</td><td><span class="st ' + c.status + '">' + esc(c.status_label) + "</span>" +
        (c.conflict ? '<br><span class="conflict">충돌 · 확인</span>' : "") + '</td><td class="val">' + (c.value ? esc(c.value) : '<span class="muted">—</span>') +
        vals + '</td><td class="note">' + esc(c.note) + "</td></tr>";
    }).join("");
    return '<section class="card"><div class="sec-title"><h3>표시사항 체크리스트</h3><p>판독불가·면 미확보는 "없음"과 다릅니다. 확인하지 못했다는 뜻입니다.</p></div>' +
      '<div class="table-wrap"><table class="checks"><thead><tr><th scope="col">항목</th><th scope="col">확인 면</th><th scope="col">상태</th>' +
      '<th scope="col">추출 값</th><th scope="col">비고</th></tr></thead><tbody>' + rows + "</tbody></table></div></section>";
  }

  async function renderCompare() {
    const box = $("#cmp-box");
    if (!box) return;
    const prev = prevSnapshot();
    if (!state.compare || !prev) { box.innerHTML = ""; return; }
    const c = await Api.compare(prev.snapshot_id, state.current.snapshot_id);
    const rows = c.rows.map((r) => '<tr class="' + (r.changed ? "chg-row" : "same") + '"><td>' + esc(r.item_name) +
      (r.changed ? ' <span class="chg">변경</span>' : "") + "</td><td>" + esc(r.before.status_label) + "<br><span class=\"muted\">" + esc(r.before.value || "—") +
      "</span></td><td>" + esc(r.after.status_label) + "<br><span class=\"muted\">" + esc(r.after.value || "—") + "</span></td></tr>").join("");
    box.innerHTML = '<section class="card cmp"><div class="sec-title"><h3>수집일 비교 · ' + c.changed_count + "개 항목 변경</h3><p>" +
      fmtTs(c.before.collected_at) + " → " + fmtTs(c.after.collected_at) + "</p></div>" +
      '<div class="table-wrap"><table><thead><tr><th scope="col">항목</th><th scope="col">이전</th><th scope="col">이후</th></tr></thead><tbody>' +
      rows + "</tbody></table></div></section>";
  }

  // ---------------------------------------------------------------- 시작
  async function init() {
    state.meta = await Api.meta();
    const today = state.meta.today;
    const d = new Date(today + "T00:00:00");
    d.setMonth(d.getMonth() - 6);
    $("#to").value = today;
    $("#from").value = d.toISOString().slice(0, 10);
    $("#lookup-form").addEventListener("submit", (e) => { e.preventDefault(); runLookup(); });
    document.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => { $("#q").value = b.dataset.q; runLookup(); }));
    // 처음 열면 예시 제품 하나를 보여준다
    $("#q").value = "수분 장벽 크림";
    await runLookup({ product_key: "samplecos-barrier-cream-50ml" });
  }
  init().catch((e) => { $("#result").innerHTML = '<div class="card error">화면을 불러오지 못했습니다: ' + esc(e.message) + "</div>"; });
})();
