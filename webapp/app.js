function currentAssetVersion() {
  const scriptFromDom =
    document.currentScript ||
    Array.from(document.querySelectorAll("script[src]")).find((node) => {
      const source = node.getAttribute("src") || "";
      return /(?:^|\/)app\.js(?:\?|$)/.test(source);
    });
  if (!scriptFromDom) return "";
  const source = scriptFromDom.getAttribute("src") || "";
  const queryIndex = source.indexOf("?");
  if (queryIndex === -1) return "";
  const params = new URLSearchParams(source.slice(queryIndex + 1));
  return params.get("v") || "";
}

function scriptPathMatches(node, fileName) {
  if (!node || !node.src) return false;
  try {
    const url = new URL(node.src, window.location.href);
    return url.pathname.endsWith(`/${fileName}`) || url.pathname.endsWith(`\\${fileName}`) || url.pathname.endsWith(fileName);
  } catch {
    const source = node.getAttribute("src") || "";
    return source === fileName || source.endsWith(`/${fileName}`) || source.endsWith(`\\${fileName}`);
  }
}

function hasScriptTag(fileName) {
  return Array.from(document.querySelectorAll("script[src]")).some((node) => scriptPathMatches(node, fileName));
}

function loadScriptFile(src, fileName) {
  return new Promise((resolve, reject) => {
    if (hasScriptTag(fileName)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

async function ensureRuntimeDependencies() {
  const version = currentAssetVersion();
  const runtimeVersion = version || String(Date.now());
  const withVersion = (fileName) => `${fileName}?v=${encodeURIComponent(runtimeVersion)}`;
  const dependencies = [
    {
      file: "helpers.js",
      src: withVersion("helpers.js"),
      ready: () =>
        typeof window.AppHelpers !== "undefined" &&
        window.AppHelpers &&
        typeof window.AppHelpers.on === "function" &&
        typeof window.AppHelpers.escapeHtml === "function",
    },
    {
      file: "auth.js",
      src: withVersion("auth.js"),
      ready: () => typeof window.AppAuth !== "undefined",
    },
    {
      file: "app.config.js",
      src: withVersion("app.config.js"),
      ready: () => typeof STORAGE_KEYS !== "undefined" && typeof translations !== "undefined",
    },
    {
      file: "app.state.js",
      src: withVersion("app.state.js"),
      ready: () => typeof state !== "undefined" && typeof elements !== "undefined",
    },
    {
      file: "app.core.js",
      src: withVersion("app.core.js"),
      ready: () => typeof initSession === "function" && typeof startAppDataFlow === "function",
    },
    {
      file: "app.analytics.js",
      src: withVersion("app.analytics.js"),
      ready: () => typeof loadChartData === "function",
    },
    {
      file: "app.transactions.js",
      src: withVersion("app.transactions.js"),
      ready: () => typeof resetTransactions === "function" && typeof loadMoreTransactions === "function",
    },
  ];

  for (const dependency of dependencies) {
    if (dependency.ready()) continue;
    await loadScriptFile(dependency.src, dependency.file);
    if (!dependency.ready()) {
      throw new Error(`Dependency ${dependency.file} is unavailable`);
    }
  }
}

function buildAssistantPeriodPayload() {
  const period = state.periodPreset || "month";
  const payload = { period };
  if (period === "month") {
    if (state.selectedMonth) payload.month = state.selectedMonth;
  } else if (period === "custom") {
    if (state.customPeriodStart) payload.start = state.customPeriodStart;
    if (state.customPeriodEnd) payload.end = state.customPeriodEnd;
  }
  return payload;
}

function findAssistantQuestion(index) {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (state.assistantMessages[i] && state.assistantMessages[i].role === "user") {
      return state.assistantMessages[i].content || "";
    }
  }
  return "";
}

function buildAssistantFeedbackPayload(entry, index) {
  const meta = (entry && entry.meta) || {};
  const question = meta.question || findAssistantQuestion(index);
  const period = meta.period || state.periodPreset || "month";
  const month = meta.month || state.selectedMonth || "";
  const start = meta.start || state.customPeriodStart || "";
  const end = meta.end || state.customPeriodEnd || "";
  const tone = meta.tone || state.assistantTone;
  return {
    question,
    answer: entry.content || "",
    tone,
    period,
    month,
    start,
    end,
    rating: "wrong",
    context: {
      period,
      month,
      start,
      end,
      tone,
      message_timestamp: entry.timestamp,
      app_version: currentAssetVersion(),
      screen: state.activeScreen,
    },
  };
}

function bindEvents() {
  on(window, "resize", () => {
    scheduleChatLayoutMetricsSync();
    scheduleTransactionsRender();
    if (typeof syncHistoryFilterControls === "function") syncHistoryFilterControls();
  });
  on(window, "scroll", () => scheduleTransactionsRender());
  ensureLastUpdatedElement();
  updateLastUpdatedLabel();
  window.setInterval(updateLastUpdatedLabel, 30000);
  on(elements.settingsBtn, "click", openSettings);
  on(elements.settingsClose, "click", closeSettings);
  on(elements.settingsOverlay, "click", closeSettings);
  on(elements.languageSelect, "change", (event) => setLanguage(event.target.value, { persist: true }));
  on(elements.currencySelect, "change", (event) => setCurrency(event.target.value, { persist: true }));
  on(elements.themeSelect, "change", (event) => applyTheme(event.target.value, { persist: true }));
  on(elements.downloadCsvBtn, "click", exportTransactionsCSV);

  on(elements.monthSelect, "change", (event) => {
    state.selectedMonth = event.target.value;
    refreshData();
  });

  on(elements.periodControls, "click", (event) => {
    const target = event.target.closest("[data-period]");
    if (!target) return;
    const preset = target.getAttribute("data-period");
    if (!preset || preset === state.periodPreset) return;
    applyPeriodPreset(preset);
    closeToolbarMorePanel();
    if (state.periodPreset !== "custom") {
      refreshData();
    }
  });

  on(elements.toolbarMoreBtn, "click", (event) => {
    event.stopPropagation();
    toggleToolbarMorePanel();
  });

  on(elements.toolbarMorePanel, "click", (event) => {
    const presetButton = event.target.closest("[data-custom-preset]");
    if (presetButton) {
      const preset = presetButton.getAttribute("data-custom-preset");
      if (preset) applyCustomRangePreset(preset);
      return;
    }
    const actionButton = event.target.closest("[data-more-action]");
    if (!actionButton) return;
    const action = actionButton.getAttribute("data-more-action");
    handleToolbarMoreAction(action);
  });

  on(elements.periodApply, "click", () => {
    if (elements.periodStart) state.customPeriodStart = elements.periodStart.value;
    if (elements.periodEnd) state.customPeriodEnd = elements.periodEnd.value;
    refreshData();
  });

  on(elements.periodCustom, "click", (event) => {
    const target = event.target.closest("[data-custom-preset]");
    if (!target) return;
    const preset = target.getAttribute("data-custom-preset");
    if (!preset) return;
    applyCustomRangePreset(preset);
  });

  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      typeof closeHistoryEditModal === "function" &&
      elements.historyEditModal &&
      !elements.historyEditModal.hasAttribute("hidden")
    ) {
      closeHistoryEditModal();
    }
    if (event.key === "Escape") {
      closeToolbarMorePanel();
      if (typeof closeSwipedTransaction === "function") {
        closeSwipedTransaction();
      }
    }
  });
  document.addEventListener("click", (event) => {
    if (elements.toolbarMorePanel && !elements.toolbarMorePanel.hasAttribute("hidden")) {
      const inMenu = event.target.closest("#toolbar-more-panel");
      const inButton = event.target.closest("#toolbar-more-btn");
      if (!inMenu && !inButton) {
        closeToolbarMorePanel();
      }
    }
    if (state.historySwipedId && typeof closeSwipedTransaction === "function") {
      const insideCard = event.target.closest(".transaction-card");
      const insideModal = event.target.closest("#history-edit-modal");
      if (!insideCard && !insideModal) {
        closeSwipedTransaction();
      }
    }
  });
  on(document, "visibilitychange", async () => {
    if (document.visibilityState !== "visible") return;
    updateLastUpdatedLabel();
    if (!state.authToken) return;
    const staleFor = Date.now() - (state.lastRefreshedAt || 0);
    if (staleFor > 120000) {
      await refreshSummaryOnly();
    }
  });
  on(window, "focus", updateLastUpdatedLabel);

  let pullStartY = null;
  let pullTriggered = false;
  on(document, "touchstart", (event) => {
    if (!state.authToken) return;
    if (state.activeScreen === "ai") return;
    if (!event.touches || event.touches.length !== 1) return;
    const scrollTop = window.scrollY || document.documentElement.scrollTop || 0;
    if (scrollTop > 2) return;
    pullStartY = event.touches[0].clientY;
    pullTriggered = false;
  });
  on(document, "touchmove", (event) => {
    if (pullStartY === null || pullTriggered || state.refreshInFlight) return;
    const currentY = event.touches && event.touches[0] ? event.touches[0].clientY : pullStartY;
    if (currentY - pullStartY > 90) {
      pullTriggered = true;
      refreshSummaryOnly();
    }
  });
  on(document, "touchend", () => {
    pullStartY = null;
    pullTriggered = false;
  });

  const directionField = elements.transactionForm ? elements.transactionForm.querySelector("select[name='direction']") : null;
  on(directionField, "change", (event) => loadCategories(event.target.value));
  on(elements.historySearch, "input", () => {
    if (typeof applyHistoryFiltersFromControls === "function") applyHistoryFiltersFromControls({ debounce: true });
  });
  on(elements.historyFilterDirection, "change", () => {
    if (typeof applyHistoryFiltersFromControls === "function") applyHistoryFiltersFromControls();
  });
  on(elements.historyFilterCategory, "change", () => {
    if (typeof applyHistoryFiltersFromControls === "function") applyHistoryFiltersFromControls();
  });
  on(elements.historyFilterAmountMin, "input", () => {
    if (typeof applyHistoryFiltersFromControls === "function") applyHistoryFiltersFromControls({ debounce: true });
  });
  on(elements.historyFilterAmountMax, "input", () => {
    if (typeof applyHistoryFiltersFromControls === "function") applyHistoryFiltersFromControls({ debounce: true });
  });
  on(elements.historyFilterEmotion, "change", () => {
    if (typeof applyHistoryFiltersFromControls === "function") applyHistoryFiltersFromControls();
  });
  on(elements.historyFiltersReset, "click", () => {
    if (typeof resetHistoryFilters === "function") resetHistoryFilters();
  });
  on(elements.historyFiltersToggle, "click", () => {
    if (typeof toggleHistoryFiltersPanel === "function") toggleHistoryFiltersPanel();
  });
  (elements.historyDirectionButtons || []).forEach((button) => {
    on(button, "click", () => {
      const value = button.getAttribute("data-history-direction") || "all";
      if (typeof setHistoryQuickFilter === "function") setHistoryQuickFilter("direction", value);
    });
  });
  on(elements.historyActiveFilters, "click", (event) => {
    const target = event.target.closest("[data-history-clear]");
    if (!target) return;
    const key = target.getAttribute("data-history-clear");
    if (!key || typeof clearHistoryFilterTag !== "function") return;
    clearHistoryFilterTag(key);
  });
  on(elements.historyCalendarPrev, "click", () => {
    if (typeof shiftHistoryCalendarMonth === "function") shiftHistoryCalendarMonth(-1);
  });
  on(elements.historyCalendarNext, "click", () => {
    if (typeof shiftHistoryCalendarMonth === "function") shiftHistoryCalendarMonth(1);
  });
  on(elements.historyCalendarMonth, "click", () => {
    if (typeof setHistoryCalendarMode === "function") setHistoryCalendarMode("month");
  });
  on(elements.historyCalendarToday, "click", () => {
    if (typeof jumpHistoryCalendarToday === "function") jumpHistoryCalendarToday();
  });
  on(elements.historyCalendarDays, "click", (event) => {
    if (typeof handleHistoryCalendarDayClick === "function") handleHistoryCalendarDayClick(event);
  });
  on(elements.historyCalendarDays, "keydown", (event) => {
    if (typeof handleHistoryCalendarKeydown === "function") handleHistoryCalendarKeydown(event);
  });
  if (elements.historyCalendarDays && typeof handleHistoryCalendarTouchStart === "function" && typeof handleHistoryCalendarTouchEnd === "function") {
    elements.historyCalendarDays.addEventListener("touchstart", handleHistoryCalendarTouchStart, { passive: true });
    elements.historyCalendarDays.addEventListener("touchend", handleHistoryCalendarTouchEnd, { passive: true });
    elements.historyCalendarDays.addEventListener("touchcancel", () => {
      state.historyCalendarTouchStart = null;
    }, { passive: true });
  }
  if (typeof closeHistoryEditModal === "function") {
    on(elements.historyEditCancel, "click", closeHistoryEditModal);
  }
  on(elements.historyEditForm, "submit", async (event) => {
    event.preventDefault();
    if (typeof submitHistoryEdit === "function") {
      await submitHistoryEdit();
    }
  });
  on(elements.historyEditForm, "change", (event) => {
    if (typeof populateHistoryEditCategoryOptions !== "function" || !elements.historyEditForm) return;
    const target = event.target;
    if (!target || target.name !== "direction") return;
    const categoryInput = elements.historyEditForm.querySelector("select[name='category_id']");
    const selected = categoryInput ? categoryInput.value : "";
    populateHistoryEditCategoryOptions(target.value || "expense", selected);
  });
  (elements.historyEditCloseTriggers || []).forEach((trigger) => {
    if (typeof closeHistoryEditModal === "function") {
      on(trigger, "click", closeHistoryEditModal);
    }
  });
  on(elements.historyEditModal, "click", (event) => {
    if (typeof closeHistoryEditModal === "function" && event.target.closest("[data-history-edit-close]")) {
      closeHistoryEditModal();
    }
  });
  if (elements.transactionsContainer && typeof handleHistoryTouchStart === "function" && typeof handleHistoryTouchEnd === "function") {
    elements.transactionsContainer.addEventListener("touchstart", handleHistoryTouchStart, { passive: true });
    elements.transactionsContainer.addEventListener("touchend", handleHistoryTouchEnd, { passive: true });
  }
  const updateGoalThresholdUI = (rawValue) => {
    const numeric = Number(rawValue) || 0;
    const percent = Math.round(numeric * 100);
    if (elements.goalThresholdValue) {
      elements.goalThresholdValue.textContent = `${percent}%`;
    }
    if (elements.goalThreshold) {
      const min = Number(elements.goalThreshold.min) || 0;
      const max = Number(elements.goalThreshold.max) || 1;
      const normalized = max > min ? ((numeric - min) / (max - min)) * 100 : 0;
      const clamped = Math.min(100, Math.max(0, normalized));
      elements.goalThreshold.style.setProperty("--threshold-fill", `${clamped}%`);
    }
  };
  if (elements.goalThreshold) {
    updateGoalThresholdUI(elements.goalThreshold.value);
    on(elements.goalThreshold, "input", (event) => updateGoalThresholdUI(event.target.value));
  }

  on(elements.scenarioActions, "click", (event) => {
    const target = event.target.closest("[data-scenario]");
    if (!target) return;
    const scenario = target.getAttribute("data-scenario");
    if (!scenario || scenario === state.activeScenario) return;
    state.activeScenario = scenario;
    elements.scenarioActions.querySelectorAll("[data-scenario]").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-scenario") === scenario);
    });
    renderBudgets();
  });

  on(elements.assistantTone, "change", (event) => {
    state.assistantTone = event.target.value || "short";
    localStorage.setItem(STORAGE_KEYS.assistantTone, state.assistantTone);
  });

  const assistantTextarea = elements.assistantForm ? elements.assistantForm.querySelector("textarea[name='question']") : null;
  const resizeAssistantTextarea = () => {
    if (!assistantTextarea) return;
    assistantTextarea.style.height = "auto";
    assistantTextarea.style.height = `${Math.min(assistantTextarea.scrollHeight, 132)}px`;
    scheduleChatLayoutMetricsSync();
  };

  on(assistantTextarea, "input", resizeAssistantTextarea);
  on(assistantTextarea, "focus", () => {
    resizeAssistantTextarea();
    if (elements.assistantHistory) {
      elements.assistantHistory.scrollTop = elements.assistantHistory.scrollHeight;
    }
  });
  resizeAssistantTextarea();

  on(elements.assistantChips, "click", (event) => {
    const target = event.target.closest("[data-prompt-key]");
    if (!target || !elements.assistantForm) return;
    const promptKey = target.getAttribute("data-prompt-key");
    const prompt = promptKey ? t(promptKey) : "";
    const textarea = elements.assistantForm.querySelector("textarea[name='question']");
    if (!textarea) return;
    textarea.value = prompt;
    resizeAssistantTextarea();
    textarea.focus();
  });

  on(elements.transactionForm, "submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(elements.transactionForm);
    const amount = Number(formData.get("amount"));
    if (!Number.isFinite(amount) || amount <= 0) {
      elements.transactionFeedback.textContent = t("transactions_save_error");
      return;
    }
    const payload = {
      amount,
      direction: formData.get("direction"),
      category_id: Number(formData.get("category_id")) || null,
      description: formData.get("description") || null,
      occurred_at: formData.get("occurred_at") || null,
    };
    setTransactionFormPending(true);
    elements.transactionFeedback.textContent = "";
    try {
      const created = await authorizedFetch("/api/v1/web/transactions", { method: "POST", body: JSON.stringify(payload) });
      elements.transactionFeedback.textContent = t("transactions_saved");
      elements.transactionForm.reset();
      const hasHistoryFilters = Boolean(
        state.historySearchQuery ||
          state.historyFilterDirection !== "all" ||
          state.historyFilterCategory !== "all" ||
          state.historyFilterEmotion !== "all" ||
          state.historyFilterAmountMin !== "" ||
          state.historyFilterAmountMax !== ""
      );
      if (created && state.transactionsPage === 0 && !hasHistoryFilters) {
        prependTransactionCard(created);
      } else if (created && state.activeScreen === "history") {
        await resetTransactions();
      }
      await refreshSummaryOnly();
    } catch (error) {
      console.error(error);
      elements.transactionFeedback.textContent = t("transactions_save_error");
    } finally {
      setTransactionFormPending(false);
    }
  });

  on(elements.goalForm, "submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(elements.goalForm);
    const categoryId = Number(formData.get("goal_category_id"));
    const amount = Number(formData.get("goal_amount"));
    const period = formData.get("goal_period");
    const threshold = Number(formData.get("goal_threshold")) || 0.9;
    if (!categoryId || !Number.isFinite(amount) || amount <= 0) {
      elements.goalFeedback.textContent = t("goal_error");
      return;
    }
    const submitBtn = elements.goalForm.querySelector("button[type='submit']");
    if (submitBtn) submitBtn.disabled = true;
    elements.goalFeedback.textContent = "";
    try {
      await authorizedFetch("/api/v1/web/budgets", {
        method: "POST",
        body: JSON.stringify({ category_id: categoryId, amount, period, alert_threshold: threshold }),
      });
      elements.goalForm.reset();
      if (elements.goalThreshold) {
        elements.goalThreshold.value = "0.9";
        if (elements.goalThresholdValue) elements.goalThresholdValue.textContent = "90%";
      }
      elements.goalFeedback.textContent = t("goal_success");
      await refreshData();
    } catch (error) {
      console.error(error);
      elements.goalFeedback.textContent = t("goal_error");
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });

  on(elements.savingsForm, "submit", (event) => {
    event.preventDefault();
    const formData = new FormData(elements.savingsForm);
    const name = (formData.get("savings_name") || "").toString().trim();
    const target = Number(formData.get("savings_target"));
    const current = Number(formData.get("savings_current"));
    const monthly = Number(formData.get("savings_monthly"));
    const goal = {
      id: Date.now(),
      name: name || t("savings_title"),
      target: Number.isFinite(target) ? target : 0,
      current: Number.isFinite(current) ? current : 0,
      monthly: Number.isFinite(monthly) ? monthly : 0,
    };
    const goals = normalizeSavingsGoals(state.savingsGoals).concat(goal);
    saveSavingsGoals(goals);
    if (elements.savingsFeedback) elements.savingsFeedback.textContent = t("savings_saved_feedback");
    elements.savingsForm.reset();
    renderSavingsGoals();
  });

  on(elements.savingsGoals, "click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const card = target.closest("[data-goal-id]");
    if (!card) return;
    const goalId = Number(card.getAttribute("data-goal-id"));
    if (!goalId) return;
    const goals = normalizeSavingsGoals(state.savingsGoals);
    const goalIndex = goals.findIndex((item) => Number(item.id) === goalId);
    if (goalIndex === -1) return;
    if (target.getAttribute("data-action") === "delete-goal") {
      goals.splice(goalIndex, 1);
      saveSavingsGoals(goals);
      renderSavingsGoals();
      return;
    }
    if (target.getAttribute("data-action") === "update-current") {
      const input = card.querySelector("input[name='savings_current']");
      const value = input ? Number(input.value) : NaN;
      goals[goalIndex].current = Number.isFinite(value) ? value : goals[goalIndex].current;
      saveSavingsGoals(goals);
      if (elements.savingsFeedback) elements.savingsFeedback.textContent = t("savings_updated_feedback");
      renderSavingsGoals();
    }
  });

  on(elements.budgets, "click", async (event) => {
    const target = event.target.closest("[data-goal-delete]");
    if (!target) return;
    const goalId = target.getAttribute("data-goal-delete");
    target.disabled = true;
    try {
      await authorizedFetch(`/api/v1/web/budgets/${goalId}`, { method: "DELETE" });
      state.budgets = (state.budgets || []).filter((item) => !item.limit || item.limit.id !== Number(goalId));
      renderBudgets();
      await refreshData();
    } catch (error) {
      console.error(error);
      elements.goalFeedback.textContent = t("goal_delete_error");
    } finally {
      target.disabled = false;
    }
  });

  on(elements.emotionList, "change", (event) => {
    const select = event.target.closest(".emotion-select");
    if (!select) return;
    const categoryId = select.getAttribute("data-category-id");
    if (!categoryId) return;
    const value = select.value;
    if (value) {
      state.emotionLabels[categoryId] = value;
    } else {
      delete state.emotionLabels[categoryId];
    }
    storeObject(STORAGE_KEYS.emotionLabels, state.emotionLabels);
    if (elements.emotionFeedback) elements.emotionFeedback.textContent = t("emotion_saved");
    if (state.historyFilterEmotion && state.historyFilterEmotion !== "all") {
      resetTransactions();
    } else {
      scheduleTransactionsRender({ force: true });
    }
  });

  on(elements.assistantForm, "submit", async (event) => {
    event.preventDefault();
    const questionValue = new FormData(elements.assistantForm).get("question");
    const question = questionValue ? questionValue.toString().trim() : "";
    if (!question) {
      elements.assistantFeedback.textContent = t("assistant_empty");
      elements.assistantFeedback.hidden = false;
      return;
    }
    elements.assistantFeedback.hidden = true;
    const periodPayload = buildAssistantPeriodPayload();
    appendAssistantMessage("user", question, {
      meta: {
        ...periodPayload,
        question,
        tone: state.assistantTone,
      },
    });
    if (assistantTextarea) {
      assistantTextarea.value = "";
      resizeAssistantTextarea();
    } else {
      elements.assistantForm.reset();
    }
    state.assistantPending = true;
    renderAssistantHistory();
    try {
      const response = await authorizedFetch("/api/v1/web/assistant", {
        method: "POST",
        body: JSON.stringify({ question, tone: state.assistantTone, ...periodPayload }),
      });
      appendAssistantMessage("assistant", response.answer, {
        meta: {
          ...periodPayload,
          question,
          tone: state.assistantTone,
        },
      });
    } catch (error) {
      console.error(error);
      elements.assistantFeedback.textContent = t("assistant_error");
      elements.assistantFeedback.hidden = false;
    } finally {
      state.assistantPending = false;
      renderAssistantHistory();
    }
  });

  on(elements.assistantHistory, "click", async (event) => {
    const button = event.target.closest("[data-feedback]");
    if (!button) return;
    const index = Number(button.getAttribute("data-message-index"));
    if (!Number.isFinite(index)) return;
    const entry = state.assistantMessages[index];
    if (!entry || entry.role !== "assistant") return;
    if (entry.feedbackStatus === "sent" || entry.feedbackStatus === "sending") return;
    entry.feedbackStatus = "sending";
    renderAssistantHistory();
    try {
      const payload = buildAssistantFeedbackPayload(entry, index);
      await authorizedFetch("/api/v1/web/assistant-feedback", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      entry.feedbackStatus = "sent";
    } catch (error) {
      console.error(error);
      entry.feedbackStatus = "error";
    } finally {
      renderAssistantHistory();
    }
  });

  on(elements.receiptInput, "change", async (event) => {
    const files = event.target.files || [];
    const file = files[0];
    if (!file) return;
    const validationMessage = validateReceiptFile(file);
    if (validationMessage) {
      updateReceiptPreview(null);
      setReceiptResult(validationMessage, "error");
      event.target.value = "";
      return;
    }
    updateReceiptPreview(file);
    setReceiptResult(t("receipt_loading"), "info");
    try {
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const response = await authorizedFetch("/api/v1/web/receipt", {
        method: "POST",
        body: JSON.stringify({ image_base64: base64 }),
      });
      const amount = response.amount
        ? formatCurrency(convertAmount(response.amount, response.currency || state.baseCurrency))
        : "-";
      setReceiptResult(
        `
        <p><strong>${t("transactions_amount_label")}:</strong> ${amount}</p>
        <p><strong>${t("receipt_merchant_label")}:</strong> ${escapeHtml(response.merchant || "-")}</p>
        <p><strong>${t("transactions_category_label")}:</strong> ${escapeHtml(response.category_hint || "-")}</p>
      `,
        "html"
      );
      if (response.amount && elements.transactionForm) {
        const amountInput = elements.transactionForm.querySelector("input[name='amount']");
        if (amountInput) amountInput.value = response.amount;
      }
      if (response.category_hint && state.categories.length && elements.categoriesSelect) {
        const match = state.categories.find((category) => category.name.toLowerCase() === response.category_hint.toLowerCase());
        if (match) elements.categoriesSelect.value = match.id;
      }
    } catch (error) {
      console.error(error);
      setReceiptResult(t("receipt_error"), "error");
    } finally {
      elements.receiptInput.value = "";
    }
  });

  on(elements.statementInput, "change", async (event) => {
    const files = event.target.files || [];
    const file = files[0];
    if (!file) return;
    const validationMessage = validateStatementFile(file);
    if (validationMessage) {
      setStatementResult(validationMessage, "error");
      event.target.value = "";
      return;
    }
    setStatementResult(t("statement_loading"), "info");
    try {
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const response = await authorizedFetch("/api/v1/web/statement", {
        method: "POST",
        body: JSON.stringify({ file_base64: base64, filename: file.name }),
      });
      const message = (t("statement_success") || "")
        .replace("{imported}", response.imported ?? 0)
        .replace("{skipped}", response.skipped ?? 0)
        .replace("{confidence}", Math.round((response.confidence || 0) * 100));
      setStatementResult(escapeHtml(message), "info");
      await resetTransactions();
      await refreshData();
    } catch (error) {
      console.error(error);
      setStatementResult(t("statement_error"), "error");
    } finally {
      elements.statementInput.value = "";
    }
  });

  on(elements.transactionsContainer, "click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.getAttribute("data-action");
    const transactionId =
      target.getAttribute("data-id") ||
      (target.closest("[data-transaction-id]") && target.closest("[data-transaction-id]").getAttribute("data-transaction-id"));
    if (!action || !transactionId) return;
    await handleHistoryCardAction(action, transactionId, target);
  });

  on(elements.loadMoreBtn, "click", () => loadMoreTransactions());

  on(elements.chartControls, "click", (event) => {
    const button = event.target.closest("[data-chart]");
    if (!button) return;
    const chartType = button.getAttribute("data-chart");
    if (!chartType || chartType === state.chartType) return;
    state.chartType = chartType;
    elements.chartControls.querySelectorAll("[data-chart]").forEach((node) => {
      node.classList.toggle("active", node === button);
    });
    loadChartData();
  });

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-scroll-target]");
    if (!trigger) return;
    const selector = trigger.getAttribute("data-scroll-target");
    if (!selector) return;
    if (trigger.tagName === "A") {
      event.preventDefault();
    }
    scrollToTarget(selector);
  });

  on(elements.allTimeToggle, "click", () => {
    state.showAllTimeTotals = !state.showAllTimeTotals;
    localStorage.setItem("manager_bot_all_time_toggle", state.showAllTimeTotals ? "1" : "0");
    toggleAllTimeVisibility();
    updateAllTimeToggleLabel();
  });

  on(elements.manualInitButton, "click", handleManualInitSubmit);
}

