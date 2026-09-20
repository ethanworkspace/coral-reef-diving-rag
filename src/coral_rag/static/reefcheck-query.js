"use strict";

(() => {
  const PAGE_SIZE = 10;
  const MAX_OFFSET = 10_000;
  const ALLOWED_RADII = Object.freeze([250, 500, 1000, 2500, 5000]);

  function isAllowedRadius(radius) {
    return Number.isInteger(radius) && ALLOWED_RADII.includes(radius);
  }

  function buildUrl(siteId, radius, offset) {
    if (typeof siteId !== "string" || !siteId.trim()) throw new TypeError("siteId is required");
    if (!isAllowedRadius(radius)) throw new RangeError("radius must be one of the displayed choices");
    if (!Number.isInteger(offset) || offset < 0 || offset > MAX_OFFSET) {
      throw new RangeError("offset is outside the API range");
    }
    const parameters = new URLSearchParams({
      radius_m: String(radius), limit: String(PAGE_SIZE), offset: String(offset),
    });
    return `/api/dive-sites/${encodeURIComponent(siteId)}/nearby-reef-check?${parameters.toString()}`;
  }

  function sameContext(left, right) {
    return Boolean(left && right && left.siteId === right.siteId && left.radius === right.radius);
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
      this.context = { siteId: context.siteId, radius: context.radius };
      return { sequence: this.sequence, context: { ...this.context }, signal: this.controller.signal };
    }
    isCurrent(token, context) {
      return Boolean(token && token.sequence === this.sequence && sameContext(token.context, context)
        && sameContext(this.context, context));
    }
    finish(token) {
      if (token && token.sequence === this.sequence) this.controller = null;
    }
  }

  const api = Object.freeze({ ALLOWED_RADII, PAGE_SIZE, MAX_OFFSET, RequestCoordinator, buildUrl, isAllowedRadius });
  globalThis.NearbyReefCheckQuery = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
