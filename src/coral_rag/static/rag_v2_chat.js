"use strict";

(() => {
  const form = document.querySelector("#rag-form");
  const questionInput = document.querySelector("#question");
  const submitBtn = document.querySelector("#submit-btn");
  const clearBtn = document.querySelector("#clear-btn");
  const statusElem = document.querySelector("#rag-status");
  const resultSection = document.querySelector("#rag-result");
  const statusBadge = document.querySelector("#result-status-badge");
  const answerElem = document.querySelector("#answer-text");
  const citationsContainer = document.querySelector("#citations-container");
  const citationsList = document.querySelector("#citations-list");
  const safetyNotice = document.querySelector("#safety-notice");
  const safetyNoticeText = document.querySelector("#safety-notice-text");

  const clearChildren = (node) => {
    while (node && node.firstChild) {
      node.removeChild(node.firstChild);
    }
  };

  const safeHttpsUrl = (value) => {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "https:" ? parsed.href : null;
    } catch {
      return null;
    }
  };

  const statusLabels = {
    success: "回答成功",
    insufficient_evidence: "資料不足",
    safety_intercepted: "安全轉介",
    llm_not_configured: "未設定服務",
    llm_call_failed: "服務連線失敗",
    model_output_invalid: "模型輸出異常",
    retrieval_error: "檢索過程異常",
    internal_error: "系統錯誤",
  };

  function setBusy(isBusy) {
    if (submitBtn) submitBtn.disabled = isBusy;
    if (questionInput) questionInput.disabled = isBusy;
    if (isBusy) {
      if (statusElem) statusElem.textContent = "正在進行受控檢索與繁中回答生成，請稍候…";
    }
  }

  function renderCitations(citations) {
    clearChildren(citationsList);
    if (!Array.isArray(citations) || citations.length === 0) {
      if (citationsContainer) citationsContainer.hidden = true;
      return;
    }

    if (citationsContainer) citationsContainer.hidden = false;

    citations.forEach((item) => {
      const card = document.createElement("article");
      card.className = "citation-card";

      const header = document.createElement("div");
      header.className = "citation-header";

      const badge = document.createElement("span");
      badge.className = "citation-tag";
      badge.textContent = item.citation_id || "引用";
      header.appendChild(badge);

      const title = document.createElement("h4");
      title.className = "citation-title";
      title.textContent = item.title || "未命名來源";
      header.appendChild(title);

      card.appendChild(header);

      if (Array.isArray(item.heading_path) && item.heading_path.length > 0) {
        const pathElem = document.createElement("p");
        pathElem.className = "citation-path";
        pathElem.textContent = item.heading_path.join(" > ");
        card.appendChild(pathElem);
      }

      const validUrl = safeHttpsUrl(item.source_url);
      if (validUrl) {
        const link = document.createElement("a");
        link.className = "citation-link";
        link.href = validUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "查看原始官方／研究來源 ↗";
        card.appendChild(link);
      }

      citationsList.appendChild(card);
    });
  }

  function renderResult(payload) {
    if (!resultSection) return;
    resultSection.hidden = false;

    const statusKey = payload.status || "internal_error";
    if (statusBadge) {
      statusBadge.textContent = statusLabels[statusKey] || "處理完畢";
      statusBadge.dataset.status = statusKey;
    }

    // 純文字安全渲染繁中回答，嚴禁 DOM HTML 直接注入
    if (answerElem) {
      answerElem.textContent = payload.answer_zh_hant || "無回答內容。";
    }

    // 安全轉介與狀態提示
    if (safetyNotice && safetyNoticeText) {
      if (statusKey === "safety_intercepted") {
        safetyNotice.hidden = false;
        safetyNoticeText.textContent =
          "此問題觸發安全路由保護（例如涉及即時海況、下水許可、急救醫療或證照資格）。本系統為受控靜態研究知識庫，請遵循官方主管機關公告或尋求專業認證人員協助。";
      } else if (statusKey === "insufficient_evidence") {
        safetyNotice.hidden = false;
        safetyNoticeText.textContent =
          "目前受控知識庫內未檢索到足以回答此問題的可靠客觀證據；系統嚴格禁止模型憑空推測，請縮小問題範圍或參考官方資源。";
      } else if (statusKey === "llm_not_configured") {
        safetyNotice.hidden = false;
        safetyNoticeText.textContent =
          "伺服器端尚未配置 LLM 模型服務或 API 金鑰，請聯繫管理員配置環境設定。";
      } else {
        safetyNotice.hidden = true;
        safetyNoticeText.textContent = "";
      }
    }

    // 只有在成功狀態下且有引用時才呈現引用卡片；其餘狀態（安全攔截、資料不足、服務錯誤）嚴禁顯示任何檢索片段作為替代
    if (statusKey === "success") {
      renderCitations(payload.citations);
    } else {
      renderCitations([]);
    }

    if (statusElem) {
      statusElem.textContent = "問答完成。";
    }
  }

  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const rawText = questionInput ? questionInput.value : "";
      const cleanText = rawText.trim();

      if (cleanText.length < 2) {
        if (statusElem) statusElem.textContent = "請輸入至少 2 個字元的研究問題。";
        if (questionInput) questionInput.focus();
        return;
      }

      setBusy(true);

      try {
        const response = await fetch("/api/rag-v2/ask", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ question: cleanText }),
        });

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          renderResult({
            status: response.status === 400 ? "safety_intercepted" : "internal_error",
            answer_zh_hant:
              errData.answer_zh_hant ||
              (response.status === 422
                ? "請求參數格式不符規定。"
                : "伺服器處理時發生錯誤，請稍後再試。"),
            citations: [],
            safety_route: errData.safety_route || null,
          });
          return;
        }

        const data = await response.json();
        renderResult(data);
      } catch (err) {
        renderResult({
          status: "internal_error",
          answer_zh_hant: "網路連線異常或伺服器無法連線，請稍後再試。",
          citations: [],
          safety_route: null,
        });
      } finally {
        setBusy(false);
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (questionInput) {
        questionInput.value = "";
        questionInput.focus();
      }
      if (resultSection) {
        resultSection.hidden = true;
      }
      if (statusElem) {
        statusElem.textContent = "請輸入問題後查詢；不會儲存提問或對話紀錄。";
      }
      if (citationsList) {
        clearChildren(citationsList);
      }
      if (citationsContainer) {
        citationsContainer.hidden = true;
      }
    });
  }
})();
