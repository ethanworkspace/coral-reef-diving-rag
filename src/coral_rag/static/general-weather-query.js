"use strict";

(() => {
  const TAIPEI_TIME_ZONE = "Asia/Taipei";
  const ALLOWED_HOURS = Object.freeze([24, 48, 72]);

  function isAllowedHours(hours) {
    return Number.isInteger(hours) && ALLOWED_HOURS.includes(hours);
  }

  function taipeiIso(value) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) throw new TypeError("A valid date is required");
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: TAIPEI_TIME_ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).formatToParts(date).reduce((result, part) => {
      if (part.type !== "literal") result[part.type] = part.value;
      return result;
    }, {});
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+08:00`;
  }

  function buildWindow(hours, now = new Date()) {
    if (!isAllowedHours(hours)) {
      throw new RangeError("hours must be one of the displayed choices");
    }
    const start = now instanceof Date ? new Date(now.getTime()) : new Date(now);
    if (Number.isNaN(start.getTime())) throw new TypeError("A valid date is required");
    const end = new Date(start.getTime() + hours * 60 * 60 * 1000);
    return Object.freeze({
      startAt: taipeiIso(start),
      endAt: taipeiIso(end),
      timeZone: TAIPEI_TIME_ZONE,
      hours,
    });
  }

  function buildUrl(siteId, hours, now) {
    if (typeof siteId !== "string" || !siteId.trim()) {
      throw new TypeError("siteId is required");
    }
    const queryWindow = buildWindow(hours, now);
    const parameters = new URLSearchParams({
      start_at: queryWindow.startAt,
      end_at: queryWindow.endAt,
    });
    return Object.freeze({
      ...queryWindow,
      url: `/api/dive-sites/${encodeURIComponent(siteId)}/general-weather-forecast?${parameters.toString()}`,
    });
  }

  function sameContext(left, right) {
    return Boolean(left && right && left.siteId === right.siteId && left.hours === right.hours);
  }

  class RequestCoordinator {
    constructor() {
      this.sequence = 0;
      this.controller = null;
      this.context = null;
    }

    cancel() {
      if (this.controller) this.controller.abort();
      this.controller = null;
      this.context = null;
      this.sequence += 1;
    }

    start(context) {
      this.cancel();
      this.controller = new AbortController();
      this.context = { siteId: context.siteId, hours: context.hours };
      return {
        sequence: this.sequence,
        context: { ...this.context },
        signal: this.controller.signal,
      };
    }

    isCurrent(token, context) {
      return Boolean(
        token
        && token.sequence === this.sequence
        && sameContext(token.context, context)
        && sameContext(this.context, context),
      );
    }

    finish(token) {
      if (token && token.sequence === this.sequence) this.controller = null;
    }
  }

  const api = Object.freeze({
    ALLOWED_HOURS,
    RequestCoordinator,
    buildUrl,
    buildWindow,
    isAllowedHours,
    taipeiIso,
  });
  globalThis.GeneralWeatherQuery = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
