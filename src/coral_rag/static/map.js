"use strict";

(() => {
  const DIVE_SITES_ENDPOINT = "/api/dive-sites";
  const REPRESENTATIVE_POINT_NOTICE =
    "此座標為景點代表點，不代表下水入口、活動範圍、合法性或安全條件。";
  const RAW_VALUE_MISSING = "原始資料未提供";
  const TAIWAN_OVERVIEW = [23.7, 120.9];
  const ednaTools = globalThis.NearbyEdnaQuery || null;
  const reefCheckTools = globalThis.NearbyReefCheckQuery || null;
  const weatherTools = globalThis.GeneralWeatherQuery || null;
  const WEATHER_VALUE_FIELDS = Object.freeze([
    ["weather", "天氣現象"],
    ["temperature", "溫度"],
    ["probability_of_precipitation", "3 小時降雨機率"],
    ["relative_humidity", "相對濕度"],
    ["wind_speed", "風速"],
    ["wind_direction", "風向"],
    ["dew_point", "露點溫度"],
    ["apparent_temperature", "體感溫度"],
    ["beaufort_scale", "蒲福風級"],
    ["weather_code", "天氣現象代碼"],
    ["weather_description", "天氣預報綜合描述"],
  ]);

  const elements = {
    map: document.getElementById("map"),
    mapStatus: document.getElementById("map-status"),
    dataStatus: document.getElementById("data-status"),
    list: document.getElementById("site-list"),
    count: document.getElementById("site-count"),
    detail: document.getElementById("site-detail"),
    detailName: document.getElementById("detail-name"),
    detailPrompt: document.getElementById("detail-prompt"),
    detailFields: document.getElementById("detail-fields"),
    regionRow: document.getElementById("region-row"),
    regionValue: document.getElementById("region-value"),
    coordinateValue: document.getElementById("coordinate-value"),
    qualityValue: document.getElementById("quality-value"),
    verifiedValue: document.getElementById("verified-value"),
    sourceValue: document.getElementById("source-value"),
    sourceLinkRow: document.getElementById("source-link-row"),
    sourceLink: document.getElementById("source-link"),
    sourceLinkWarning: document.getElementById("source-link-warning"),
    ednaPanel: document.getElementById("edna-panel"),
    ednaForm: document.getElementById("edna-form"),
    ednaRadius: document.getElementById("edna-radius"),
    ednaSubmit: document.getElementById("edna-submit"),
    ednaResultsRegion: document.getElementById("edna-results-region"),
    ednaStatus: document.getElementById("edna-status"),
    ednaSummary: document.getElementById("edna-summary"),
    ednaResults: document.getElementById("edna-results"),
    ednaPagination: document.getElementById("edna-pagination"),
    ednaPrevious: document.getElementById("edna-previous"),
    ednaNext: document.getElementById("edna-next"),
    ednaRange: document.getElementById("edna-range"),
    reefCheckPanel: document.getElementById("reefcheck-panel"),
    reefCheckForm: document.getElementById("reefcheck-form"),
    reefCheckRadius: document.getElementById("reefcheck-radius"),
    reefCheckSubmit: document.getElementById("reefcheck-submit"),
    reefCheckResultsRegion: document.getElementById("reefcheck-results-region"),
    reefCheckStatus: document.getElementById("reefcheck-status"),
    reefCheckSummary: document.getElementById("reefcheck-summary"),
    reefCheckResults: document.getElementById("reefcheck-results"),
    reefCheckPagination: document.getElementById("reefcheck-pagination"),
    reefCheckPrevious: document.getElementById("reefcheck-previous"),
    reefCheckNext: document.getElementById("reefcheck-next"),
    reefCheckRange: document.getElementById("reefcheck-range"),
    weatherPanel: document.getElementById("weather-panel"),
    weatherForm: document.getElementById("weather-form"),
    weatherRange: document.getElementById("weather-range"),
    weatherSubmit: document.getElementById("weather-submit"),
    weatherResultsRegion: document.getElementById("weather-results-region"),
    weatherStatus: document.getElementById("weather-status"),
    weatherQueryWindow: document.getElementById("weather-query-window"),
    weatherSourceDetails: document.getElementById("weather-source-details"),
    weatherResults: document.getElementById("weather-results"),
  };

  let map = null;
  let tileLayer = null;
  let tileFailureReported = false;
  let selectedSite = null;
  let ednaBusy = false;
  let reefCheckBusy = false;
  let weatherBusy = false;
  let currentEdnaOffset = 0;
  let currentEdnaNextOffset = null;
  let currentReefCheckOffset = 0;
  let currentReefCheckNextOffset = null;
  const ednaRequests = ednaTools ? new ednaTools.RequestCoordinator() : null;
  const reefCheckRequests = reefCheckTools ? new reefCheckTools.RequestCoordinator() : null;
  const weatherRequests = weatherTools ? new weatherTools.RequestCoordinator() : null;
  const markerById = new Map();
  const buttonById = new Map();

  function safeText(value, fallback = "未提供") {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    return fallback;
  }

  function safeHttpsUrl(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : null;
    } catch (_error) {
      return null;
    }
  }

  function createSafeLink(label, value) {
    const safeUrl = safeHttpsUrl(value);
    if (!safeUrl) return document.createTextNode(safeText(label, RAW_VALUE_MISSING));
    const link = document.createElement("a");
    link.href = safeUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = safeText(label, safeUrl);
    return link;
  }

  function appendEvidenceField(definitionList, label, value) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    if (value instanceof Node) description.append(value);
    else description.textContent = safeText(value, RAW_VALUE_MISSING);
    row.append(term, description);
    definitionList.append(row);
  }

  function selectedRadius() {
    const radius = Number(elements.ednaRadius.value);
    return ednaTools && ednaTools.isAllowedRadius(radius) ? radius : null;
  }

  function currentEdnaContext() {
    const radius = selectedRadius();
    if (!selectedSite || radius === null) return null;
    return { siteId: safeText(selectedSite.id, ""), radius };
  }

  function updateEdnaControls() {
    const radius = selectedRadius();
    elements.ednaRadius.disabled = !selectedSite || !ednaTools;
    elements.ednaSubmit.disabled = !selectedSite || radius === null || ednaBusy || !ednaTools;
    elements.ednaPrevious.disabled = ednaBusy || currentEdnaOffset <= 0;
    elements.ednaNext.disabled = ednaBusy || currentEdnaNextOffset === null;
  }

  function clearEdnaDisplay() {
    elements.ednaSummary.hidden = true;
    elements.ednaSummary.textContent = "";
    elements.ednaResults.replaceChildren();
    elements.ednaPagination.hidden = true;
    elements.ednaRange.textContent = "";
    currentEdnaOffset = 0;
    currentEdnaNextOffset = null;
  }

  function resetEdnaQuery(message, { resetRadius = false } = {}) {
    if (ednaRequests) ednaRequests.cancel();
    ednaBusy = false;
    elements.ednaResultsRegion.setAttribute("aria-busy", "false");
    if (resetRadius) elements.ednaRadius.value = "";
    clearEdnaDisplay();
    elements.ednaStatus.textContent = message;
    updateEdnaControls();
  }

  function setEdnaBusy(isBusy) {
    ednaBusy = isBusy;
    elements.ednaResultsRegion.setAttribute("aria-busy", isBusy ? "true" : "false");
    updateEdnaControls();
  }

  function selectedReefCheckRadius() {
    const radius = Number(elements.reefCheckRadius.value);
    return reefCheckTools && reefCheckTools.isAllowedRadius(radius) ? radius : null;
  }

  function currentReefCheckContext() {
    const radius = selectedReefCheckRadius();
    if (!selectedSite || radius === null) return null;
    return { siteId: safeText(selectedSite.id, ""), radius };
  }

  function updateReefCheckControls() {
    const radius = selectedReefCheckRadius();
    elements.reefCheckRadius.disabled = !selectedSite || !reefCheckTools;
    elements.reefCheckSubmit.disabled = !selectedSite || radius === null || reefCheckBusy || !reefCheckTools;
    elements.reefCheckPrevious.disabled = reefCheckBusy || currentReefCheckOffset <= 0;
    elements.reefCheckNext.disabled = reefCheckBusy || currentReefCheckNextOffset === null;
  }

  function clearReefCheckDisplay() {
    elements.reefCheckSummary.hidden = true;
    elements.reefCheckSummary.textContent = "";
    elements.reefCheckResults.replaceChildren();
    elements.reefCheckPagination.hidden = true;
    elements.reefCheckRange.textContent = "";
    currentReefCheckOffset = 0;
    currentReefCheckNextOffset = null;
  }

  function resetReefCheckQuery(message, { resetRadius = false } = {}) {
    if (reefCheckRequests) reefCheckRequests.cancel();
    reefCheckBusy = false;
    elements.reefCheckResultsRegion.setAttribute("aria-busy", "false");
    if (resetRadius) elements.reefCheckRadius.value = "";
    clearReefCheckDisplay();
    elements.reefCheckStatus.textContent = message;
    updateReefCheckControls();
  }

  function setReefCheckBusy(isBusy) {
    reefCheckBusy = isBusy;
    elements.reefCheckResultsRegion.setAttribute("aria-busy", isBusy ? "true" : "false");
    updateReefCheckControls();
  }

  function selectedWeatherHours() {
    const hours = Number(elements.weatherRange.value);
    return weatherTools && weatherTools.isAllowedHours(hours) ? hours : null;
  }

  function currentWeatherContext() {
    const hours = selectedWeatherHours();
    if (!selectedSite || hours === null) return null;
    return { siteId: safeText(selectedSite.id, ""), hours };
  }

  function updateWeatherControls() {
    const hours = selectedWeatherHours();
    elements.weatherRange.disabled = !selectedSite || !weatherTools;
    elements.weatherSubmit.disabled = !selectedSite || hours === null || weatherBusy || !weatherTools;
  }

  function clearWeatherDisplay() {
    elements.weatherQueryWindow.hidden = true;
    elements.weatherQueryWindow.textContent = "";
    elements.weatherSourceDetails.hidden = true;
    elements.weatherSourceDetails.replaceChildren();
    elements.weatherResults.replaceChildren();
  }

  function resetWeatherQuery(message, { resetRange = false } = {}) {
    if (weatherRequests) weatherRequests.cancel();
    weatherBusy = false;
    elements.weatherResultsRegion.setAttribute("aria-busy", "false");
    if (resetRange) elements.weatherRange.value = "";
    clearWeatherDisplay();
    elements.weatherStatus.textContent = message;
    updateWeatherControls();
  }

  function setWeatherBusy(isBusy) {
    weatherBusy = isBusy;
    elements.weatherResultsRegion.setAttribute("aria-busy", isBusy ? "true" : "false");
    updateWeatherControls();
  }

  function originalWeatherValue(value) {
    if (!value || typeof value !== "object") return RAW_VALUE_MISSING;
    const raw = safeText(value.value, RAW_VALUE_MISSING);
    const unit = safeText(value.unit, "");
    return unit ? `${raw}（${unit}）` : raw;
  }

  function weatherFieldLabel(key, value) {
    const known = WEATHER_VALUE_FIELDS.find(([field]) => field === key);
    if (known) return known[1];
    const sourceElement = value && typeof value === "object" ? safeText(value.source_element, "") : "";
    return sourceElement ? `原始欄位：${sourceElement}` : `原始欄位：${safeText(key, RAW_VALUE_MISSING)}`;
  }

  function renderWeatherItem(item, resultNumber) {
    const listItem = document.createElement("li");
    const article = document.createElement("article");
    const heading = document.createElement("h3");
    const fields = document.createElement("dl");
    const values = item && typeof item.values === "object" && item.values ? item.values : {};
    const renderedKeys = new Set();
    article.className = "evidence-card";
    fields.className = "evidence-card-fields";
    heading.textContent = `行政區預報時點 ${resultNumber}`;
    appendEvidenceField(fields, "DataTime", item && item.valid_at);
    WEATHER_VALUE_FIELDS.forEach(([key, label]) => {
      appendEvidenceField(fields, label, originalWeatherValue(values[key]));
      renderedKeys.add(key);
    });
    Object.keys(values).sort().forEach((key) => {
      if (!renderedKeys.has(key)) {
        appendEvidenceField(fields, weatherFieldLabel(key, values[key]), originalWeatherValue(values[key]));
      }
    });
    article.append(heading, fields);
    listItem.append(article);
    return listItem;
  }

  function renderWeatherSourceDetails(payload) {
    const source = payload && typeof payload.source === "object" ? payload.source : {};
    const license = source && typeof source.license === "object" ? source.license : {};
    const area = payload && typeof payload.administrative_area === "object" ? payload.administrative_area : {};
    const validPeriod = payload && typeof payload.dataset_valid_period === "object" ? payload.dataset_valid_period : {};
    const freshness = payload && typeof payload.freshness === "object" ? payload.freshness : {};
    const provenance = source && typeof source.provenance === "object" ? source.provenance : {};
    const heading = document.createElement("h3");
    const fields = document.createElement("dl");
    heading.textContent = "來源、行政區與時效";
    appendEvidenceField(fields, "官方縣市／鄉鎮", [area.county, area.district]
      .filter((value) => typeof value === "string" && value.trim()).join("／"));
    appendEvidenceField(fields, "CWA 資料集 ID", source.dataset_id);
    appendEvidenceField(fields, "資料發布時間", source.issued_at);
    appendEvidenceField(fields, "資料更新時間", source.updated_at);
    appendEvidenceField(fields, "資料取得時間", source.retrieved_at);
    appendEvidenceField(fields, "資料有效區間", `${safeText(validPeriod.start_at)} 至 ${safeText(validPeriod.end_at)}`);
    appendEvidenceField(fields, "資料新鮮度狀態", freshness.status);
    appendEvidenceField(fields, "資料來源", createSafeLink(source.name, source.dataset_url));
    appendEvidenceField(fields, "授權", createSafeLink(license.name, license.url));
    appendEvidenceField(fields, "來源與授權標示", source.attribution);
    appendEvidenceField(fields, "原始來源識別", provenance.sha256);
    appendEvidenceField(fields, "原始來源定位方式", provenance.source_file);
    elements.weatherSourceDetails.replaceChildren(heading, fields);
    elements.weatherSourceDetails.hidden = false;
  }

  function emptyWeatherMessage(reason) {
    if (reason === "no_explicit_administrative_mapping") {
      return "此潛點沒有經明確官方行政區對應的一般天氣預報；未改用其他地區資料。";
    }
    if (reason === "no_forecast_data_for_explicit_administrative_mapping") {
      return "此行政區尚無已匯入且可用的一般天氣預報。";
    }
    return "指定時間範圍沒有行政區一般天氣預報。";
  }

  function renderWeatherResults(payload, context) {
    const diveSite = payload && typeof payload.dive_site === "object" ? payload.dive_site : null;
    if (!payload || !diveSite || diveSite.id !== context.siteId || !Array.isArray(payload.items)) {
      throw new TypeError("Unexpected general weather response shape");
    }
    if (payload.status === "empty") {
      elements.weatherResults.replaceChildren();
      elements.weatherSourceDetails.hidden = true;
      elements.weatherSourceDetails.replaceChildren();
      elements.weatherStatus.textContent = emptyWeatherMessage(payload.reason);
      return;
    }
    if (payload.status !== "ok" || !payload.source || !payload.administrative_area || !payload.freshness) {
      throw new TypeError("Incomplete general weather response");
    }
    renderWeatherSourceDetails(payload);
    elements.weatherResults.replaceChildren(
      ...payload.items.map((item, index) => renderWeatherItem(item, index + 1)),
    );
    elements.weatherStatus.textContent = payload.items.length
      ? `已載入 ${payload.items.length} 筆行政區一般天氣預報時點。`
      : "指定時間範圍沒有行政區一般天氣預報。";
  }

  async function queryGeneralWeather() {
    if (!weatherTools || !weatherRequests) {
      resetWeatherQuery("行政區一般天氣預報查詢元件無法載入；潛點基本資料仍可使用。");
      return;
    }
    const context = currentWeatherContext();
    if (!selectedSite) {
      resetWeatherQuery("尚未查詢。請先選擇潛點與預報範圍。");
      return;
    }
    if (!context) {
      resetWeatherQuery("預報範圍無效；請選擇未來 24、48 或 72 小時。");
      return;
    }

    let request;
    try {
      request = weatherTools.buildUrl(context.siteId, context.hours);
    } catch (_error) {
      resetWeatherQuery("預報範圍無效；請重新選擇後再試。");
      return;
    }

    const token = weatherRequests.start(context);
    clearWeatherDisplay();
    elements.weatherQueryWindow.hidden = false;
    elements.weatherQueryWindow.textContent = `本次查詢範圍：${request.startAt} 至 ${request.endAt}（${request.timeZone}）。`;
    setWeatherBusy(true);
    elements.weatherStatus.textContent = "正在查詢行政區一般天氣預報…";

    try {
      const response = await fetch(request.url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal: token.signal,
      });
      if (!weatherRequests.isCurrent(token, currentWeatherContext())) return;
      if (response.status === 404) {
        elements.weatherStatus.textContent = "找不到目前選取的潛點（404）；請重新選擇潛點。";
        return;
      }
      if (response.status === 422) {
        elements.weatherStatus.textContent = "預報時間範圍無效（422）；請重新選擇範圍後再試。";
        return;
      }
      if (response.status === 503) {
        elements.weatherStatus.textContent = "行政區天氣資料尚未更新、已過期或來源驗證失敗（503）；未顯示任何舊預報值。";
        return;
      }
      if (!response.ok) {
        elements.weatherStatus.textContent = `行政區天氣 API 查詢失敗（HTTP ${response.status}）；請稍後重試。`;
        return;
      }
      try {
        const payload = await response.json();
        if (!weatherRequests.isCurrent(token, currentWeatherContext())) return;
        renderWeatherResults(payload, context);
      } catch (_error) {
        if (!weatherRequests.isCurrent(token, currentWeatherContext())) return;
        elements.weatherSourceDetails.hidden = true;
        elements.weatherSourceDetails.replaceChildren();
        elements.weatherResults.replaceChildren();
        elements.weatherStatus.textContent = "行政區天氣 API 回應格式無法辨識；未顯示任何預報值。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!weatherRequests.isCurrent(token, currentWeatherContext())) return;
      elements.weatherSourceDetails.hidden = true;
      elements.weatherSourceDetails.replaceChildren();
      elements.weatherResults.replaceChildren();
      elements.weatherStatus.textContent = "無法連線到行政區天氣 API；請確認服務狀態後重試。";
    } finally {
      if (weatherRequests.isCurrent(token, currentWeatherContext())) {
        weatherRequests.finish(token);
        setWeatherBusy(false);
      }
    }
  }

  function coordinatesFor(site) {
    const latitude = Number(site.latitude);
    const longitude = Number(site.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
    if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return null;
    return [latitude, longitude];
  }

  function initializeMap() {
    if (!window.L) {
      elements.map.classList.add("is-unavailable");
      elements.map.replaceChildren();
      const fallback = document.createElement("p");
      fallback.textContent = "互動地圖函式庫載入失敗；請使用右側或下方的潛點清單。";
      elements.map.append(fallback);
      elements.mapStatus.textContent = "地圖無法使用；潛點文字清單仍可操作。";
      return;
    }

    elements.map.replaceChildren();
    map = window.L.map(elements.map, {
      center: TAIWAN_OVERVIEW,
      zoom: 7,
      minZoom: 5,
      maxZoom: 18,
      scrollWheelZoom: false,
    });
    tileLayer = window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    });
    tileLayer.on("tileerror", () => {
      if (tileFailureReported) return;
      tileFailureReported = true;
      elements.mapStatus.textContent = "底圖圖磚無法載入；潛點清單與基本資訊仍可使用。";
    });
    tileLayer.addTo(map);
    elements.mapStatus.textContent = "互動地圖已載入；可用標記或文字清單選擇潛點。";
  }

  function displayRegion(site) {
    const area = site && typeof site.administrative_area === "object"
      ? site.administrative_area
      : {};
    return [area.county, area.district]
      .filter((value) => typeof value === "string" && value.trim())
      .map((value) => value.trim())
      .join("／");
  }

  function setSourceLink(reference) {
    const safeUrl = safeHttpsUrl(reference);
    elements.sourceLink.removeAttribute("href");
    if (safeUrl) {
      elements.sourceLink.href = safeUrl;
      elements.sourceLinkRow.hidden = false;
      elements.sourceLinkWarning.hidden = true;
    } else {
      elements.sourceLinkRow.hidden = true;
      elements.sourceLinkWarning.hidden = false;
    }
  }

  function recordLocatorText(source) {
    const locator = source && typeof source.record_locator === "object"
      ? source.record_locator
      : {};
    const parts = [];
    if (typeof locator.source_file === "string" && locator.source_file.trim()) {
      parts.push(`source_file=${locator.source_file.trim()}`);
    }
    if (locator.source_row !== null && locator.source_row !== undefined) {
      parts.push(`source_row=${safeText(locator.source_row, RAW_VALUE_MISSING)}`);
    }
    if (typeof locator.row_numbering === "string" && locator.row_numbering.trim()) {
      parts.push(locator.row_numbering.trim());
    }
    return parts.length ? parts.join("；") : RAW_VALUE_MISSING;
  }

  function renderEdnaItem(item, resultNumber) {
    const source = item && typeof item.source === "object" ? item.source : {};
    const license = source && typeof source.license === "object" ? source.license : {};
    const taxon = item && typeof item.taxon === "object" ? item.taxon : {};
    const listItem = document.createElement("li");
    const article = document.createElement("article");
    const heading = document.createElement("h3");
    const fields = document.createElement("dl");
    article.className = "evidence-card";
    fields.className = "evidence-card-fields";
    heading.textContent = `歷史 eDNA 檢出紀錄 ${resultNumber}`;

    const distance = Number(item.distance_m);
    appendEvidenceField(
      fields,
      "距代表點距離",
      Number.isFinite(distance) ? `${distance} 公尺` : RAW_VALUE_MISSING,
    );
    appendEvidenceField(fields, "採樣日期", item.sampled_at);
    appendEvidenceField(fields, "原始站點名稱或 ID", item.station_id);
    appendEvidenceField(fields, "原始分類群（scientific_name）", taxon.scientific_name);
    appendEvidenceField(fields, "原始分類群（chinese_name）", taxon.chinese_name);
    appendEvidenceField(fields, "原始科別（family_name）", taxon.family_name);
    appendEvidenceField(fields, "原始科別（chinese_family）", taxon.chinese_family);
    if (item.depth_m !== null && item.depth_m !== undefined && safeText(item.depth_m, "")) {
      appendEvidenceField(fields, "採樣深度", `${safeText(item.depth_m)} 公尺`);
    }
    appendEvidenceField(fields, "原始來源紀錄 ID", item.source_record_id);
    appendEvidenceField(fields, "來源定位方式", recordLocatorText(source));
    appendEvidenceField(
      fields,
      "資料來源",
      createSafeLink(source.name, source.dataset_url),
    );
    appendEvidenceField(
      fields,
      "授權",
      createSafeLink(license.name, license.url),
    );
    appendEvidenceField(fields, "來源與授權標示", license.attribution);

    article.append(heading, fields);
    listItem.append(article);
    return listItem;
  }

  function renderEdnaResults(payload, context) {
    const pagination = payload && typeof payload.pagination === "object" ? payload.pagination : null;
    const query = payload && typeof payload.query === "object" ? payload.query : null;
    const diveSite = payload && typeof payload.dive_site === "object" ? payload.dive_site : null;
    if (
      !pagination
      || !query
      || !diveSite
      || !Array.isArray(payload.items)
      || diveSite.id !== context.siteId
      || Number(query.radius_m) !== context.radius
      || !Number.isInteger(pagination.offset)
      || !Number.isInteger(pagination.matched_count)
    ) {
      throw new TypeError("Unexpected nearby eDNA response shape");
    }

    const items = payload.items;
    const offset = pagination.offset;
    const matchedCount = pagination.matched_count;
    currentEdnaOffset = offset;
    currentEdnaNextOffset = pagination.has_more && Number.isInteger(pagination.next_offset)
      ? pagination.next_offset
      : null;
    elements.ednaResults.replaceChildren(
      ...items.map((item, index) => renderEdnaItem(item, offset + index + 1)),
    );
    elements.ednaSummary.hidden = false;
    elements.ednaSummary.textContent = `本次查詢半徑：${context.radius} 公尺；符合條件總筆數：${matchedCount} 筆。`;

    if (items.length === 0) {
      elements.ednaStatus.textContent = "指定半徑內沒有可回查的附近歷史 eDNA 紀錄。";
      elements.ednaPagination.hidden = true;
      elements.ednaRange.textContent = "0 筆";
      updateEdnaControls();
      return;
    }

    const rangeStart = offset + 1;
    const rangeEnd = offset + items.length;
    elements.ednaStatus.textContent = "歷史 eDNA 檢出紀錄已載入；以下內容是附近歷史採樣證據。";
    elements.ednaRange.textContent = `顯示第 ${rangeStart}–${rangeEnd} 筆，共 ${matchedCount} 筆`;
    elements.ednaPagination.hidden = false;
    updateEdnaControls();
  }

  async function queryNearbyEdna(offset = 0) {
    if (!ednaTools || !ednaRequests) {
      resetEdnaQuery("附近歷史 eDNA 查詢元件無法載入；潛點基本資料仍可使用。");
      return;
    }
    const context = currentEdnaContext();
    if (!selectedSite) {
      resetEdnaQuery("尚未查詢。請先選擇潛點與查詢半徑。");
      return;
    }
    if (!context) {
      resetEdnaQuery("查詢半徑無效；請從清單選擇 250 至 5,000 公尺的半徑。");
      return;
    }

    let url;
    try {
      url = ednaTools.buildUrl(context.siteId, context.radius, offset);
    } catch (_error) {
      resetEdnaQuery("查詢半徑或分頁位置無效；請重新選擇半徑後再試。");
      return;
    }

    const token = ednaRequests.start(context);
    clearEdnaDisplay();
    setEdnaBusy(true);
    elements.ednaStatus.textContent = "正在查詢附近歷史 eDNA 證據…";

    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        signal: token.signal,
      });
      if (!ednaRequests.isCurrent(token, currentEdnaContext())) return;
      if (response.status === 404) {
        elements.ednaStatus.textContent = "找不到目前選取的潛點（404）；請重新選擇潛點。";
        return;
      }
      if (response.status === 422) {
        elements.ednaStatus.textContent = "查詢半徑或分頁參數無效（422）；請重新選擇半徑後再試。";
        return;
      }
      if (response.status === 503) {
        elements.ednaStatus.textContent = "eDNA 結構化資料庫版本尚未就緒（503）；請完成重建後再試。";
        return;
      }
      if (!response.ok) {
        elements.ednaStatus.textContent = `歷史 eDNA API 查詢失敗（HTTP ${response.status}）；請稍後重試。`;
        return;
      }

      let payload;
      try {
        payload = await response.json();
        if (!ednaRequests.isCurrent(token, currentEdnaContext())) return;
        renderEdnaResults(payload, context);
      } catch (_error) {
        if (!ednaRequests.isCurrent(token, currentEdnaContext())) return;
        clearEdnaDisplay();
        elements.ednaStatus.textContent = "歷史 eDNA API 回應格式無法辨識；未顯示任何結果。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!ednaRequests.isCurrent(token, currentEdnaContext())) return;
      clearEdnaDisplay();
      elements.ednaStatus.textContent = "無法連線到歷史 eDNA API；請確認服務狀態後重試。";
    } finally {
      if (ednaRequests.isCurrent(token, currentEdnaContext())) {
        ednaRequests.finish(token);
        setEdnaBusy(false);
      }
    }
  }

  function reefCheckLocatorText(source) {
    const locator = source && typeof source.record_locator === "object" ? source.record_locator : {};
    const ids = [locator.event_id, locator.occurrence_id]
      .filter((value) => typeof value === "string" && value.trim());
    const method = typeof locator.locator_method === "string" ? locator.locator_method : "";
    return [ids.join(" / "), method].filter(Boolean).join("；") || RAW_VALUE_MISSING;
  }

  function renderReefCheckItem(item, resultNumber) {
    const event = item && typeof item.event === "object" ? item.event : {};
    const observation = item && typeof item.observation === "object" ? item.observation : null;
    const source = item && typeof item.source === "object" ? item.source : {};
    const license = source && typeof source.license === "object" ? source.license : {};
    const position = event && typeof event.position === "object" ? event.position : {};
    const taxon = observation && typeof observation.taxon === "object" ? observation.taxon : {};
    const listItem = document.createElement("li");
    const article = document.createElement("article");
    const heading = document.createElement("h3");
    const fields = document.createElement("dl");
    article.className = "evidence-card";
    fields.className = "evidence-card-fields";
    heading.textContent = `Reef Check 歷史目視紀錄 ${resultNumber}`;
    const distance = Number(item && item.distance_m);
    appendEvidenceField(fields, "距代表點距離", Number.isFinite(distance) ? `${distance} 公尺` : RAW_VALUE_MISSING);
    appendEvidenceField(fields, "調查日期", event.surveyed_at);
    appendEvidenceField(fields, "日期精度", event.date_precision);
    appendEvidenceField(fields, "原始事件 ID", event.event_id);
    appendEvidenceField(fields, "原始地點名稱", event.locality);
    appendEvidenceField(fields, "調查方法", event.sampling_protocol);
    if (event.depth_m && (event.depth_m.minimum !== null || event.depth_m.maximum !== null)) {
      appendEvidenceField(fields, "原始深度範圍", `${safeText(event.depth_m.minimum)} 至 ${safeText(event.depth_m.maximum)} 公尺`);
    }
    if (position.coordinate_uncertainty_m !== null && position.coordinate_uncertainty_m !== undefined) {
      appendEvidenceField(fields, "座標不確定度", `${safeText(position.coordinate_uncertainty_m)} 公尺`);
    }
    if (item && item.data_quality !== null && item.data_quality !== undefined) {
      appendEvidenceField(fields, "資料品質", item.data_quality);
    }
    if (observation) {
      appendEvidenceField(fields, "原始觀測 ID", observation.occurrence_id);
      appendEvidenceField(fields, "原始觀測類型", observation.basis_of_record);
      appendEvidenceField(fields, "原始分類群（學名）", taxon.scientific_name);
      appendEvidenceField(fields, "原始分類群階層", taxon.taxon_rank);
      appendEvidenceField(fields, "原始俗名", taxon.vernacular_name);
      if (observation.raw_value !== null && observation.raw_value !== undefined) {
        const unit = safeText(observation.raw_unit, "");
        appendEvidenceField(fields, "原始數值", unit ? `${safeText(observation.raw_value)} ${unit}` : observation.raw_value);
      }
    }
    appendEvidenceField(fields, "來源紀錄定位", reefCheckLocatorText(source));
    appendEvidenceField(fields, "資料來源", createSafeLink(source.name, source.dataset_url));
    appendEvidenceField(fields, "授權", createSafeLink(license.name, license.url));
    appendEvidenceField(fields, "顯名", license.attribution);
    article.append(heading, fields);
    listItem.append(article);
    return listItem;
  }

  function renderReefCheckResults(payload, context) {
    const pagination = payload && typeof payload.pagination === "object" ? payload.pagination : null;
    const query = payload && typeof payload.query === "object" ? payload.query : null;
    const diveSite = payload && typeof payload.dive_site === "object" ? payload.dive_site : null;
    const gate = payload && typeof payload.license_gate === "object" ? payload.license_gate : null;
    if (!pagination || !query || !diveSite || !gate || !Array.isArray(payload.items)
      || payload.evidence_type !== "nearby_historical_reef_check_visual_survey_evidence"
      || gate.status !== "enabled_for_local_noncommercial_research"
      || diveSite.id !== context.siteId || Number(query.radius_m) !== context.radius
      || !Number.isInteger(pagination.offset) || !Number.isInteger(pagination.matched_count)) {
      throw new TypeError("Unexpected nearby Reef Check response shape");
    }
    const items = payload.items;
    const offset = pagination.offset;
    const matchedCount = pagination.matched_count;
    currentReefCheckOffset = offset;
    currentReefCheckNextOffset = pagination.has_more && Number.isInteger(pagination.next_offset)
      ? pagination.next_offset : null;
    elements.reefCheckResults.replaceChildren(
      ...items.map((item, index) => renderReefCheckItem(item, offset + index + 1)),
    );
    elements.reefCheckSummary.hidden = false;
    elements.reefCheckSummary.textContent = `本次查詢半徑：${context.radius} 公尺；符合的歷史目視紀錄：${matchedCount} 筆。`;
    if (items.length === 0) {
      elements.reefCheckStatus.textContent = "指定半徑內沒有可回查的歷史 Reef Check 目視紀錄。";
      elements.reefCheckPagination.hidden = true;
      elements.reefCheckRange.textContent = "0 筆";
      updateReefCheckControls();
      return;
    }
    const rangeStart = offset + 1;
    const rangeEnd = offset + items.length;
    elements.reefCheckStatus.textContent = "Reef Check 歷史目視紀錄已載入；僅限本機非商業研究使用。";
    elements.reefCheckRange.textContent = `顯示第 ${rangeStart}–${rangeEnd} 筆，共 ${matchedCount} 筆`;
    elements.reefCheckPagination.hidden = false;
    updateReefCheckControls();
  }

  async function queryNearbyReefCheck(offset = 0) {
    if (!reefCheckTools || !reefCheckRequests) {
      resetReefCheckQuery("Reef Check 查詢元件無法載入；不會顯示任何觀測資料。");
      return;
    }
    const context = currentReefCheckContext();
    if (!selectedSite) {
      resetReefCheckQuery("尚未查詢。請先選擇潛點與查詢半徑。");
      return;
    }
    if (!context) {
      resetReefCheckQuery("查詢半徑無效；請從 250 至 5,000 公尺的選項中選擇。");
      return;
    }
    let url;
    try {
      url = reefCheckTools.buildUrl(context.siteId, context.radius, offset);
    } catch (_error) {
      resetReefCheckQuery("查詢半徑或分頁參數無效；不會顯示任何觀測資料。");
      return;
    }
    const token = reefCheckRequests.start(context);
    clearReefCheckDisplay();
    setReefCheckBusy(true);
    elements.reefCheckStatus.textContent = "正在查詢附近歷史 Reef Check 目視證據…";
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store", signal: token.signal,
      });
      if (!reefCheckRequests.isCurrent(token, currentReefCheckContext())) return;
      if (response.status === 403) {
        clearReefCheckDisplay();
        elements.reefCheckStatus.textContent = "Reef Check 僅在已啟用的本機非商業研究模式中可用；未顯示任何觀測資料。";
        return;
      }
      if (response.status === 404) {
        elements.reefCheckStatus.textContent = "找不到目前選取的潛點（404）；請重新選擇潛點。";
        return;
      }
      if (response.status === 422) {
        elements.reefCheckStatus.textContent = "查詢半徑或分頁參數無效（422）；請重新選擇。";
        return;
      }
      if (response.status === 503) {
        elements.reefCheckStatus.textContent = "Reef Check 結構化資料暫時無法使用（503）；未顯示任何觀測資料。";
        return;
      }
      if (!response.ok) {
        elements.reefCheckStatus.textContent = `Reef Check API 查詢失敗（HTTP ${response.status}）；請稍後再試。`;
        return;
      }
      try {
        const payload = await response.json();
        if (!reefCheckRequests.isCurrent(token, currentReefCheckContext())) return;
        renderReefCheckResults(payload, context);
      } catch (_error) {
        if (!reefCheckRequests.isCurrent(token, currentReefCheckContext())) return;
        clearReefCheckDisplay();
        elements.reefCheckStatus.textContent = "Reef Check API 回應格式無法驗證；未顯示任何觀測資料。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!reefCheckRequests.isCurrent(token, currentReefCheckContext())) return;
      clearReefCheckDisplay();
      elements.reefCheckStatus.textContent = "無法連線至 Reef Check API；未顯示任何觀測資料。";
    } finally {
      if (reefCheckRequests.isCurrent(token, currentReefCheckContext())) {
        reefCheckRequests.finish(token);
        setReefCheckBusy(false);
      }
    }
  }

  function selectSite(site, origin) {
    const id = safeText(site.id, "");
    const siteChanged = !selectedSite || safeText(selectedSite.id, "") !== id;
    const coordinates = coordinatesFor(site);
    const source = site && typeof site.source === "object" ? site.source : {};
    const region = displayRegion(site);
    selectedSite = site;

    if (siteChanged) {
      resetEdnaQuery(
        `已選擇 ${safeText(site.name)}。請先選擇查詢半徑，再按下「查詢附近歷史證據」。`,
        { resetRadius: true },
      );
      resetReefCheckQuery(
        `已選擇 ${safeText(site.name)}。請主動選擇查詢半徑，再按「查詢附近歷史目視證據」。`,
        { resetRadius: true },
      );
      resetWeatherQuery(
        `已選擇 ${safeText(site.name)}。請先選擇預報範圍，再按下「查看行政區天氣預報」。`,
        { resetRange: true },
      );
    }

    elements.detailName.textContent = safeText(site.name);
    elements.detailPrompt.hidden = true;
    elements.detailFields.hidden = false;
    elements.regionRow.hidden = !region;
    elements.regionValue.textContent = region;
    elements.coordinateValue.textContent = coordinates
      ? `${coordinates[0].toFixed(6)}, ${coordinates[1].toFixed(6)}`
      : "座標格式無法顯示";
    elements.qualityValue.textContent = safeText(site.data_quality);
    elements.verifiedValue.textContent = safeText(site.last_verified_at);
    elements.sourceValue.textContent = safeText(source.name);
    setSourceLink(source.reference);

    buttonById.forEach((button, buttonId) => {
      button.setAttribute("aria-current", buttonId === id ? "true" : "false");
    });
    markerById.forEach((marker, markerId) => {
      const markerElement = marker.getElement();
      if (markerElement) markerElement.classList.toggle("is-selected", markerId === id);
    });

    const button = buttonById.get(id);
    if (origin === "marker" && button) button.scrollIntoView({ block: "nearest" });

    const marker = markerById.get(id);
    if (origin === "list" && map && marker && coordinates) {
      map.setView(coordinates, Math.max(map.getZoom(), 13));
      marker.getElement()?.focus();
    }

    if (origin === "marker") elements.detail.focus({ preventScroll: true });
  }

  function addMarker(site) {
    if (!map || !window.L) return null;
    const coordinates = coordinatesFor(site);
    if (!coordinates) return null;
    const id = safeText(site.id, "");
    const name = safeText(site.name);
    const icon = window.L.divIcon({
      className: "site-marker",
      iconSize: [28, 28],
      iconAnchor: [14, 28],
    });
    const marker = window.L.marker(coordinates, {
      icon,
      keyboard: true,
      title: name,
      alt: `${name}代表點`,
      riseOnHover: true,
    });
    marker.on("click", () => selectSite(site, "marker"));
    marker.addTo(map);
    markerById.set(id, marker);
    return marker;
  }

  function addListItem(site) {
    const id = safeText(site.id, "");
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = safeText(site.name);
    button.setAttribute("aria-current", "false");
    button.addEventListener("click", () => selectSite(site, "list"));
    item.append(button);
    elements.list.append(item);
    buttonById.set(id, button);
  }

  function renderSites(items) {
    elements.list.replaceChildren();
    markerById.clear();
    buttonById.clear();
    const bounds = [];

    items.forEach((site) => {
      addListItem(site);
      const marker = addMarker(site);
      if (marker) bounds.push(marker.getLatLng());
    });

    elements.count.textContent = `${items.length} 筆`;
    elements.dataStatus.textContent = `已載入 ${items.length} 筆經來源核對的潛點基本資料。`;
    if (map && bounds.length) map.fitBounds(bounds, { padding: [34, 34], maxZoom: 13 });
  }

  function showEmptyState() {
    elements.list.replaceChildren();
    elements.count.textContent = "0 筆";
    elements.dataStatus.textContent = "目前沒有已驗證潛點可顯示；系統不會以假資料補足。";
  }

  function showLoadError(message) {
    elements.list.replaceChildren();
    elements.count.textContent = "";
    elements.dataStatus.textContent = message;
  }

  async function loadSites() {
    try {
      const response = await fetch(DIVE_SITES_ENDPOINT, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (response.status === 503) {
        showLoadError("資料庫版本尚未就緒（503）；請完成結構化資料庫重建後再試。地圖未加入任何替代資料。");
        return;
      }
      if (!response.ok) {
        showLoadError(`潛點 API 連線失敗（HTTP ${response.status}）；請稍後重試。`);
        return;
      }
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.items)) {
        showLoadError("潛點 API 回應格式無法辨識；請聯絡系統維護者。地圖未加入任何替代資料。");
        return;
      }
      if (payload.items.length === 0) {
        showEmptyState();
        return;
      }
      renderSites(payload.items);
    } catch (_error) {
      showLoadError("無法連線到潛點 API；請確認服務狀態後重試。文字清單目前也無資料可顯示。");
    }
  }

  elements.ednaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    queryNearbyEdna(0);
  });
  elements.ednaRadius.addEventListener("change", () => {
    const radius = selectedRadius();
    const message = radius === null
      ? "尚未查詢。請選擇查詢半徑，再按下「查詢附近歷史證據」。"
      : `已選擇 ${radius} 公尺半徑；請按下「查詢附近歷史證據」。`;
    resetEdnaQuery(message);
  });
  elements.ednaPrevious.addEventListener("click", () => {
    if (!ednaTools) return;
    queryNearbyEdna(Math.max(0, currentEdnaOffset - ednaTools.PAGE_SIZE));
  });
  elements.ednaNext.addEventListener("click", () => {
    if (currentEdnaNextOffset !== null) queryNearbyEdna(currentEdnaNextOffset);
  });
  elements.reefCheckForm.addEventListener("submit", (event) => {
    event.preventDefault();
    queryNearbyReefCheck(0);
  });
  elements.reefCheckRadius.addEventListener("change", () => {
    const radius = selectedReefCheckRadius();
    const message = radius === null
      ? "尚未查詢。請選擇查詢半徑，再按「查詢附近歷史目視證據」。"
      : `已選擇 ${radius} 公尺半徑；請按「查詢附近歷史目視證據」。`;
    resetReefCheckQuery(message);
  });
  elements.reefCheckPrevious.addEventListener("click", () => {
    if (!reefCheckTools) return;
    queryNearbyReefCheck(Math.max(0, currentReefCheckOffset - reefCheckTools.PAGE_SIZE));
  });
  elements.reefCheckNext.addEventListener("click", () => {
    if (currentReefCheckNextOffset !== null) queryNearbyReefCheck(currentReefCheckNextOffset);
  });
  elements.weatherForm.addEventListener("submit", (event) => {
    event.preventDefault();
    queryGeneralWeather();
  });
  elements.weatherRange.addEventListener("change", () => {
    const hours = selectedWeatherHours();
    const message = hours === null
      ? "尚未查詢。請選擇預報範圍，再按下「查看行政區天氣預報」。"
      : `已選擇未來 ${hours} 小時；請按下「查看行政區天氣預報」。`;
    resetWeatherQuery(message);
  });

  if (!ednaTools) {
    resetEdnaQuery("附近歷史 eDNA 查詢元件無法載入；潛點基本資料仍可使用。");
  } else {
    updateEdnaControls();
  }
  if (!reefCheckTools) {
    resetReefCheckQuery("Reef Check 查詢元件無法載入；不會顯示任何觀測資料。");
  } else {
    updateReefCheckControls();
  }
  if (!weatherTools) {
    resetWeatherQuery("行政區一般天氣預報查詢元件無法載入；潛點基本資料仍可使用。");
  } else {
    updateWeatherControls();
  }

  const notice = document.querySelector(".representative-point-notice");
  if (notice) notice.textContent = REPRESENTATIVE_POINT_NOTICE;
  initializeMap();
  loadSites();
})();