function queueRefresh(type) {
  if (!state.refreshInFlight) return false;
  if (state.pendingRefreshType === "full" || type === "full") {
    state.pendingRefreshType = "full";
  } else {
    state.pendingRefreshType = "summary";
  }
  return true;
}

function runQueuedRefresh() {
  const pendingType = state.pendingRefreshType;
  state.pendingRefreshType = "";
  if (pendingType === "full") {
    refreshData();
    return;
  }
  if (pendingType === "summary") {
    refreshSummaryOnly();
  }
}

async function refreshSummaryOnly() {
  if (queueRefresh("summary")) return;
  state.refreshInFlight = true;
  updateLastUpdatedLabel();
  try {
    const params = buildPeriodParams();
    const overview = await authorizedFetch(`/api/v1/web/overview${params.toString() ? `?${params}` : ""}`);
    renderSummary(overview);
    renderBudgets((overview && overview.budgets) || []);
    cacheOverviewSnapshot(overview);
    markDataRefreshed();
    await Promise.all([loadChartData()]);
  } catch (error) {
    console.error(error);
  } finally {
    state.refreshInFlight = false;
    updateLastUpdatedLabel();
    runQueuedRefresh();
  }
}

async function refreshData() {
  if (queueRefresh("full")) return;
  state.refreshInFlight = true;
  updateLastUpdatedLabel();
  try {
    const params = buildPeriodParams();
    const overview = await authorizedFetch(`/api/v1/web/overview${params.toString() ? `?${params}` : ""}`);
    state.availableMonths = (overview && overview.available_months) || [];
    if (state.periodPreset === "month") {
      if (!state.selectedMonth && state.availableMonths.length) {
        state.selectedMonth = state.availableMonths[0];
      } else if (state.selectedMonth && state.availableMonths.length && !state.availableMonths.includes(state.selectedMonth)) {
        state.selectedMonth = state.availableMonths[0];
      }
      populateMonthSelect();
    }
    renderSummary(overview);
    renderBudgets((overview && overview.budgets) || []);
    cacheOverviewSnapshot(overview);
    markDataRefreshed();
    const refreshJobs = [loadChartData()];
    if (state.activeScreen === "history" || (state.transactionsItems && state.transactionsItems.length)) {
      refreshJobs.push(resetTransactions());
    }
    await Promise.all(refreshJobs);
  } catch (error) {
    console.error(error);
    restoreOverviewSnapshot();
    elements.transactionFeedback.textContent = t("error_general");
  } finally {
    state.refreshInFlight = false;
    updateLastUpdatedLabel();
    runQueuedRefresh();
  }
}

async function bootstrap() {
  applyTheme(state.theme);
  applyTranslations();
  populateMonthSelect();
  applyPeriodPreset(state.periodPreset);
  applyFeatureFlags();
  migrateLegacySavingsGoal();
  if (elements.periodStart) elements.periodStart.value = state.customPeriodStart;
  if (elements.periodEnd) elements.periodEnd.value = state.customPeriodEnd;
  setupScreenNavigation();
  updateGreeting();
  renderAssistantHistory();
  bindEvents();

  void loadPublicConfig();
  void ensureExchangeRates();

  const sessionReady = await initSession();
  if (!sessionReady) {
    showManualAuth(state.initData ? "manual_auth_error_invalid" : "");
    elements.greeting.textContent = t("greeting_no_init");
    return;
  }

  await startAppDataFlow();
}

async function startApplication() {
  try {
    await ensureRuntimeDependencies();
    await bootstrap();
    if (typeof handleTelegramLoginWidget === "function") {
      window.handleTelegramLoginWidget = handleTelegramLoginWidget;
    }
  } catch (error) {
    console.error("Application bootstrap failed", error);
  }
}

startApplication();
