"use strict";

(() => {
  const form = document.querySelector("#assistant-form");
  const site = document.querySelector("#site");
  const radius = document.querySelector("#radius");
  const range = document.querySelector("#weather-range");
  const status = document.querySelector("#assistant-status");
  const result = document.querySelector("#assistant-result");
  const useModel = document.querySelector("#use-model");
  const modeStatus = document.querySelector("#mode-status");
  // Memory-only display state. Refreshing the page discards it, and it is never sent back to Gemini.
  const verifiedTurns = [];

  const text = (value, fallback = "原始資料未提供") =>
    typeof value === "string" && value.trim() ? value : (typeof value === "number" ? String(value) : fallback);
  const clear = node => { while (node.firstChild) node.removeChild(node.firstChild); };
  const safeUrl = value => {
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : null;
    } catch {
      return null;
    }
  };
  const taipeiIso = date => date.toLocaleString("sv-SE", {timeZone: "Asia/Taipei", hour12: false}).replace(" ", "T") + "+08:00";

  function appendSource(parent, item) {
    const url = safeUrl(item && item.url);
    if (!url) return;
    const card = document.createElement("article");
    card.className = "citation";
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = text(item.name, "原始來源");
    card.append(link);
    const meta = document.createElement("p");
    meta.textContent = `最後核對：${text(item.last_verified_at)}；授權／顯名：${text(item.license_or_terms)}`;
    card.append(meta);
    parent.append(card);
  }

  function renderVerifiedTurns() {
    const section = document.querySelector("#verified-turns");
    const list = document.querySelector("#verified-turn-list");
    clear(list);
    section.hidden = verifiedTurns.length === 0;
    for (const turn of verifiedTurns) {
      const item = document.createElement("article");
      item.className = "verified-turn";
      const heading = document.createElement("h4");
      heading.textContent = "Gemini RAG 已驗證摘要";
      const paragraph = document.createElement("p");
      paragraph.textContent = turn.summary;
      item.append(heading, paragraph);
      list.append(item);
    }
  }

  function renderModelSummary(payload) {
    const container = document.querySelector("#model-blocks");
    clear(container);
    if (!payload.model_used || typeof payload.summary !== "string" || !payload.summary.trim()) return;
    const article = document.createElement("article");
    article.className = "model-block";
    const heading = document.createElement("h3");
    heading.textContent = "Gemini RAG 已驗證摘要";
    const paragraph = document.createElement("p");
    paragraph.className = "model-text";
    paragraph.textContent = payload.summary;
    const note = document.createElement("p");
    note.textContent = "此摘要僅依本次受控檢索來源生成；來源、授權與限制由伺服器附加。";
    article.append(heading, paragraph, note);
    container.append(article);
    verifiedTurns.push({summary: payload.summary});
    while (verifiedTurns.length > 2) verifiedTurns.shift();
    renderVerifiedTurns();
  }

  function renderRecords(payload) {
    const records = document.querySelector("#records");
    clear(records);
    for (const record of (Array.isArray(payload.records) ? payload.records : [])) {
      const card = document.createElement("article");
      card.className = "record";
      const definition = document.createElement("dl");
      for (const [key, value] of Object.entries(record)) {
        const term = document.createElement("dt");
        const description = document.createElement("dd");
        term.textContent = key;
        description.textContent = typeof value === "object" ? JSON.stringify(value) : text(value);
        definition.append(term, description);
      }
      card.append(definition);
      records.append(card);
    }
  }

  function renderSources(payload) {
    const citations = document.querySelector("#citations");
    const links = document.querySelector("#links");
    clear(citations);
    clear(links);
    const basis = Array.isArray(payload.research_basis) ? payload.research_basis : payload.citations;
    if (Array.isArray(basis) && basis.length) {
      const heading = document.createElement("h3");
      heading.textContent = "研究依據";
      citations.append(heading);
      for (const item of basis) appendSource(citations, item);
    }
    for (const item of (Array.isArray(payload.external_links) ? payload.external_links : [])) appendSource(links, item);
  }

  function renderLimitations(payload) {
    const limits = document.querySelector("#limitations");
    clear(limits);
    for (const item of (Array.isArray(payload.limitations) ? payload.limitations : [])) {
      const row = document.createElement("li");
      row.textContent = text(item);
      limits.append(row);
    }
  }

  function render(payload) {
    const labels = {
      search_public_summary: "保育來源", lookup_dive_site: "潛點資料", lookup_nearby_edna: "歷史 eDNA 證據",
      lookup_general_weather: "行政區天氣", link_only: "官方連結", data_insufficient: "資料不足",
      redirect_professional: "專業轉介", refuse: "拒絕", needs_clarification: "需要補充資訊",
    };
    result.hidden = false;
    document.querySelector("#result-label").textContent = labels[payload.presentation] || "研究結果";
    document.querySelector("#result-message").textContent = text(payload.message);
    renderModelSummary(payload);
    renderRecords(payload);
    renderSources(payload);
    renderLimitations(payload);
  }

  function modelOutcome(payload) {
    if (!payload.use_model) return "已完成非生成式研究查詢。";
    if (payload.model_used) return `Gemini RAG 摘要已通過純文字安全檢查；本次程序剩餘額度：${payload.quota_remaining}。`;
    const safeReason = {
      not_model_eligible: "此問題依安全規則不會送往 Gemini。",
      quota_exhausted: "本次程序的 Gemini 額度已用完，已安全回落為非生成式研究結果。",
      provider_timeout: "Gemini 逾時，已安全回落為非生成式研究結果。",
      provider_configuration_missing: "Gemini 目前不可用；仍可使用非生成式研究查詢。",
      provider_configuration_invalid: "Gemini 設定無法安全使用；仍可使用非生成式研究查詢。",
      summary_empty: "Gemini 摘要未通過純文字驗證，已安全回落。",
      summary_too_long: "Gemini 摘要未通過純文字驗證，已安全回落。",
      summary_url_or_markup: "Gemini 摘要未通過純文字驗證，已安全回落。",
      summary_sensitive_or_local_reference: "Gemini 摘要未通過純文字驗證，已安全回落。",
      summary_prompt_injection_residue: "Gemini 摘要未通過純文字驗證，已安全回落。",
      summary_unverified_number: "Gemini 摘要未通過純文字驗證，已安全回落。",
    };
    return safeReason[payload.model_skipped_reason] || "Gemini 本次不可用；已安全回落為非生成式研究結果。";
  }

  async function loadModeStatus() {
    try {
      const response = await fetch("/api/research-chat/status");
      const payload = await response.json();
      modeStatus.textContent = payload.mode_name === "gemini" && payload.status === "ready"
        ? `Gemini RAG 摘要可供明確選用；本次程序剩餘額度：${payload.quota_remaining}。`
        : "Gemini RAG 摘要目前不可用；仍可使用非生成式研究查詢。";
    } catch {
      modeStatus.textContent = "Gemini 狀態無法確認；目前只會顯示非生成式研究證據。";
    }
  }

  async function loadSites() {
    try {
      const response = await fetch("/api/dive-sites");
      const payload = await response.json();
      for (const item of (payload.items || [])) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = text(item.name);
        site.append(option);
      }
    } catch {
      status.textContent = "潛點清單目前無法載入；仍可查詢不需潛點的保育來源。";
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    result.hidden = true;
    status.textContent = useModel.checked ? "Gemini RAG 摘要驗證中…" : "正在依安全規則查詢既有研究證據…";
    const data = {question: document.querySelector("#question").value.trim(), use_model: useModel.checked};
    if (site.value) data.site_id = site.value;
    if (radius.value) data.radius_m = Number(radius.value);
    if (range.value) {
      const start = new Date();
      data.start_at = taipeiIso(start);
      data.end_at = taipeiIso(new Date(start.getTime() + Number(range.value) * 3_600_000));
    }
    try {
      const response = await fetch("/api/research-chat", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error("request");
      render(payload);
      status.textContent = modelOutcome(payload);
    } catch {
      status.textContent = "研究查詢目前無法完成；請稍後再試。";
    }
  });

  loadSites();
  loadModeStatus();
})();
