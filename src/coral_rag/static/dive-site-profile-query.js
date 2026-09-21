"use strict";

(() => {
  const PROFILE_PATH = "/api/dive-sites";

  function buildProfileUrl(siteId) {
    const normalizedId = typeof siteId === "string" ? siteId.trim() : "";
    if (!normalizedId) throw new Error("site_id_required");
    return `${PROFILE_PATH}/${encodeURIComponent(normalizedId)}/profile`;
  }

  class RequestCoordinator {
    constructor() {
      this.sequence = 0;
      this.controller = null;
    }

    start(context) {
      this.cancel();
      this.sequence += 1;
      this.controller = new AbortController();
      return { sequence: this.sequence, context, signal: this.controller.signal };
    }

    cancel() {
      if (this.controller) this.controller.abort();
      this.controller = null;
    }

    isCurrent(token, context) {
      return Boolean(
        token &&
          token.sequence === this.sequence &&
          JSON.stringify(token.context) === JSON.stringify(context),
      );
    }

    finish(token) {
      if (token && token.sequence === this.sequence) this.controller = null;
    }
  }

  const exported = Object.freeze({ buildProfileUrl, RequestCoordinator });
  globalThis.DiveSiteProfileQuery = exported;

  if (typeof module !== "undefined" && module.exports) module.exports = exported;
})();
