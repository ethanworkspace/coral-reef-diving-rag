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
  const profileTools = globalThis.DiveSiteProfileQuery || null;
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
    profileDrawer: document.getElementById("site-profile-drawer"),
    profileToggle: document.getElementById("profile-toggle"),
    profileContent: document.getElementById("profile-drawer-content"),
    profileStatus: document.getElementById("profile-status"),
    profileDetails: document.getElementById("profile-details"),
    profileMediaState: document.getElementById("profile-media-state"),
    profileBasicFields: document.getElementById("profile-basic-fields"),
    profileIntroductionText: document.getElementById("profile-introduction-text"),
    profileIntroductionSources: document.getElementById("profile-introduction-sources"),
    profileEnvironmentText: document.getElementById("profile-environment-text"),
    profileEnvironmentSources: document.getElementById("profile-environment-sources"),
    profileActivityText: document.getElementById("profile-activity-text"),
    profileActivitySources: document.getElementById("profile-activity-sources"),
    profileEdnaStatus: document.getElementById("profile-edna-status"),
    profileEdnaSources: document.getElementById("profile-edna-sources"),
    profileReefCheckStatus: document.getElementById("profile-reefcheck-status"),
    profileReefCheckSources: document.getElementById("profile-reefcheck-sources"),
    profileWeatherStatus: document.getElementById("profile-weather-status"),
    profileLimitations: document.getElementById("profile-limitations"),
    profileToEdna: document.getElementById("profile-to-edna"),
    profileToReefCheck: document.getElementById("profile-to-reefcheck"),
    profileToWeather: document.getElementById("profile-to-weather"),
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
    nearbyMarineSection: document.getElementById("profile-nearby-marine"),
    nearbyMarineRefresh: document.getElementById("nearby-marine-refresh"),
    nearbyMarineStatus: document.getElementById("nearby-marine-status"),
    nearbyMarineContent: document.getElementById("nearby-marine-content"),
    nearbyMarineMetaFields: document.getElementById("nearby-marine-meta-fields"),
    nearbyMarineItems: document.getElementById("nearby-marine-items"),
    nearbyMarineDisclaimers: document.getElementById("nearby-marine-disclaimers"),
    speciesReferenceSection: document.getElementById("profile-species-reference"),
    speciesReferenceRefresh: document.getElementById("species-reference-refresh"),
    speciesReferenceStatus: document.getElementById("species-reference-status"),
    speciesReferenceContent: document.getElementById("species-reference-content"),
    speciesReferenceList: document.getElementById("species-reference-list"),
    speciesReferenceDisclaimers: document.getElementById("species-reference-disclaimers"),
    profileQaSection: document.getElementById("profile-qa"),
    profileQaForm: document.getElementById("profile-qa-form"),
    profileQaInput: document.getElementById("profile-qa-input"),
    profileQaCounter: document.getElementById("profile-qa-counter"),
    profileQaSubmit: document.getElementById("profile-qa-submit"),
    profileQaStatus: document.getElementById("profile-qa-status"),
    profileQaAnswerContainer: document.getElementById("profile-qa-answer-container"),
    profileQaAnswerText: document.getElementById("profile-qa-answer-text"),
    profileQaCitationsSection: document.getElementById("profile-qa-citations-section"),
    profileQaCitationsList: document.getElementById("profile-qa-citations-list"),
    profileEdnaQaSection: document.getElementById("profile-edna-qa"),
    profileEdnaQaForm: document.getElementById("profile-edna-qa-form"),
    profileEdnaQaRadius: document.getElementById("profile-edna-qa-radius"),
    profileEdnaQaInput: document.getElementById("profile-edna-qa-input"),
    profileEdnaQaCounter: document.getElementById("profile-edna-qa-counter"),
    profileEdnaQaSubmit: document.getElementById("profile-edna-qa-submit"),
    profileEdnaQaStatus: document.getElementById("profile-edna-qa-status"),
    profileEdnaQaAnswerContainer: document.getElementById("profile-edna-qa-answer-container"),
    profileEdnaQaAnswerText: document.getElementById("profile-edna-qa-answer-text"),
    profileEdnaQaCitationsSection: document.getElementById("profile-edna-qa-citations-section"),
    profileEdnaQaCitationsList: document.getElementById("profile-edna-qa-citations-list"),
  };

  let map = null;
  let tileLayer = null;
  let tileFailureReported = false;
  let selectedSite = null;
  let ednaBusy = false;
  let reefCheckBusy = false;
  let weatherBusy = false;
  let profileBusy = false;
  let nearbyMarineBusy = false;
  let currentEdnaOffset = 0;
  let currentEdnaNextOffset = null;
  let currentReefCheckOffset = 0;
  let currentReefCheckNextOffset = null;
  const ednaRequests = ednaTools ? new ednaTools.RequestCoordinator() : null;
  const reefCheckRequests = reefCheckTools ? new reefCheckTools.RequestCoordinator() : null;
  const weatherRequests = weatherTools ? new weatherTools.RequestCoordinator() : null;
  const profileRequests = profileTools ? new profileTools.RequestCoordinator() : null;

  class NearbyMarineRequestCoordinator {
    constructor() {
      this.sequence = 0;
      this.controller = null;
    }

    start(siteId) {
      this.cancel();
      this.sequence += 1;
      this.controller = new AbortController();
      return { sequence: this.sequence, siteId, signal: this.controller.signal };
    }

    cancel() {
      if (this.controller) {
        this.controller.abort();
        this.controller = null;
      }
    }

    isCurrent(token, currentSiteId) {
      return Boolean(
        token &&
        token.sequence === this.sequence &&
        token.siteId === currentSiteId
      );
    }

    finish(token) {
      if (token && token.sequence === this.sequence) {
        this.controller = null;
      }
    }
  }

  class SpeciesReferenceRequestCoordinator {
    constructor() {
      this.sequence = 0;
      this.controller = null;
    }

    start(siteId) {
      this.cancel();
      this.sequence += 1;
      this.controller = new AbortController();
      return { sequence: this.sequence, siteId, signal: this.controller.signal };
    }

    cancel() {
      if (this.controller) {
        this.controller.abort();
        this.controller = null;
      }
    }

    isCurrent(token, currentSiteId) {
      return Boolean(
        token &&
        token.sequence === this.sequence &&
        token.siteId === currentSiteId
      );
    }

    finish(token) {
      if (token && token.sequence === this.sequence) {
        this.controller = null;
      }
    }
  }

  class ProfileQaRequestCoordinator {
    constructor() {
      this.sequence = 0;
      this.controller = null;
    }

    start(siteId) {
      this.cancel();
      this.sequence += 1;
      this.controller = new AbortController();
      return { sequence: this.sequence, siteId, signal: this.controller.signal };
    }

    cancel() {
      if (this.controller) {
        this.controller.abort();
        this.controller = null;
      }
    }

    isCurrent(token, currentSiteId) {
      return Boolean(
        token &&
        token.sequence === this.sequence &&
        token.siteId === currentSiteId &&
        !token.signal?.aborted
      );
    }

    finish(token) {
      if (token && token.sequence === this.sequence) {
        this.controller = null;
      }
    }
  }

  class ProfileEdnaQaRequestCoordinator {
    constructor() {
      this.sequence = 0;
      this.controller = null;
    }

    start(siteId) {
      this.cancel();
      this.sequence += 1;
      this.controller = new AbortController();
      return { sequence: this.sequence, siteId, signal: this.controller.signal };
    }

    cancel() {
      if (this.controller) {
        this.controller.abort();
        this.controller = null;
      }
    }

    isCurrent(token, currentSiteId) {
      return Boolean(
        token &&
        token.sequence === this.sequence &&
        token.siteId === currentSiteId &&
        !token.signal?.aborted
      );
    }

    finish(token) {
      if (token && token.sequence === this.sequence) {
        this.controller = null;
      }
    }
  }

  const nearbyMarineRequests = new NearbyMarineRequestCoordinator();
  const speciesReferenceRequests = new SpeciesReferenceRequestCoordinator();
  const profileQaRequests = new ProfileQaRequestCoordinator();
  const profileEdnaQaRequests = new ProfileEdnaQaRequestCoordinator();
  let speciesReferenceBusy = false;
  let profileQaBusy = false;
  let profileEdnaQaBusy = false;
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

  function currentProfileContext() {
    if (!selectedSite) return null;
    const siteId = safeText(selectedSite.id, "");
    return siteId ? { siteId } : null;
  }

  function setProfileBusy(isBusy) {
    profileBusy = isBusy;
    elements.profileDrawer.setAttribute("aria-busy", String(isBusy));
    elements.profileToggle.disabled = isBusy;
    updateProfileShortcutControls();
  }

  function updateProfileShortcutControls() {
    const disabled = !selectedSite || profileBusy;
    elements.profileToEdna.disabled = disabled;
    elements.profileToReefCheck.disabled = disabled;
    elements.profileToWeather.disabled = disabled;
  }

  function setProfileDrawerCollapsed(collapsed) {
    elements.profileContent.hidden = collapsed;
    elements.profileToggle.setAttribute("aria-expanded", String(!collapsed));
    elements.profileToggle.textContent = collapsed ? "展開資訊" : "收合資訊";
    if (collapsed) {
      profileQaRequests.cancel();
      profileEdnaQaRequests.cancel();
    }
  }

  function clearProfileSources(list) {
    list.replaceChildren();
  }

  function clearProfileDisplay() {
    clearProfileQaDisplay();
    clearProfileEdnaQaDisplay();
    elements.profileDetails.hidden = true;
    elements.profileMediaState.replaceChildren();
    const mediaWaiting = document.createElement("p");
    mediaWaiting.textContent = "正在切換潛點；未顯示任何圖片。";
    elements.profileMediaState.append(mediaWaiting);
    elements.profileBasicFields.replaceChildren();
    elements.profileIntroductionText.textContent = "";
    elements.profileEnvironmentText.textContent = "";
    elements.profileActivityText.textContent = "";
    elements.profileEdnaStatus.textContent = "";
    elements.profileReefCheckStatus.textContent = "";
    elements.profileLimitations.replaceChildren();
    [
      elements.profileIntroductionSources,
      elements.profileEnvironmentSources,
      elements.profileActivitySources,
      elements.profileEdnaSources,
      elements.profileReefCheckSources,
    ].forEach(clearProfileSources);
  }

  function appendProfileSource(list, source) {
    if (!source || typeof source !== "object") return;
    const item = document.createElement("li");
    const heading = document.createElement("strong");
    heading.textContent = safeText(source.name);
    const fields = document.createElement("dl");
    appendEvidenceField(fields, "維護單位", source.maintainer);
    appendEvidenceField(fields, "最後核對日期", source.last_verified_at);
    appendEvidenceField(fields, "授權／顯名", source.license_and_attribution);
    appendEvidenceField(fields, "來源限制", source.limitations);
    appendEvidenceField(fields, "原始來源", createSafeLink("開啟原始 HTTPS 來源", source.url));
    item.append(heading, fields);
    list.append(item);
  }

  function renderProfileSources(list, sources) {
    clearProfileSources(list);
    if (!Array.isArray(sources)) return;
    sources.forEach((source) => appendProfileSource(list, source));
  }

  function renderProfileMedia(media) {
    const value = media && typeof media === "object" ? media : {};
    elements.profileMediaState.replaceChildren();
    if (value.status !== "available" || !value.image || typeof value.image !== "object") {
      const message = document.createElement("p");
      message.textContent = safeText(value.message, "目前沒有可公開展示的官方圖片。");
      const attribution = document.createElement("p");
      attribution.className = "profile-data-reason";
      attribution.textContent = safeText(value.license_attribution, "圖片來源或再利用權利尚未確認。");
      elements.profileMediaState.append(message, attribution);
      return;
    }
    const image = value.image;
    const url = safeText(image.url, "");
    if (!url.startsWith("/static/curated-media/dive-sites/") || url.includes("..")) {
      const blocked = document.createElement("p");
      blocked.textContent = "目前沒有可公開展示的官方圖片。";
      elements.profileMediaState.append(blocked);
      return;
    }
    const figure = document.createElement("figure");
    const img = document.createElement("img");
    img.src = url;
    img.alt = safeText(image.alt, "官方景點圖片");
    img.loading = "lazy";
    img.addEventListener("error", () => {
      figure.replaceChildren();
      const fallback = document.createElement("p");
      fallback.textContent = "官方圖片目前無法載入；未以其他圖片替代。";
      figure.append(fallback);
    }, { once: true });
    const caption = document.createElement("figcaption");
    caption.textContent = `圖片來源與顯名：${safeText(image.license_attribution)}；最後核對：${safeText(image.last_verified_at)}`;
    figure.append(img, caption);
    const source = createSafeLink("查看官方圖片原始來源", image.source_url);
    if (source) figure.append(source);
    elements.profileMediaState.append(figure);
  }

  function renderProfileTextSection(section, textElement, sourceList) {
    const value = section && typeof section === "object" ? section : {};
    if (value.status === "data_insufficient") {
      textElement.textContent = "目前資料不足";
      if (typeof value.reason === "string" && value.reason.trim()) {
        const reason = document.createElement("span");
        reason.className = "profile-data-reason";
        reason.textContent = `：${value.reason.trim()}`;
        textElement.append(reason);
      }
      clearProfileSources(sourceList);
      return;
    }
    textElement.textContent = safeText(value.text, "目前資料不足");
    renderProfileSources(sourceList, value.sources);
  }

  function renderProfileBasics(site) {
    const value = site && typeof site === "object" ? site : {};
    const point = value.representative_point && typeof value.representative_point === "object"
      ? value.representative_point
      : {};
    const administrativeArea = value.administrative_area && typeof value.administrative_area === "object"
      ? value.administrative_area
      : {};
    const basicSource = value.basic_source && typeof value.basic_source === "object"
      ? value.basic_source
      : {};
    const region = [administrativeArea.county, administrativeArea.district]
      .filter((part) => typeof part === "string" && part.trim())
      .join("／");
    const latitude = Number(point.latitude);
    const longitude = Number(point.longitude);
    const coordinates = Number.isFinite(latitude) && Number.isFinite(longitude)
      ? `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`
      : "原始資料未提供";
    elements.profileBasicFields.replaceChildren();
    appendEvidenceField(elements.profileBasicFields, "潛點名稱", value.name);
    if (region) appendEvidenceField(elements.profileBasicFields, "行政區", region);
    appendEvidenceField(elements.profileBasicFields, "資料品質", value.data_quality);
    appendEvidenceField(elements.profileBasicFields, "官方代表點座標", coordinates);
    appendEvidenceField(elements.profileBasicFields, "最後核對日期", value.last_verified_at);
    appendEvidenceField(
      elements.profileBasicFields,
      "基本資料來源",
      createSafeLink(safeText(basicSource.name), basicSource.reference),
    );
  }

  function renderProfileEvidence(profile) {
    const evidence = profile && typeof profile.research_evidence_index === "object"
      ? profile.research_evidence_index
      : {};
    const edna = evidence.edna && typeof evidence.edna === "object" ? evidence.edna : {};
    const reefCheck = evidence.reef_check && typeof evidence.reef_check === "object" ? evidence.reef_check : {};
    elements.profileEdnaStatus.textContent = `${safeText(edna.availability, "目前資料不足")}。${safeText(edna.limitations, "")}`;
    elements.profileReefCheckStatus.textContent = `${safeText(reefCheck.availability, "目前資料不足")}。${safeText(reefCheck.limitations, "僅限本機非商業研究模式使用。")}`;
    renderProfileSources(elements.profileEdnaSources, edna.sources);
    renderProfileSources(elements.profileReefCheckSources, reefCheck.sources);
  }

  function renderProfileLimitations(payload, profile) {
    const entries = [];
    if (Array.isArray(payload.limitations)) entries.push(...payload.limitations);
    if (profile && typeof profile.limitations === "string" && profile.limitations.trim()) {
      entries.push(profile.limitations);
    }
    elements.profileLimitations.replaceChildren();
    entries.forEach((entry) => {
      if (typeof entry !== "string" || !entry.trim()) return;
      const item = document.createElement("li");
      item.textContent = entry.trim();
      elements.profileLimitations.append(item);
    });
  }

  function renderApprovedProfile(payload, context) {
    const site = payload && payload.site && typeof payload.site === "object" ? payload.site : {};
    const profile = payload && payload.profile && typeof payload.profile === "object" ? payload.profile : null;
    if (safeText(site.id, "") !== context.siteId) throw new Error("profile_site_mismatch");
    renderProfileBasics(site);
    elements.profileDetails.hidden = false;
    renderProfileMedia(payload && payload.media);
    if (!profile || payload.status === "data_insufficient") {
      elements.profileStatus.textContent = "目前資料不足：此潛點尚無可公開的來源核對介紹。";
      elements.profileIntroductionText.textContent = "目前資料不足";
      elements.profileEnvironmentText.textContent = "目前資料不足";
      elements.profileActivityText.textContent = "目前資料不足";
      clearProfileSources(elements.profileIntroductionSources);
      clearProfileSources(elements.profileEnvironmentSources);
      clearProfileSources(elements.profileActivitySources);
      clearProfileSources(elements.profileEdnaSources);
      clearProfileSources(elements.profileReefCheckSources);
      elements.profileEdnaStatus.textContent = "請使用下方既有手動查詢，取得附近歷史 eDNA 證據。";
      elements.profileReefCheckStatus.textContent = "僅在已啟用的本機非商業研究模式中，可使用下方既有手動查詢。";
      renderProfileLimitations(payload, null);
      return;
    }
    if (payload.status !== "available") throw new Error("profile_status_invalid");
    elements.profileStatus.textContent = "已載入可公開的來源核對介紹。";
    renderProfileTextSection(profile.official_introduction, elements.profileIntroductionText, elements.profileIntroductionSources);
    renderProfileTextSection(profile.geographic_environment_features, elements.profileEnvironmentText, elements.profileEnvironmentSources);
    renderProfileTextSection(profile.public_activity_background, elements.profileActivityText, elements.profileActivitySources);
    renderProfileEvidence(profile);
    renderProfileLimitations(payload, profile);
  }

  async function loadSelectedSiteProfile() {
    const context = currentProfileContext();
    if (!context) return;
    clearProfileDisplay();
    setProfileDrawerCollapsed(false);
    if (!profileTools || !profileRequests) {
      elements.profileStatus.textContent = "潛點介紹查詢元件目前無法使用；未顯示任何補充資料。";
      return;
    }
    const token = profileRequests.start(context);
    setProfileBusy(true);
    elements.profileStatus.textContent = "正在讀取來源核對的潛點介紹。";
    try {
      const response = await fetch(profileTools.buildProfileUrl(context.siteId), {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal: token.signal,
      });
      if (!profileRequests.isCurrent(token, currentProfileContext())) return;
      if (response.status === 404) {
        elements.profileStatus.textContent = "找不到目前選取潛點的介紹資料（404）。";
        return;
      }
      if (response.status === 503) {
        elements.profileStatus.textContent = "潛點介紹來源目前無法驗證（503）；未顯示舊資料。";
        return;
      }
      if (!response.ok) {
        elements.profileStatus.textContent = `潛點介紹查詢失敗（HTTP ${response.status}）。未顯示任何補充資料。`;
        return;
      }
      try {
        const payload = await response.json();
        if (!profileRequests.isCurrent(token, currentProfileContext())) return;
        renderApprovedProfile(payload, context);
      } catch (_error) {
        if (!profileRequests.isCurrent(token, currentProfileContext())) return;
        clearProfileDisplay();
        elements.profileStatus.textContent = "潛點介紹回應格式無法驗證；未顯示任何補充資料。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!profileRequests.isCurrent(token, currentProfileContext())) return;
      clearProfileDisplay();
      elements.profileStatus.textContent = "無法連線至潛點介紹 API；未顯示任何補充資料。";
    } finally {
      if (profileRequests.isCurrent(token, currentProfileContext())) {
        profileRequests.finish(token);
        setProfileBusy(false);
      }
    }
  }

  const NEARBY_MARINE_ENDPOINT = "/api/dive-sites";

  function clearNearbyMarineDisplay() {
    if (elements.nearbyMarineContent) {
      elements.nearbyMarineContent.hidden = true;
    }
    if (elements.nearbyMarineMetaFields) {
      elements.nearbyMarineMetaFields.replaceChildren();
    }
    if (elements.nearbyMarineItems) {
      elements.nearbyMarineItems.replaceChildren();
    }
    if (elements.nearbyMarineDisclaimers) {
      elements.nearbyMarineDisclaimers.replaceChildren();
    }
  }

  function resetNearbyMarine(message) {
    nearbyMarineRequests.cancel();
    clearNearbyMarineDisplay();
    if (elements.nearbyMarineStatus) {
      elements.nearbyMarineStatus.textContent =
        message || "請點選地圖標記或潛點清單以讀取附近海域模式資料。";
    }
  }

  function setNearbyMarineBusy(busy) {
    nearbyMarineBusy = busy;
    if (elements.nearbyMarineSection) {
      elements.nearbyMarineSection.setAttribute("aria-busy", busy ? "true" : "false");
    }
    if (elements.nearbyMarineRefresh) {
      elements.nearbyMarineRefresh.disabled = busy;
    }
  }

  function formatCoord(lat, lon) {
    if (typeof lat !== "number" || typeof lon !== "number") return RAW_VALUE_MISSING;
    return `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  }

  function renderNearbyMarineMeta(payload) {
    const model = payload.nearby_model_location || {};
    const site = payload.dive_site || {};
    const source = payload.source || {};
    const dl = elements.nearbyMarineMetaFields;
    dl.replaceChildren();

    appendEvidenceField(
      dl,
      "模式位置名稱／代碼",
      model.location_name && model.location_code
        ? `${model.location_name}（${model.location_code}）`
        : safeText(model.location_name || model.location_code),
    );
    appendEvidenceField(
      dl,
      "模式點座標",
      formatCoord(model.latitude, model.longitude),
    );
    appendEvidenceField(
      dl,
      "潛點代表點座標",
      formatCoord(site.latitude, site.longitude),
    );
    appendEvidenceField(
      dl,
      "距潛點直線距離",
      model.distance_m !== undefined && model.distance_km !== undefined
        ? `${Number(model.distance_m).toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 2 })} 公尺（${model.distance_km} 公里）`
        : RAW_VALUE_MISSING,
    );
    appendEvidenceField(
      dl,
      "空間性質說明",
      safeText(model.location_nature, "氣象署近岸數值模式預報代表外海計算點，非潛點現場量測"),
    );
    appendEvidenceField(
      dl,
      "資料發布時間",
      safeText(source.issued_at),
    );
    appendEvidenceField(
      dl,
      "預報有效時間",
      source.valid_from && source.valid_to
        ? `${source.valid_from} 至 ${source.valid_to}`
        : RAW_VALUE_MISSING,
    );
  }

  function renderNearbyMarineItem(item, index) {
    const li = document.createElement("li");
    const article = document.createElement("article");
    article.className = "evidence-card";
    const h4 = document.createElement("h4");
    h4.textContent = `預報時點 ${index}：${safeText(item.valid_at)}`;
    const dl = document.createElement("dl");
    dl.className = "evidence-card-fields";

    const waveHeight = item.significant_wave_height_m;
    appendEvidenceField(
      dl,
      "浪高",
      waveHeight !== null && waveHeight !== undefined
        ? `${waveHeight} 公尺 (m)`
        : RAW_VALUE_MISSING,
    );
    appendEvidenceField(
      dl,
      "波向",
      safeText(item.wave_direction),
    );
    const wavePeriod = item.wave_period_s;
    appendEvidenceField(
      dl,
      "週期",
      wavePeriod !== null && wavePeriod !== undefined
        ? `${wavePeriod} 秒 (s)`
        : RAW_VALUE_MISSING,
    );
    appendEvidenceField(
      dl,
      "流向",
      safeText(item.ocean_current_direction),
    );
    const speed = item.ocean_current_speed_knot;
    const rawSpeed = item.raw_current_speed;
    let speedText = RAW_VALUE_MISSING;
    if (speed !== null && speed !== undefined) {
      speedText = `${speed} 節 (knot)`;
    } else if (rawSpeed) {
      speedText = `${rawSpeed} 節 (knot)`;
    }
    appendEvidenceField(
      dl,
      "流速",
      speedText,
    );

    article.append(h4, dl);
    li.append(article);
    return li;
  }

  function renderNearbyMarineDisclaimers(disclaimers) {
    const ul = elements.nearbyMarineDisclaimers;
    ul.replaceChildren();
    const list = Array.isArray(disclaimers) && disclaimers.length > 0
      ? disclaimers
      : [
          "此資料為交通部中央氣象署數值模式外海代表計算點之預報結果，絕非潛點現場量測數據。",
          "模式代表位置與潛點實體存在客觀空間距離，無法反映近岸水文微地形、碎波帶與沿岸暗流。",
          "本資料僅供宏觀海域環境背景參考，嚴禁單獨用於判斷合法性、安全性或是否適合下水。",
          "從事浮潛或水肺潛水活動前，必須確認最新官方警特報、現場實際海況，並由合格專業人員實地評估。",
        ];
    list.forEach((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      ul.append(li);
    });
  }

  async function loadNearbyMarineContext(site) {
    const targetSite = site || selectedSite;
    if (!targetSite || !targetSite.id) {
      resetNearbyMarine("請先選擇潛點。");
      return;
    }
    const siteId = safeText(targetSite.id, "");
    const token = nearbyMarineRequests.start(siteId);
    clearNearbyMarineDisplay();
    setNearbyMarineBusy(true);
    elements.nearbyMarineStatus.textContent = `正在讀取 ${safeText(targetSite.name)} 的附近海域模式參考…`;

    try {
      const url = `${NEARBY_MARINE_ENDPOINT}/${encodeURIComponent(siteId)}/nearby-marine-context`;
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal: token.signal,
      });

      if (!nearbyMarineRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

      if (response.status === 404) {
        clearNearbyMarineDisplay();
        elements.nearbyMarineStatus.textContent = "找不到目前選取的潛點（404）；未顯示任何舊預報。";
        return;
      }
      if (response.status === 422) {
        clearNearbyMarineDisplay();
        elements.nearbyMarineStatus.textContent = "預報時間範圍無效（422）；未顯示任何舊預報。";
        return;
      }
      if (response.status === 503) {
        clearNearbyMarineDisplay();
        let reasonMsg = "附近海域模式資料目前無法提供（503）；未顯示任何舊資料。";
        try {
          const errPayload = await response.json();
          if (errPayload && errPayload.reason === "source_expired") {
            reasonMsg = "氣象署模式預報資料已過期（發布超過 24 小時）；為確保安全，未顯示過期舊預報。";
          } else if (errPayload && errPayload.reason === "source_checksum_mismatch") {
            reasonMsg = "模式快照完整性驗證失敗；未顯示不可靠資料。";
          } else if (errPayload && (errPayload.reason === "no_source_snapshot_found" || errPayload.reason === "source_directory_unavailable")) {
            reasonMsg = "目前無可用的氣象署模式快照資料；未顯示任何預報值。";
          }
        } catch (_jsonErr) {}
        elements.nearbyMarineStatus.textContent = reasonMsg;
        return;
      }
      if (!response.ok) {
        clearNearbyMarineDisplay();
        elements.nearbyMarineStatus.textContent = `附近海域模式 API 查詢失敗（HTTP ${response.status}）；未顯示任何舊預報值。`;
        return;
      }

      try {
        const payload = await response.json();
        if (!nearbyMarineRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

        if (!payload || payload.status !== "ok" || !Array.isArray(payload.items)) {
          clearNearbyMarineDisplay();
          elements.nearbyMarineStatus.textContent = "模式資料回應格式不符；未顯示任何預報值。";
          return;
        }

        renderNearbyMarineMeta(payload);
        elements.nearbyMarineItems.replaceChildren(
          ...payload.items.map((item, idx) => renderNearbyMarineItem(item, idx + 1)),
        );
        renderNearbyMarineDisclaimers(payload.disclaimers);
        elements.nearbyMarineContent.hidden = false;
        elements.nearbyMarineStatus.textContent = `已載入最近模式計算點預報（共 ${payload.items.length} 筆時點）。此資料非潛點現場量測，僅供海域背景參考。`;
      } catch (_jsonErr) {
        if (!nearbyMarineRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
        clearNearbyMarineDisplay();
        elements.nearbyMarineStatus.textContent = "附近海域模式資料解析失敗；未顯示任何預報值。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!nearbyMarineRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
      clearNearbyMarineDisplay();
      elements.nearbyMarineStatus.textContent = "無法連線至附近海域模式 API；未顯示任何舊資料。";
    } finally {
      if (nearbyMarineRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) {
        nearbyMarineRequests.finish(token);
        setNearbyMarineBusy(false);
      }
    }
  }

  function clearSpeciesReferenceDisplay() {
    if (elements.speciesReferenceContent) {
      elements.speciesReferenceContent.hidden = true;
    }
    if (elements.speciesReferenceList) {
      elements.speciesReferenceList.replaceChildren();
    }
    if (elements.speciesReferenceDisclaimers) {
      elements.speciesReferenceDisclaimers.replaceChildren();
    }
  }

  function resetSpeciesReference(message) {
    speciesReferenceRequests.cancel();
    clearSpeciesReferenceDisplay();
    if (elements.speciesReferenceStatus) {
      elements.speciesReferenceStatus.textContent =
        message || "請點選地圖標記或潛點清單以讀取物種參考圖片與歷史生態證據。";
    }
  }

  function setSpeciesReferenceBusy(busy) {
    speciesReferenceBusy = busy;
    if (elements.speciesReferenceSection) {
      elements.speciesReferenceSection.setAttribute("aria-busy", busy ? "true" : "false");
    }
    if (elements.speciesReferenceRefresh) {
      elements.speciesReferenceRefresh.disabled = busy;
    }
  }

  function renderSpeciesReferenceDisclaimers(disclaimers) {
    if (!elements.speciesReferenceDisclaimers) return;
    elements.speciesReferenceDisclaimers.replaceChildren();
    const list = Array.isArray(disclaimers) ? disclaimers : [];
    list.forEach((item) => {
      if (typeof item !== "string" || !item.trim()) return;
      const li = document.createElement("li");
      li.textContent = item.trim();
      elements.speciesReferenceDisclaimers.append(li);
    });
  }

  function renderSpeciesReferenceCard(item) {
    const card = document.createElement("article");
    card.className = "species-reference-card";

    const header = document.createElement("div");
    header.className = "species-card-header";
    const title = document.createElement("h4");
    title.className = "species-card-title";
    title.textContent = safeText(item.species_chinese_name, "未命名物種");

    const sciName = document.createElement("span");
    sciName.className = "species-sci-name";
    const em = document.createElement("em");
    em.textContent = safeText(item.species_scientific_name);
    sciName.append(" (", em, ")");
    title.append(" ", sciName);
    header.append(title);

    if (item.taxonomic_notes) {
      const noteP = document.createElement("p");
      noteP.className = "species-taxonomic-note";
      const noteLabel = document.createElement("strong");
      noteLabel.textContent = "分類註記：";
      noteP.append(noteLabel, safeText(item.taxonomic_notes));
      header.append(noteP);
    }
    card.append(header);

    const badge = document.createElement("div");
    badge.className = "species-card-badge";
    badge.textContent = safeText(item.purpose_specification, "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）");
    card.append(badge);

    const url = typeof item.image_url === "string" ? item.image_url : "";
    if (url.startsWith("/static/curated-media/species-reference/") && !url.includes("..")) {
      const figure = document.createElement("figure");
      figure.className = "species-card-figure";
      const img = document.createElement("img");
      img.src = url;
      img.alt = `${safeText(item.species_chinese_name)} 外觀參考照片`;
      img.loading = "lazy";
      img.addEventListener("error", () => {
        figure.replaceChildren();
        const fallback = document.createElement("p");
        fallback.className = "media-fallback";
        fallback.textContent = "物種參考圖片目前無法載入；未以未授權圖片替代。";
        figure.append(fallback);
      }, { once: true });

      const figcaption = document.createElement("figcaption");
      const attribP = document.createElement("p");
      attribP.className = "image-attribution";
      attribP.textContent = `攝影／作者：${safeText(item.image_author)} ｜ 授權：${safeText(item.image_license)}`;
      figcaption.append(attribP);

      if (item.source_page_url) {
        const sourceLink = createSafeLink("查看來源網頁與授權", item.source_page_url);
        if (sourceLink) figcaption.append(sourceLink);
      }
      figure.append(img, figcaption);
      card.append(figure);
    } else {
      const noImgP = document.createElement("p");
      noImgP.className = "media-fallback";
      noImgP.textContent = "無可公開之物種外觀參考圖檔。";
      card.append(noImgP);
    }

    const evidenceSection = document.createElement("div");
    evidenceSection.className = "species-card-evidence";
    const evTitle = document.createElement("h5");
    evTitle.textContent = "對照之歷史生態調查證據";
    evidenceSection.append(evTitle);

    const dl = document.createElement("dl");
    dl.className = "species-evidence-fields";

    appendEvidenceField(dl, "證據類型", safeText(item.evidence_type_label, item.evidence_type));
    appendEvidenceField(dl, "調查方法", safeText(item.survey_method));
    appendEvidenceField(dl, "記錄／採樣日期", safeText(item.record_date));
    appendEvidenceField(
      dl,
      "距潛點距離",
      typeof item.distance_m === "number"
        ? `${item.distance_m.toFixed(1)} 公尺`
        : RAW_VALUE_MISSING,
    );
    appendEvidenceField(dl, "資料來源", safeText(item.evidence_source));
    appendEvidenceField(dl, "資料授權", safeText(item.evidence_license));
    appendEvidenceField(dl, "證據限制", safeText(item.evidence_constraints));

    evidenceSection.append(dl);
    card.append(evidenceSection);

    return card;
  }

  async function loadSpeciesReferenceImages(site) {
    if (!site || !site.id) {
      resetSpeciesReference();
      return;
    }

    const token = speciesReferenceRequests.start(safeText(site.id, ""));
    clearSpeciesReferenceDisplay();
    setSpeciesReferenceBusy(true);
    elements.speciesReferenceStatus.textContent = "正在讀取物種外觀參考圖片與核定生態證據對照...";

    try {
      const url = `/api/dive-sites/${encodeURIComponent(site.id)}/species-reference-images`;
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: token.signal,
      });

      if (!speciesReferenceRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

      if (response.status === 404) {
        clearSpeciesReferenceDisplay();
        elements.speciesReferenceStatus.textContent = "此潛點不存在或未核驗；無法取得物種參考資料。";
        return;
      }

      if (response.status === 503) {
        clearSpeciesReferenceDisplay();
        elements.speciesReferenceStatus.textContent = "物種參考資料驗證失敗（503）；為確保安全，未顯示未核實資料。";
        return;
      }

      if (!response.ok) {
        clearSpeciesReferenceDisplay();
        elements.speciesReferenceStatus.textContent = `物種參考 API 查詢失敗（HTTP ${response.status}）；未顯示任何資料。`;
        return;
      }

      try {
        const payload = await response.json();
        if (!speciesReferenceRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

        if (!payload || payload.status !== "ok" || !Array.isArray(payload.items)) {
          clearSpeciesReferenceDisplay();
          elements.speciesReferenceStatus.textContent = "物種參考資料回應格式不符；未顯示任何項目。";
          return;
        }

        if (payload.items.length === 0) {
          clearSpeciesReferenceDisplay();
          elements.speciesReferenceStatus.textContent = "此潛點目前無可公開之物種外觀參考圖片與核定生態證據對照。";
          return;
        }

        elements.speciesReferenceList.replaceChildren(
          ...payload.items.map((item) => renderSpeciesReferenceCard(item)),
        );
        renderSpeciesReferenceDisclaimers(payload.disclaimers);
        elements.speciesReferenceContent.hidden = false;
        elements.speciesReferenceStatus.textContent = `已載入 ${payload.items.length} 筆已核准之物種外觀參考與歷史生態證據。此圖片非潛點現場拍攝，亦不代表該物種目前可見。`;
      } catch (_jsonErr) {
        if (!speciesReferenceRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
        clearSpeciesReferenceDisplay();
        elements.speciesReferenceStatus.textContent = "物種參考資料解析失敗；未顯示任何資料。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!speciesReferenceRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
      clearSpeciesReferenceDisplay();
      elements.speciesReferenceStatus.textContent = "無法連線至物種參考 API；未顯示任何舊資料。";
    } finally {
      if (speciesReferenceRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) {
        speciesReferenceRequests.finish(token);
        setSpeciesReferenceBusy(false);
      }
    }
  }

  function clearProfileQaDisplay() {
    if (elements.profileQaAnswerContainer) {
      elements.profileQaAnswerContainer.hidden = true;
    }
    if (elements.profileQaAnswerText) {
      elements.profileQaAnswerText.textContent = "";
    }
    if (elements.profileQaCitationsSection) {
      elements.profileQaCitationsSection.hidden = true;
    }
    if (elements.profileQaCitationsList) {
      elements.profileQaCitationsList.replaceChildren();
    }
  }

  function updateProfileQaCounter() {
    if (!elements.profileQaInput || !elements.profileQaCounter) return;
    const currentLen = elements.profileQaInput.value.length;
    elements.profileQaCounter.textContent = `${currentLen} / 500 字`;
  }

  function updateProfileQaControls() {
    if (!elements.profileQaInput || !elements.profileQaSubmit) return;
    const hasSite = Boolean(selectedSite && selectedSite.id);
    elements.profileQaInput.disabled = !hasSite || profileQaBusy;

    const trimmedLen = elements.profileQaInput.value.trim().length;
    const isValidLen = trimmedLen >= 2 && trimmedLen <= 500;
    elements.profileQaSubmit.disabled = !hasSite || profileQaBusy || !isValidLen;
  }

  function resetProfileQa(message, { clearInput = true } = {}) {
    profileQaRequests.cancel();
    profileQaBusy = false;
    if (elements.profileQaSection) {
      elements.profileQaSection.setAttribute("aria-busy", "false");
    }
    clearProfileQaDisplay();
    if (clearInput && elements.profileQaInput) {
      elements.profileQaInput.value = "";
    }
    updateProfileQaCounter();
    updateProfileQaControls();
    if (elements.profileQaStatus) {
      elements.profileQaStatus.textContent =
        message || "請點選地圖標記或潛點清單以啟用問答。";
    }
  }

  function setProfileQaBusy(busy) {
    profileQaBusy = busy;
    if (elements.profileQaSection) {
      elements.profileQaSection.setAttribute("aria-busy", busy ? "true" : "false");
    }
    updateProfileQaControls();
  }

  function renderProfileQaCitationCard(cit) {
    if (!cit || typeof cit !== "object") return null;

    const card = document.createElement("article");
    card.className = "profile-qa-citation-card";

    const header = document.createElement("div");
    header.className = "profile-qa-citation-header";

    const badge = document.createElement("span");
    badge.className = "profile-qa-citation-badge";
    badge.textContent = safeText(cit.citation_id, "引用");

    const title = document.createElement("h5");
    title.className = "profile-qa-citation-title";
    title.textContent = safeText(cit.source_name, "官方來源");

    header.append(badge, title);
    card.append(header);

    const dl = document.createElement("dl");
    dl.className = "profile-qa-citation-fields";

    appendEvidenceField(dl, "潛點名稱", cit.site_name);
    appendEvidenceField(dl, "資料章節", cit.section_type);
    appendEvidenceField(dl, "授權條款", cit.license_and_attribution);
    appendEvidenceField(dl, "宣告標示", cit.required_attribution);
    appendEvidenceField(dl, "使用限制", cit.limitations);

    const safeUrl = safeHttpsUrl(cit.source_url);
    if (safeUrl) {
      appendEvidenceField(
        dl,
        "官方來源",
        createSafeLink("開啟官方 HTTPS 來源（新視窗）", safeUrl),
      );
    } else {
      appendEvidenceField(dl, "官方來源", "未提供有效 HTTPS 來源網址");
    }

    card.append(dl);
    return card;
  }

  async function submitProfileQuestion() {
    if (!selectedSite || !selectedSite.id) {
      resetProfileQa("請先選擇潛點再提問。");
      return;
    }
    if (!elements.profileQaInput) return;

    const rawQuestion = elements.profileQaInput.value;
    const cleanQuestion = rawQuestion.trim();
    if (cleanQuestion.length < 2 || cleanQuestion.length > 500) {
      if (elements.profileQaStatus) {
        elements.profileQaStatus.textContent = "提問字數須在 2 至 500 字元之間。";
      }
      updateProfileQaControls();
      return;
    }

    const siteId = safeText(selectedSite.id, "");
    const token = profileQaRequests.start(siteId);
    clearProfileQaDisplay();
    setProfileQaBusy(true);
    elements.profileQaStatus.textContent = `正在向 ${safeText(selectedSite.name)} 的官方背景資料庫查詢回答…`;

    try {
      const url = `/api/dive-sites/${encodeURIComponent(siteId)}/ask-profile`;
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({ question: cleanQuestion }),
        signal: token.signal,
      });

      if (!profileQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

      if (response.status === 404) {
        clearProfileQaDisplay();
        elements.profileQaStatus.textContent = "找不到目前選取的潛點代碼（404）；未顯示任何回答。";
        return;
      }
      if (response.status === 422) {
        clearProfileQaDisplay();
        elements.profileQaStatus.textContent = "提問格式或字數不合規範（422）；未顯示任何回答。";
        return;
      }
      if (response.status === 503) {
        clearProfileQaDisplay();
        elements.profileQaStatus.textContent = "潛點介紹資料來源或索引校驗失敗（503）；暫時無法提供問答服務。";
        return;
      }
      if (response.status === 500) {
        clearProfileQaDisplay();
        elements.profileQaStatus.textContent = "伺服器處理問答時發生未預期異常（500）；請稍後再試。";
        return;
      }
      if (!response.ok) {
        clearProfileQaDisplay();
        elements.profileQaStatus.textContent = `問答服務連線異常（HTTP ${response.status}）；請稍後再試。`;
        return;
      }

      try {
        const payload = await response.json();
        if (!profileQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

        if (!payload || typeof payload !== "object") {
          clearProfileQaDisplay();
          elements.profileQaStatus.textContent = "問答回應格式無法辨識；未顯示任何回答。";
          return;
        }

        if (payload.status === "answerable") {
          const answerText = typeof payload.answer_zh_hant === "string" ? payload.answer_zh_hant.trim() : "";
          if (!answerText) {
            clearProfileQaDisplay();
            elements.profileQaStatus.textContent = "目前潛點官方資料不足以回答此問題。";
            return;
          }
          elements.profileQaAnswerText.textContent = answerText;
          elements.profileQaAnswerContainer.hidden = false;

          elements.profileQaCitationsList.replaceChildren();
          if (Array.isArray(payload.citations) && payload.citations.length > 0) {
            payload.citations.forEach((cit) => {
              const card = renderProfileQaCitationCard(cit);
              if (card) elements.profileQaCitationsList.append(card);
            });
            elements.profileQaCitationsSection.hidden = elements.profileQaCitationsList.children.length === 0;
          } else {
            elements.profileQaCitationsSection.hidden = true;
          }
          elements.profileQaStatus.textContent = "已依官方核准背景完成回答。";
        } else if (payload.status === "safety_intercepted") {
          clearProfileQaDisplay();
          elements.profileQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "此問題涉及即時海況安全、醫療急救、入水動線或法規許可，已依安全契約攔截。",
          );
        } else if (payload.status === "insufficient_evidence") {
          clearProfileQaDisplay();
          elements.profileQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "目前潛點官方資料不足以回答此問題。",
          );
        } else if (payload.status === "unconfigured_llm") {
          clearProfileQaDisplay();
          elements.profileQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "尚未設定語言模型服務，請先設定相關環境變數。",
          );
        } else if (payload.status === "llm_call_failed") {
          clearProfileQaDisplay();
          elements.profileQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "語言模型服務暫時無法連線，已依安全契約中斷處理。",
          );
        } else {
          clearProfileQaDisplay();
          elements.profileQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "問答處理受阻，已依安全契約中止。",
          );
        }
      } catch (_jsonErr) {
        if (!profileQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
        clearProfileQaDisplay();
        elements.profileQaStatus.textContent = "問答回應解析失敗；未顯示任何回答。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!profileQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
      clearProfileQaDisplay();
      elements.profileQaStatus.textContent = "無法連線至問答服務；請確認網路連線後再試。";
    } finally {
      if (profileQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) {
        profileQaRequests.finish(token);
        setProfileQaBusy(false);
      }
    }
  }

  function clearProfileEdnaQaDisplay() {
    if (elements.profileEdnaQaAnswerContainer) {
      elements.profileEdnaQaAnswerContainer.hidden = true;
    }
    if (elements.profileEdnaQaAnswerText) {
      elements.profileEdnaQaAnswerText.textContent = "";
    }
    if (elements.profileEdnaQaCitationsSection) {
      elements.profileEdnaQaCitationsSection.hidden = true;
    }
    if (elements.profileEdnaQaCitationsList) {
      elements.profileEdnaQaCitationsList.replaceChildren();
    }
  }

  function updateProfileEdnaQaCounter() {
    if (!elements.profileEdnaQaInput || !elements.profileEdnaQaCounter) return;
    const currentLen = elements.profileEdnaQaInput.value.length;
    elements.profileEdnaQaCounter.textContent = `${currentLen} / 500 字`;
  }

  function updateProfileEdnaQaControls() {
    if (!elements.profileEdnaQaInput || !elements.profileEdnaQaSubmit || !elements.profileEdnaQaRadius) return;
    const hasSite = Boolean(selectedSite && selectedSite.id);
    elements.profileEdnaQaRadius.disabled = !hasSite || profileEdnaQaBusy;
    elements.profileEdnaQaInput.disabled = !hasSite || profileEdnaQaBusy;

    const rawRadius = elements.profileEdnaQaRadius.value;
    const radiusInt = parseInt(rawRadius, 10);
    const hasValidRadius = Boolean(rawRadius && !Number.isNaN(radiusInt) && [500, 1000, 2000, 5000].includes(radiusInt));

    const trimmedLen = elements.profileEdnaQaInput.value.trim().length;
    const isValidLen = trimmedLen >= 2 && trimmedLen <= 500;
    elements.profileEdnaQaSubmit.disabled = !hasSite || profileEdnaQaBusy || !hasValidRadius || !isValidLen;
  }

  function resetProfileEdnaQa(message, { clearInput = true, resetRadius = false } = {}) {
    profileEdnaQaRequests.cancel();
    profileEdnaQaBusy = false;
    if (elements.profileEdnaQaSection) {
      elements.profileEdnaQaSection.setAttribute("aria-busy", "false");
    }
    clearProfileEdnaQaDisplay();
    if (resetRadius && elements.profileEdnaQaRadius) {
      elements.profileEdnaQaRadius.value = "";
    }
    if (clearInput && elements.profileEdnaQaInput) {
      elements.profileEdnaQaInput.value = "";
    }
    updateProfileEdnaQaCounter();
    updateProfileEdnaQaControls();
    if (elements.profileEdnaQaStatus) {
      elements.profileEdnaQaStatus.textContent =
        message || "請點選地圖標記或潛點清單以啟用問答。";
    }
  }

  function setProfileEdnaQaBusy(busy) {
    profileEdnaQaBusy = busy;
    if (elements.profileEdnaQaSection) {
      elements.profileEdnaQaSection.setAttribute("aria-busy", busy ? "true" : "false");
    }
    updateProfileEdnaQaControls();
  }

  function renderProfileEdnaQaCitationCard(cit) {
    if (!cit || typeof cit !== "object") return null;

    const card = document.createElement("article");
    card.className = "profile-edna-qa-citation-card";

    const header = document.createElement("div");
    header.className = "profile-edna-qa-citation-header";

    const badge = document.createElement("span");
    badge.className = "profile-edna-qa-citation-badge";
    badge.textContent = safeText(cit.citation_id, "eDNA 引用");

    const title = document.createElement("h5");
    title.className = "profile-edna-qa-citation-title";
    title.textContent = safeText(cit.source_name, "海洋保育署 eDNA 採樣資料");

    header.append(badge, title);
    card.append(header);

    const dl = document.createElement("dl");
    dl.className = "profile-edna-qa-citation-fields";

    appendEvidenceField(dl, "潛點名稱", cit.site_name);
    appendEvidenceField(dl, "資料性質", cit.data_nature);
    if (cit.radius_m != null) {
      appendEvidenceField(dl, "搜尋半徑", `${cit.radius_m} 公尺`);
    }
    if (cit.distance_m != null) {
      appendEvidenceField(dl, "距代表點", `${cit.distance_m} 公尺`);
    }
    appendEvidenceField(dl, "測站代號", cit.station_id);
    appendEvidenceField(dl, "採樣日期", cit.sampled_at);

    if (cit.sample_position && typeof cit.sample_position === "object") {
      const lat = cit.sample_position.latitude;
      const lon = cit.sample_position.longitude;
      const crs = safeText(cit.sample_position.coordinate_reference_system, "WGS84");
      if (lat != null && lon != null) {
        appendEvidenceField(dl, "採樣座標", `${lat}, ${lon} (${crs})`);
      }
    }

    const taxa = [cit.chinese_name, cit.scientific_name].filter(Boolean).join(" / ");
    if (taxa) {
      appendEvidenceField(dl, "檢出分類群", taxa);
    }

    appendEvidenceField(dl, "來源定位器", cit.source_record_id);
    appendEvidenceField(dl, "授權條款", cit.license_name);
    appendEvidenceField(dl, "宣告標示", cit.required_attribution);

    if (Array.isArray(cit.limitations) && cit.limitations.length > 0) {
      appendEvidenceField(dl, "限制說明", cit.limitations.join("；"));
    } else if (cit.limitations) {
      appendEvidenceField(dl, "限制說明", cit.limitations);
    }

    const safeUrl = safeHttpsUrl(cit.source_url);
    if (safeUrl) {
      appendEvidenceField(
        dl,
        "官方資料集",
        createSafeLink("開啟官方資料集 HTTPS 網址（新視窗）", safeUrl),
      );
    } else {
      appendEvidenceField(dl, "官方資料集", "未提供有效 HTTPS 來源網址");
    }

    card.append(dl);
    return card;
  }

  async function submitProfileEdnaQuestion() {
    if (!selectedSite || !selectedSite.id) {
      resetProfileEdnaQa("請先選擇潛點再提問。");
      return;
    }
    if (!elements.profileEdnaQaInput || !elements.profileEdnaQaRadius) return;

    const rawRadius = elements.profileEdnaQaRadius.value;
    const radiusInt = parseInt(rawRadius, 10);
    if (!rawRadius || Number.isNaN(radiusInt) || ![500, 1000, 2000, 5000].includes(radiusInt)) {
      if (elements.profileEdnaQaStatus) {
        elements.profileEdnaQaStatus.textContent = "請先選擇搜尋半徑（500、1,000、2,000 或 5,000 公尺）。";
      }
      updateProfileEdnaQaControls();
      return;
    }

    const rawQuestion = elements.profileEdnaQaInput.value;
    const cleanQuestion = rawQuestion.trim();
    if (cleanQuestion.length < 2 || cleanQuestion.length > 500) {
      if (elements.profileEdnaQaStatus) {
        elements.profileEdnaQaStatus.textContent = "提問字數須在 2 至 500 字元之間。";
      }
      updateProfileEdnaQaControls();
      return;
    }

    const siteId = safeText(selectedSite.id, "");
    const token = profileEdnaQaRequests.start(siteId);
    clearProfileEdnaQaDisplay();
    setProfileEdnaQaBusy(true);
    elements.profileEdnaQaStatus.textContent = `正在向 ${safeText(selectedSite.name)} 的歷史 eDNA 採樣資料庫查詢回答（半徑 ${radiusInt.toLocaleString()} 公尺）…`;

    try {
      const url = `/api/dive-sites/${encodeURIComponent(siteId)}/ask-edna`;
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({ question: cleanQuestion, radius_m: radiusInt }),
        signal: token.signal,
      });

      if (!profileEdnaQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

      if (response.status === 404) {
        clearProfileEdnaQaDisplay();
        elements.profileEdnaQaStatus.textContent = "找不到目前選取的潛點代碼（404）；未顯示任何回答。";
        return;
      }
      if (response.status === 422) {
        clearProfileEdnaQaDisplay();
        elements.profileEdnaQaStatus.textContent = "提問格式、半徑或字數不合規範（422）；未顯示任何回答。";
        return;
      }
      if (response.status === 503) {
        clearProfileEdnaQaDisplay();
        elements.profileEdnaQaStatus.textContent = "結構化 eDNA 資料庫不可用或校驗失敗（503）；暫時無法提供問答服務。";
        return;
      }
      if (response.status === 500) {
        clearProfileEdnaQaDisplay();
        elements.profileEdnaQaStatus.textContent = "伺服器處理問答時發生未預期異常（500）；請稍後再試。";
        return;
      }
      if (!response.ok) {
        clearProfileEdnaQaDisplay();
        elements.profileEdnaQaStatus.textContent = `問答服務連線異常（HTTP ${response.status}）；請稍後再試。`;
        return;
      }

      try {
        const payload = await response.json();
        if (!profileEdnaQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;

        if (!payload || typeof payload !== "object") {
          clearProfileEdnaQaDisplay();
          elements.profileEdnaQaStatus.textContent = "問答回應格式無法辨識；未顯示任何回答。";
          return;
        }

        if (payload.status === "answerable") {
          const answerText = typeof payload.answer_zh_hant === "string" ? payload.answer_zh_hant.trim() : "";
          if (!answerText) {
            clearProfileEdnaQaDisplay();
            elements.profileEdnaQaStatus.textContent = "目前潛點周邊資料不足以回答此問題。";
            return;
          }
          elements.profileEdnaQaAnswerText.textContent = answerText;
          elements.profileEdnaQaAnswerContainer.hidden = false;

          elements.profileEdnaQaCitationsList.replaceChildren();
          if (Array.isArray(payload.citations) && payload.citations.length > 0) {
            payload.citations.forEach((cit) => {
              const card = renderProfileEdnaQaCitationCard(cit);
              if (card) elements.profileEdnaQaCitationsList.append(card);
            });
            elements.profileEdnaQaCitationsSection.hidden = elements.profileEdnaQaCitationsList.children.length === 0;
          } else {
            elements.profileEdnaQaCitationsSection.hidden = true;
          }
          elements.profileEdnaQaStatus.textContent = "已依周邊歷史 eDNA 採樣紀錄完成回答。";
        } else if (payload.status === "scope_guidance") {
          clearProfileEdnaQaDisplay();
          elements.profileEdnaQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "此問題屬景點背景介紹範疇，請改用上方「官方背景問答」提問。",
          );
        } else if (payload.status === "safety_intercepted") {
          clearProfileEdnaQaDisplay();
          elements.profileEdnaQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "此問題涉及即時海況安全、下水判斷、醫療急救或出沒保證，已依安全契約攔截。",
          );
        } else if (payload.status === "insufficient_evidence") {
          clearProfileEdnaQaDisplay();
          elements.profileEdnaQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "指定半徑內無相關歷史 eDNA 採樣紀錄。",
          );
        } else if (payload.status === "unconfigured_llm") {
          clearProfileEdnaQaDisplay();
          elements.profileEdnaQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "尚未設定語言模型服務，請先設定相關環境變數。",
          );
        } else if (payload.status === "llm_call_failed") {
          clearProfileEdnaQaDisplay();
          elements.profileEdnaQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "語言模型服務暫時無法連線，已依安全契約中斷處理。",
          );
        } else {
          clearProfileEdnaQaDisplay();
          elements.profileEdnaQaStatus.textContent = safeText(
            payload.answer_zh_hant,
            "問答處理受阻，已依安全契約中止。",
          );
        }
      } catch (_jsonErr) {
        if (!profileEdnaQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
        clearProfileEdnaQaDisplay();
        elements.profileEdnaQaStatus.textContent = "問答回應解析失敗；未顯示任何回答。";
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
      if (!profileEdnaQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) return;
      clearProfileEdnaQaDisplay();
      elements.profileEdnaQaStatus.textContent = "無法連線至問答服務；請確認網路連線後再試。";
    } finally {
      if (profileEdnaQaRequests.isCurrent(token, selectedSite ? safeText(selectedSite.id, "") : null)) {
        profileEdnaQaRequests.finish(token);
        setProfileEdnaQaBusy(false);
      }
    }
  }

  function focusManualQuery(panel, control) {
    panel.scrollIntoView({ block: "start", behavior: "smooth" });
    control.focus({ preventScroll: true });
  }

  function selectSite(site, origin) {
    const id = safeText(site.id, "");
    const siteChanged = !selectedSite || safeText(selectedSite.id, "") !== id;
    const coordinates = coordinatesFor(site);
    const source = site && typeof site.source === "object" ? site.source : {};
    const region = displayRegion(site);
    selectedSite = site;
    updateProfileShortcutControls();

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
      resetProfileQa(
        `已切換至 ${safeText(site.name)}。請輸入 2 至 500 字元的繁體中文問題並送出。`,
      );
      resetProfileEdnaQa(
        `已切換至 ${safeText(site.name)}。請先選擇搜尋半徑並輸入提問內容。`,
        { resetRadius: true },
      );
      loadSelectedSiteProfile();
      loadNearbyMarineContext(site);
      loadSpeciesReferenceImages(site);
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
    resetProfileQa("目前沒有已驗證潛點可提問。");
    resetProfileEdnaQa("目前沒有已驗證潛點可提問。");
    elements.list.replaceChildren();
    elements.count.textContent = "0 筆";
    elements.dataStatus.textContent = "目前沒有已驗證潛點可顯示；系統不會以假資料補足。";
  }

  function showLoadError(message) {
    resetProfileQa(message);
    resetProfileEdnaQa(message);
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
  elements.profileToggle.addEventListener("click", () => {
    setProfileDrawerCollapsed(!elements.profileContent.hidden);
  });
  elements.profileToEdna.addEventListener("click", () => {
    focusManualQuery(elements.ednaPanel, elements.ednaRadius);
  });
  elements.profileToReefCheck.addEventListener("click", () => {
    focusManualQuery(elements.reefCheckPanel, elements.reefCheckRadius);
  });
  elements.profileToWeather.addEventListener("click", () => {
    focusManualQuery(elements.weatherPanel, elements.weatherRange);
  });
  if (elements.nearbyMarineRefresh) {
    elements.nearbyMarineRefresh.addEventListener("click", () => {
      if (selectedSite) {
        loadNearbyMarineContext(selectedSite);
      }
    });
  }
  if (elements.speciesReferenceRefresh) {
    elements.speciesReferenceRefresh.addEventListener("click", () => {
      if (selectedSite) {
        loadSpeciesReferenceImages(selectedSite);
      }
    });
  }
  if (elements.profileQaInput) {
    elements.profileQaInput.addEventListener("input", () => {
      updateProfileQaCounter();
      updateProfileQaControls();
    });
  }
  if (elements.profileQaForm) {
    elements.profileQaForm.addEventListener("submit", (event) => {
      event.preventDefault();
      submitProfileQuestion();
    });
  }
  if (elements.profileEdnaQaInput) {
    elements.profileEdnaQaInput.addEventListener("input", () => {
      updateProfileEdnaQaCounter();
      updateProfileEdnaQaControls();
    });
  }
  if (elements.profileEdnaQaRadius) {
    elements.profileEdnaQaRadius.addEventListener("change", () => {
      updateProfileEdnaQaControls();
    });
  }
  if (elements.profileEdnaQaForm) {
    elements.profileEdnaQaForm.addEventListener("submit", (event) => {
      event.preventDefault();
      submitProfileEdnaQuestion();
    });
  }

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
  updateProfileShortcutControls();
  resetProfileQa("請點選地圖標記或潛點清單以啟用問答。");
  resetProfileEdnaQa("請點選地圖標記或潛點清單以啟用問答。");

  const notice = document.querySelector(".representative-point-notice");
  if (notice) notice.textContent = REPRESENTATIVE_POINT_NOTICE;
  initializeMap();
  loadSites();
})();
