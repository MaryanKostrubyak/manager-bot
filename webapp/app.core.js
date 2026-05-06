// App core logic: i18n, auth/session flow, preferences, and shared UI helpers.
function t(key) {
  const langDict = translations[state.language] || translations.uk;
  return (langDict && langDict[key]) || translations.uk[key] || translations.en[key] || key;
}

function applyTheme(theme, options = {}) {
  const { persist = false } = options;
  const normalized = theme === "light" ? "light" : "dark";
  document.body.classList.remove("theme-light", "theme-dark");
  document.body.classList.add(`theme-${normalized}`);
  state.theme = normalized;
  localStorage.setItem(STORAGE_KEYS.theme, normalized);
  if (persist) persistPreferences();
}

function setManualAuthError(key) {
  if (!elements.manualAuthError) return;
  if (!key) {
    elements.manualAuthError.textContent = "";
    elements.manualAuthError.hidden = true;
    return;
  }
  elements.manualAuthError.textContent = t(key);
  elements.manualAuthError.hidden = false;
}

function showManualAuth(errorKey) {
  // UX: hide manual auth UI in the overview screen.
  if (errorKey) {
    setManualAuthError(errorKey);
  } else {
    setManualAuthError("");
  }
}

function hideManualAuth() {
  if (elements.manualAuth) {
    elements.manualAuth.setAttribute("hidden", "hidden");
  }
  if (elements.manualInitInput) {
    elements.manualInitInput.value = "";
  }
  setManualAuthError("");
}

async function loadPublicConfig() {
  try {
    const response = await fetch("/api/v1/web/config");
    if (!response.ok) return;
    const config = await response.json();
    state.telegramBotUsername = config.telegram_bot_username || "";
    mountTelegramLoginWidget();
  } catch (error) {
    console.warn("Failed to load public config", error);
  }
}

function mountTelegramLoginWidget() {
  if (!elements.telegramLoginContainer) return;
  elements.telegramLoginContainer.innerHTML = "";
  if (!state.telegramBotUsername) return;
  const script = document.createElement("script");
  script.src = "https://telegram.org/js/telegram-widget.js?22";
  script.async = true;
  script.setAttribute("data-telegram-login", state.telegramBotUsername);
  script.setAttribute("data-size", "large");
  script.setAttribute("data-request-access", "write");
  script.setAttribute("data-onauth", "handleTelegramLoginWidget");
  elements.telegramLoginContainer.dataset.username = state.telegramBotUsername;
  elements.telegramLoginContainer.appendChild(script);
}

async function handleTelegramLoginWidget(userPayload) {
  const serialized = serializeTelegramLoginPayload(userPayload);
  if (!serialized) {
    setManualAuthError("manual_auth_error_invalid");
    return;
  }
  setManualAuthError("");
  const success = await authenticateWithTelegram({ login_data: serialized });
  if (!success) {
    setManualAuthError("manual_auth_error_invalid");
  }
}

function applyTranslations() {
  document.documentElement.lang = state.language;
  (elements.i18nTextNodes || []).forEach((node) => {
    const key = node.getAttribute("data-i18n");
    node.textContent = t(key);
  });
  (elements.i18nPlaceholderNodes || []).forEach((node) => {
    const key = node.getAttribute("data-i18n-placeholder");
    node.placeholder = t(key);
  });
  (elements.i18nAriaNodes || []).forEach((node) => {
    const key = node.getAttribute("data-i18n-aria-label");
    node.setAttribute("aria-label", t(key));
  });
  if (elements.languageSelect) elements.languageSelect.value = state.language;
  if (elements.currencySelect) elements.currencySelect.value = state.currency;
  if (elements.themeSelect) elements.themeSelect.value = state.theme;
  if (elements.assistantTone) elements.assistantTone.value = state.assistantTone;
  if (elements.downloadCsvBtn) {
    elements.downloadCsvBtn.textContent = t("settings_download");
    elements.downloadCsvBtn.disabled = false;
  }
  if (elements.loadMoreBtn) {
    elements.loadMoreBtn.textContent = state.hasMoreTransactions ? t("transactions_more") : t("transactions_nomore");
  }
  if (typeof syncHistoryFilterControls === "function") {
    syncHistoryFilterControls();
  }
  if (typeof populateHistoryCategoryOptions === "function") {
    populateHistoryCategoryOptions();
  }
  updatePreferenceSummary();
  updateLastUpdatedLabel();
  renderSavingsGoals();
  renderEmotionTags();
}

function formatShortDate(value) {
  if (!(value instanceof Date)) return "";
  const day = String(value.getDate()).padStart(2, "0");
  const month = String(value.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}.${value.getFullYear()}`;
}

function normalizeSavingsGoals(rawValue) {
  if (Array.isArray(rawValue)) {
    return rawValue;
  }
  if (rawValue && typeof rawValue === "object") {
    return [
      {
        id: Date.now(),
        name: rawValue.name || t("savings_title"),
        target: Number(rawValue.target) || 0,
        current: Number(rawValue.current) || 0,
        monthly: Number(rawValue.monthly) || 0,
      },
    ];
  }
  return [];
}

function saveSavingsGoals(goals) {
  state.savingsGoals = goals;
  storeObject(STORAGE_KEYS.savingsGoals, goals);
}

function renderSavingsGoals() {
  if (!elements.savingsGoals) return;
  const goals = normalizeSavingsGoals(state.savingsGoals);
  state.savingsGoals = goals;
  if (!goals.length) {
    elements.savingsGoals.innerHTML = `<p class="muted">${t("savings_empty")}</p>`;
    return;
  }
  elements.savingsGoals.innerHTML = goals
    .map((goal) => {
      const target = Math.max(0, Number(goal.target) || 0);
      const current = Math.max(0, Number(goal.current) || 0);
      const monthly = Math.max(0, Number(goal.monthly) || 0);
      const percent = target > 0 ? Math.min(100, Math.round((current / target) * 100)) : 0;
      const left = Math.max(0, target - current);
      let eta = t("savings_eta_none");
      if (monthly > 0 && left > 0) {
        const etaDate = new Date();
        etaDate.setMonth(etaDate.getMonth() + Math.ceil(left / monthly));
        eta = formatShortDate(etaDate);
      } else if (target > 0 && left <= 0) {
        eta = t("savings_eta_done");
      }
      return `
        <div class="savings-goal" data-goal-id="${goal.id}">
          <div class="savings-goal__header">
            <div>
              <h4>${escapeHtml(goal.name || t("savings_title"))}</h4>
              <p class="muted">${t("savings_target_label")}: ${formatCurrency(target)}</p>
            </div>
            <span class="savings-percent">${percent}%</span>
          </div>
          <div class="savings-progress__bar">
            <span style="width:${percent}%"></span>
          </div>
          <div class="savings-progress__meta">
            <div>
              <p class="muted">${t("savings_saved_label")}</p>
              <strong>${formatCurrency(current)}</strong>
            </div>
            <div>
              <p class="muted">${t("savings_left_label")}</p>
              <strong>${target ? formatCurrency(left) : "—"}</strong>
            </div>
            <div>
              <p class="muted">${t("savings_eta_label")}</p>
              <strong>${eta}</strong>
            </div>
          </div>
          <div class="savings-goal__actions">
            <label>
              <span class="label-text">${t("savings_current_label")}</span>
              <input type="number" step="0.01" min="0" name="savings_current" value="${current || 0}" />
            </label>
            <button type="button" class="ghost-btn small" data-action="update-current">${t("savings_update")}</button>
            <button type="button" class="ghost-btn small danger" data-action="delete-goal">${t("savings_delete")}</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderEmotionTags() {
  if (!elements.emotionList) return;
  const categories = state.expenseCategories.length ? state.expenseCategories : state.categories;
  if (!categories.length) {
    elements.emotionList.innerHTML = `<p class="muted">${t("category_loading")}</p>`;
    return;
  }
  const items = categories
    .map((category) => {
      const stored = state.emotionLabels[String(category.id)] || "";
      const options = EMOTION_OPTIONS.map((option) => {
        const selected = option.value === stored ? "selected" : "";
        return `<option value="${option.value}" ${selected}>${t(option.labelKey)}</option>`;
      }).join("");
      return `
        <div class="emotion-item">
          <span class="emotion-label">${escapeHtml(category.name)}</span>
          <select class="emotion-select" data-category-id="${category.id}">
            ${options}
          </select>
        </div>
      `;
    })
    .join("");
  elements.emotionList.innerHTML = items;
}

function updatePreferenceSummary() {
  // Placeholder for future preference summary UI; keeps app stable if element is absent.
  // Intentionally no-op because preferences are reflected directly in selects.
}

function resetUserDataViews() {
  if (state.chartInstance && typeof state.chartInstance.destroy === "function") {
    state.chartInstance.destroy();
  }
  state.chartInstance = null;

  if (elements.userName) elements.userName.textContent = "";
  if (elements.userAvatar) {
    elements.userAvatar.style.backgroundImage = "";
    elements.userAvatar.classList.remove("has-photo");
    elements.userAvatar.textContent = "MB";
  }
  if (elements.greeting) elements.greeting.textContent = t("greeting_no_init");
  if (elements.income) elements.income.textContent = formatCurrency(0);
  if (elements.expense) elements.expense.textContent = formatCurrency(0);
  if (elements.net) elements.net.textContent = formatCurrency(0);
  if (elements.allTimeExpense) elements.allTimeExpense.textContent = formatCurrency(0);
  if (elements.allTimeIncome) elements.allTimeIncome.textContent = formatCurrency(0);
  if (elements.budgets) elements.budgets.innerHTML = "";
  if (elements.transactionsContainer) elements.transactionsContainer.innerHTML = "";
  if (elements.chartEmpty) elements.chartEmpty.textContent = "";
  if (elements.chartInsights) elements.chartInsights.innerHTML = "";
  if (elements.chartThreshold) elements.chartThreshold.innerHTML = "";
  if (elements.heatmap) elements.heatmap.innerHTML = "";
  if (elements.monthSelect) elements.monthSelect.innerHTML = "";
  if (elements.loadMoreBtn) {
    elements.loadMoreBtn.textContent = t("transactions_more");
    elements.loadMoreBtn.disabled = false;
  }
  if (elements.statementResult) elements.statementResult.innerHTML = "";
  if (elements.receiptResult) elements.receiptResult.innerHTML = "";
  if (elements.receiptPreview) {
    elements.receiptPreview.hidden = true;
    elements.receiptPreview.innerHTML = "";
  }
  if (elements.assistantHistory) elements.assistantHistory.innerHTML = "";
  if (elements.savingsGoals) elements.savingsGoals.innerHTML = "";
  if (elements.transactionFeedback) elements.transactionFeedback.textContent = "";
  if (elements.goalFeedback) elements.goalFeedback.textContent = "";
  if (elements.savingsFeedback) elements.savingsFeedback.textContent = "";
  if (elements.emotionFeedback) elements.emotionFeedback.textContent = "";
  if (elements.scenarioFeedback) elements.scenarioFeedback.textContent = "";
  if (elements.scenarioRecommendations) elements.scenarioRecommendations.innerHTML = "";
  if (typeof closeHistoryEditModal === "function") {
    closeHistoryEditModal();
  }
}

function clearSessionState(options = {}) {
  const { preserveInitData = false } = options;
  cancelManagedRequest("charts:data");
  cancelManagedRequest("insights:data");
  cancelManagedRequest("transactions:list");
  cancelManagedRequest("categories:list");
  cancelManagedRequest("categories:budget");
  cancelManagedRequest("history:categories:expense");
  cancelManagedRequest("history:categories:income");
  clearAuthToken();
  state.user = null;
  state.overview = null;
  state.categories = [];
  state.expenseCategories = [];
  state.budgets = [];
  state.savingsGoals = readStoredObject(STORAGE_KEYS.savingsGoals, []);
  state.emotionLabels = readStoredObject(STORAGE_KEYS.emotionLabels, {});
  state.availableMonths = [];
  state.selectedMonth = "";
  state.transactionsPage = 0;
  state.hasMoreTransactions = true;
  state.transactionsItems = [];
  if (state.historySearchTimer) {
    window.clearTimeout(state.historySearchTimer);
  }
  state.historySearchQuery = "";
  state.historyFilterDirection = "all";
  state.historyFilterCategory = "all";
  state.historyFilterEmotion = "all";
  state.historyFilterAmountMin = "";
  state.historyFilterAmountMax = "";
  state.historyCalendarMonth = "";
  state.historySelectedDay = "";
  state.historyCalendarMode = "month";
  state.historyCalendarAuto = true;
  state.historyCalendarTouchStart = null;
  state.historyCategories = [];
  state.historyFiltersExpanded = window.innerWidth > 720;
  state.historySwipedId = null;
  state.historyTouchStart = null;
  state.historyEditingId = null;
  state.historySearchTimer = 0;
  state.transactionsLastRangeKey = "";
  state.transactionsLoading = false;
  state.transactionsRenderScheduled = false;
  state.assistantMessages = [];
  state.assistantPending = false;
  state.assistantWelcomeShown = false;
  state.chartType = "category_bar";
  state.baseCurrency = "UAH";
  state.lastRefreshedAt = 0;
  localStorage.removeItem(STORAGE_KEYS.overviewCache);
  localStorage.removeItem(STORAGE_KEYS.lastRefreshedAt);
  if (state.receiptPreviewUrl) {
    URL.revokeObjectURL(state.receiptPreviewUrl);
    state.receiptPreviewUrl = "";
  }
  if (!preserveInitData) {
    state.initData = "";
    state.initDataSource = "none";
    state.hasFreshInitData = false;
    if (auth && typeof auth.clearInitData === "function") {
      auth.clearInitData();
    } else {
      localStorage.removeItem(STORAGE_KEYS.initData);
    }
  }
  resetUserDataViews();
  updateLastUpdatedLabel();
}

function handleUnauthorized() {
  const shouldPreserveInit = state.initDataSource && state.initDataSource !== "storage";
  clearSessionState({ preserveInitData: shouldPreserveInit });
  showManualAuth("");
}

if (resolvedInitData.changed && state.authToken) {
  clearSessionState({ preserveInitData: true });
  state.initData = resolvedInitData.initData;
  state.initDataSource = resolvedInitData.source;
  state.hasFreshInitData = resolvedInitData.fresh;
}

function setLanguage(language, options = {}) {
  const { persist = false, refresh = true } = options;
  state.language = language === "en" ? "en" : "uk";
  localStorage.setItem(STORAGE_KEYS.language, state.language);
  applyTranslations();
  populateMonthSelect();
  updateGreeting();
  syncAssistantWelcomeMessage();
  renderAssistantHistory();
  renderBudgets();
  if (refresh) {
    loadChartData();
    if (state.activeScreen === "history" || (state.transactionsItems && state.transactionsItems.length)) {
      resetTransactions();
    }
  }
  if (persist) persistPreferences();
}

function setCurrency(currency, options = {}) {
  const { persist = false, refresh = true } = options;
  state.currency = currency === "USD" ? "USD" : "UAH";
  localStorage.setItem(STORAGE_KEYS.currency, state.currency);
  renderSummary(state.overview);
  renderBudgets();
  if (refresh) {
    loadChartData();
    if (state.activeScreen === "history" || (state.transactionsItems && state.transactionsItems.length)) {
      resetTransactions();
    }
  }
  if (persist) persistPreferences();
}

async function persistPreferences() {
  if (!state.authToken && !state.initData) return;
  try {
    await authorizedFetch("/api/v1/web/preferences", {
      method: "PATCH",
      body: JSON.stringify({
        language: state.language,
        currency: state.currency,
        theme: state.theme,
      }),
    });
  } catch (error) {
    console.warn("Не вдалося синхронізувати налаштування", error);
  }
}

async function authenticateWithTelegram(payload) {
  if (!payload || (!payload.init_data && !payload.login_data)) {
    return false;
  }
  try {
    clearSessionState({ preserveInitData: Boolean(payload.init_data) });
    const session = await auth.authenticateWithTelegram(payload);
    if (!session) return false;
    if (payload.init_data) {
      state.initData = payload.init_data;
      state.initDataSource = "manual";
      state.hasFreshInitData = false;
      localStorage.setItem(STORAGE_KEYS.initData, payload.init_data);
    } else {
      state.initDataSource = "login_widget";
      state.hasFreshInitData = false;
      if (auth && typeof auth.clearInitData === "function") {
        auth.clearInitData();
      }
    }
    updateUserProfile(session);
    persistAuthToken(session.token, session.token_expires_at);
    hideManualAuth();
    return true;
  } catch (error) {
    console.error(error);
    setManualAuthError("manual_auth_error_invalid");
    return false;
  }
}

async function initSession() {
  try {
    if (state.hasFreshInitData && state.initData) {
      const freshLogin = await authenticateWithTelegram({ init_data: state.initData });
      if (freshLogin) return true;
    }

    if (state.authToken && state.initDataSource === "storage") {
      clearAuthToken();
    }

    if (state.authToken) {
      try {
        const session = await authorizedFetch("/api/v1/web/session");
        if (session) {
          updateUserProfile(session);
          hideManualAuth();
          return true;
        }
      } catch (error) {
        console.warn("Persisted session check failed", error);
        clearSessionState({ preserveInitData: Boolean(state.initData) });
      }
    }

    if (state.initData && state.initDataSource && state.initDataSource !== "storage") {
      const restored = await authenticateWithTelegram({ init_data: state.initData });
      if (restored) return true;
    }

    // Fallback for cases when Telegram init payload was not exposed in runtime.
    if (state.initData) {
      const fallback = await authenticateWithTelegram({ init_data: state.initData });
      if (fallback) return true;
    }

    return false;
  } catch (error) {
    console.warn("Session init failed", error);
    return false;
  }
}

async function startAppDataFlow() {
  restoreOverviewSnapshot();
  await loadCategories();
  await loadBudgetCategories();
  await refreshData();
  renderSavingsGoals();
  renderEmotionTags();
  if (typeof syncHistoryFilterControls === "function") {
    syncHistoryFilterControls();
  }
}

function updateGreeting() {
  if (!elements.greeting) return;
  if (!state.user) {
    elements.greeting.textContent = t("greeting_no_init");
    return;
  }
  const name = [state.user.first_name, state.user.last_name].filter(Boolean).join(" ") || state.user.first_name || "";
  elements.greeting.textContent = t("greeting_named").replace("{name}", name);
}

function updateUserProfile(user) {
  if (!user) return;
  state.user = user;
  if (user.language) setLanguage(user.language, { refresh: false });
  if (user.currency) setCurrency(user.currency, { refresh: false });
  if (user.theme) applyTheme(user.theme);
  if (elements.userName) {
    const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ") || user.first_name || "";
    elements.userName.textContent = fullName || "";
  }
  if (elements.userAvatar) {
    const initials = [user.first_name, user.last_name]
      .filter(Boolean)
      .map((value) => value.trim().charAt(0).toUpperCase())
      .join("")
      .slice(0, 2);
    if (user.photo_url) {
      elements.userAvatar.style.backgroundImage = `url(${user.photo_url})`;
      elements.userAvatar.classList.add("has-photo");
      elements.userAvatar.textContent = "";
    } else {
      elements.userAvatar.style.backgroundImage = "";
      elements.userAvatar.classList.remove("has-photo");
      elements.userAvatar.textContent = initials || "MB";
    }
  }
  updateGreeting();
}

function buildPeriodParams() {
  const params = new URLSearchParams();
  if (state.periodPreset === "month") {
    if (state.selectedMonth) params.set("month", state.selectedMonth);
  } else {
    params.set("period", state.periodPreset);
    if (state.periodPreset === "custom") {
      if (state.customPeriodStart) params.set("start", state.customPeriodStart);
      if (state.customPeriodEnd) params.set("end", state.customPeriodEnd);
    }
  }
  return params;
}

function togglePeriodControls() {
  if (!elements.periodCustom) return;
  const isCustom = state.periodPreset === "custom";
  elements.periodCustom.hidden = !isCustom;
  if (elements.monthSelect) elements.monthSelect.disabled = state.periodPreset !== "month";
}

function currentLocale() {
  return state.language === "en" ? "en-US" : "uk-UA";
}

function getCurrencyFormatter(currency = state.currency) {
  const locale = currentLocale();
  const key = `${locale}|${currency}`;
  if (!formatterCache.currency.has(key)) {
    formatterCache.currency.set(
      key,
      new Intl.NumberFormat(locale, {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
      })
    );
  }
  return formatterCache.currency.get(key);
}

function formatCurrency(value, currency = state.currency) {
  return getCurrencyFormatter(currency).format(Number(value) || 0);
}

function formatMultiline(value = "") {
  return escapeHtml(value).replace(/\n/g, "<br />");
}

function sanitizeAssistantInline(value = "") {
  let text = String(value ?? "");
  text = text.replace(/`{1,3}([^`]+)`{1,3}/g, "$1");
  text = text.replace(/\*\*(.*?)\*\*/g, "$1");
  text = text.replace(/__(.*?)__/g, "$1");
  text = text.replace(/\*(.*?)\*/g, "$1");
  text = text.replace(/_(.*?)_/g, "$1");
  text = text.replace(/\s+#\s*/g, " ");
  return text.trim();
}

function parseAssistantBlocks(raw = "") {
  const text = String(raw ?? "").replace(/\r\n/g, "\n");
  const lines = text.split("\n");
  const blocks = [];
  let paragraph = [];
  let list = null;
  let inFence = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const content = paragraph.join("\n").trim();
    if (content) {
      blocks.push({ type: "paragraph", text: content });
    }
    paragraph = [];
  };

  const flushList = () => {
    if (!list || !list.items.length) {
      list = null;
      return;
    }
    blocks.push(list);
    list = null;
  };

  const startList = (type) => {
    if (list && list.type === type) return;
    flushList();
    list = { type, items: [] };
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (/^```/.test(trimmed)) {
      inFence = !inFence;
      return;
    }
    if (inFence) {
      paragraph.push(line);
      return;
    }
    if (!trimmed) {
      flushParagraph();
      flushList();
      return;
    }
    const headingMatch = trimmed.match(/^#{1,6}\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", text: headingMatch[1] });
      return;
    }
    const bulletMatch = trimmed.match(/^[-*•]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      startList("ul");
      list.items.push(bulletMatch[1]);
      return;
    }
    const orderedMatch = trimmed.match(/^\d{1,2}[.)]\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      startList("ol");
      list.items.push(orderedMatch[1]);
      return;
    }
    if (list) flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  return blocks;
}

function renderAssistantContent(raw = "") {
  const blocks = parseAssistantBlocks(raw);
  if (!blocks.length) {
    return `<p>${formatMultiline(sanitizeAssistantInline(raw))}</p>`;
  }
  return blocks
    .map((block) => {
      if (block.type === "heading") {
        return `<div class="assistant-heading">${escapeHtml(sanitizeAssistantInline(block.text))}</div>`;
      }
      if (block.type === "ul" || block.type === "ol") {
        const items = block.items
          .map((item) => `<li>${formatMultiline(sanitizeAssistantInline(item))}</li>`)
          .join("");
        return `<${block.type} class="assistant-list">${items}</${block.type}>`;
      }
      return `<p>${formatMultiline(sanitizeAssistantInline(block.text))}</p>`;
    })
    .join("");
}

function convertAmount(value, fromCurrency) {
  if (!Number.isFinite(Number(value))) return 0;
  const base = fromCurrency || state.baseCurrency || "UAH";
  if (base === state.currency) return Number(value);
  const fromRate = state.exchangeRates[base] || 1;
  const toRate = state.exchangeRates[state.currency] || 1;
  return (Number(value) * fromRate) / toRate;
}

function isAbortError(error) {
  return Boolean(error && (error.name === "AbortError" || String(error.message || "").toLowerCase().includes("abort")));
}

function formatDateLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const locale = currentLocale();
  if (!formatterCache.date.has(locale)) {
    formatterCache.date.set(
      locale,
      new Intl.DateTimeFormat(locale, {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    );
  }
  const formatter = formatterCache.date.get(locale);
  return formatter.format(date);
}

function formatTimeLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const locale = currentLocale();
  if (!formatterCache.time.has(locale)) {
    formatterCache.time.set(
      locale,
      new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
      })
    );
  }
  const formatter = formatterCache.time.get(locale);
  return formatter.format(date);
}

function syncChatLayoutMetrics() {
  if (elements.bottomNav) {
    const navHeight = Math.ceil(elements.bottomNav.getBoundingClientRect().height || 0);
    if (navHeight > 0 && navHeight !== state.chatNavHeight) {
      state.chatNavHeight = navHeight;
      document.documentElement.style.setProperty("--chat-nav-height", `${navHeight}px`);
    }
  }
  if (elements.assistantForm) {
    const composerHeight = Math.ceil(elements.assistantForm.getBoundingClientRect().height || 0);
    if (composerHeight > 0 && composerHeight !== state.chatComposerHeight) {
      state.chatComposerHeight = composerHeight;
      document.documentElement.style.setProperty("--chat-composer-space", `${composerHeight + 12}px`);
    }
  }
}

function scheduleChatLayoutMetricsSync() {
  if (state.chatLayoutSyncScheduled) return;
  state.chatLayoutSyncScheduled = true;
  window.requestAnimationFrame(() => {
    state.chatLayoutSyncScheduled = false;
    syncChatLayoutMetrics();
  });
}

function ensureLastUpdatedElement() {
  if (elements.lastUpdated) return;
  if (!elements.periodControls || !elements.periodControls.parentElement) return;
  const node = document.createElement("p");
  node.id = "last-updated";
  node.className = "last-updated muted";
  node.setAttribute("aria-live", "polite");
  elements.periodControls.parentElement.appendChild(node);
  elements.lastUpdated = node;
}

function buildOverviewCacheKey() {
  return [
    state.periodPreset,
    state.selectedMonth || "",
    state.customPeriodStart || "",
    state.customPeriodEnd || "",
  ].join("|");
}

function cacheOverviewSnapshot(overview) {
  if (!overview) return;
  storeObject(STORAGE_KEYS.overviewCache, {
    key: buildOverviewCacheKey(),
    data: overview,
    saved_at: Date.now(),
  });
}

function restoreOverviewSnapshot() {
  const cached = readStoredObject(STORAGE_KEYS.overviewCache, null);
  if (!cached || !cached.data || cached.key !== buildOverviewCacheKey()) return false;
  renderSummary(cached.data);
  renderBudgets((cached.data && cached.data.budgets) || []);
  return true;
}

function formatRelativeRefreshTime(timestamp) {
  if (!timestamp) return "";
  const locale = currentLocale();
  if (!formatterCache.relativeTime.has(locale)) {
    formatterCache.relativeTime.set(locale, new Intl.RelativeTimeFormat(locale, { numeric: "auto" }));
  }
  const formatter = formatterCache.relativeTime.get(locale);
  const deltaSeconds = Math.round((timestamp - Date.now()) / 1000);
  const absSeconds = Math.abs(deltaSeconds);
  if (absSeconds < 60) return formatter.format(deltaSeconds, "second");
  const deltaMinutes = Math.round(deltaSeconds / 60);
  if (Math.abs(deltaMinutes) < 60) return formatter.format(deltaMinutes, "minute");
  const deltaHours = Math.round(deltaMinutes / 60);
  if (Math.abs(deltaHours) < 24) return formatter.format(deltaHours, "hour");
  const deltaDays = Math.round(deltaHours / 24);
  return formatter.format(deltaDays, "day");
}

function updateLastUpdatedLabel() {
  if (!elements.lastUpdated) return;
  if (state.refreshInFlight) {
    elements.lastUpdated.textContent = t("hero_refreshing");
    elements.lastUpdated.classList.add("is-refreshing");
    return;
  }
  elements.lastUpdated.classList.remove("is-refreshing");
  if (!state.lastRefreshedAt) {
    elements.lastUpdated.textContent = t("hero_pull_hint");
    return;
  }
  const relative = formatRelativeRefreshTime(state.lastRefreshedAt);
  elements.lastUpdated.textContent = t("hero_updated_at").replace("{time}", relative || t("hero_pull_hint"));
}

function markDataRefreshed() {
  state.lastRefreshedAt = Date.now();
  localStorage.setItem(STORAGE_KEYS.lastRefreshedAt, String(state.lastRefreshedAt));
  updateLastUpdatedLabel();
}

function setActiveScreen(screen) {
  if (!screen) return;
  state.activeScreen = screen;
  (elements.screenNodes || []).forEach((node) => {
    node.classList.toggle("active", node.getAttribute("data-screen") === screen);
  });
  (elements.screenNavButtons || []).forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-screen-target") === screen);
  });
  document.body.setAttribute("data-active-screen", screen);
  syncChatLayoutMetrics();
  if (screen === "history") {
    if (typeof renderHistoryCalendar === "function") {
      renderHistoryCalendar({ smooth: false });
    }
    if (typeof loadHistoryFilterCategories === "function" && !(state.historyCategories || []).length) {
      loadHistoryFilterCategories();
    }
    if (typeof resetTransactions === "function" && !(state.transactionsItems || []).length && !state.transactionsLoading) {
      resetTransactions();
    } else {
      scheduleTransactionsRender({ force: true });
    }
  }
  if (screen !== "overview") {
    closeToolbarMorePanel();
  }
  if (screen === "ai") {
    ensureAssistantWelcome();
    renderAssistantHistory();
  }
}

function setupScreenNavigation() {
  setActiveScreen(state.activeScreen);
  on(elements.bottomNav, "click", (event) => {
    const target = event.target.closest("[data-screen-target]");
    if (!target) return;
    const screen = target.getAttribute("data-screen-target");
    if (!screen || screen === state.activeScreen) return;
    setActiveScreen(screen);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function scrollToTarget(selector) {
  if (!selector) return;
  const target = document.querySelector(selector);
  if (!target) return;
  const parentScreen = target.closest("[data-screen]");
  if (parentScreen) {
    const screenName = parentScreen.getAttribute("data-screen");
    if (screenName && screenName !== state.activeScreen) {
      setActiveScreen(screenName);
    }
  }
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function handleManualInitSubmit() {
  const rawValue = elements.manualInitInput ? elements.manualInitInput.value.trim() : "";
  if (!rawValue) {
    setManualAuthError("manual_auth_error_empty");
    return;
  }
  const loginData = authModule.normalizeLoginData(rawValue);
  const initData = authModule.normalizeInitData(rawValue);
  const payload = loginData ? { login_data: loginData } : initData ? { init_data: initData } : null;
  if (!payload) {
    setManualAuthError("manual_auth_error_invalid");
    return;
  }
  elements.manualInitButton.disabled = true;
  setManualAuthError("");
  const sessionReady = await authenticateWithTelegram(payload);
  if (sessionReady) {
    await startAppDataFlow();
  }
  elements.manualInitButton.disabled = false;
}

function populateMonthSelect() {
  if (!elements.monthSelect) return;
  const options = ['<option value="">', t("hero_month_label"), "</option>"];
  const months = state.availableMonths && state.availableMonths.length ? state.availableMonths : [];
  months.forEach((value) => {
    const [year, month] = value.split("-");
    const labelDate = new Date(Number(year), Number(month) - 1, 1);
    const label = labelDate.toLocaleDateString(state.language === "en" ? "en-US" : "uk-UA", {
      month: "long",
      year: "numeric",
    });
    options.push(`<option value="${value}">${label.charAt(0).toUpperCase() + label.slice(1)}</option>`);
  });
  elements.monthSelect.innerHTML = options.join("");
  elements.monthSelect.value = state.selectedMonth;
}

async function ensureExchangeRates() {
  try {
    const response = await fetch("https://open.er-api.com/v6/latest/UAH");
    const payload = await response.json();
    if (payload.result === "success" && payload.rates && payload.rates.USD) {
      state.exchangeRates.USD = 1 / payload.rates.USD;
    }
  } catch (error) {
    console.warn("Exchange rate fetch failed", error);
  }
}

function renderSummary(overview) {
  if (!overview || !overview.summary) return;
  state.overview = overview;
  state.baseCurrency = overview.summary.currency || "UAH";
   if (Array.isArray(overview.available_months)) {
    state.availableMonths = overview.available_months;
  }
  if (elements.income) {
    elements.income.textContent = formatCurrency(convertAmount(overview.summary.total_income, state.baseCurrency));
  }
  if (elements.expense) {
    elements.expense.textContent = formatCurrency(convertAmount(overview.summary.total_expense, state.baseCurrency));
  }
  if (elements.net) {
    elements.net.textContent = formatCurrency(convertAmount(overview.summary.net, state.baseCurrency));
  }
  if (elements.allTimeExpense && overview.all_time_summary) {
    elements.allTimeExpense.textContent = formatCurrency(
      convertAmount(overview.all_time_summary.total_expense, overview.all_time_summary.currency || state.baseCurrency)
    );
  }
  if (elements.allTimeIncome && overview.all_time_summary) {
    elements.allTimeIncome.textContent = formatCurrency(
      convertAmount(overview.all_time_summary.total_income, overview.all_time_summary.currency || state.baseCurrency)
    );
  }
  toggleAllTimeVisibility();
  updateAllTimeToggleLabel();
}

function renderBudgets(items) {
  if (Array.isArray(items)) {
    state.budgets = items;
  }
  if (!elements.budgets) return;
  renderScenarioRecommendations();
  const list = state.budgets || [];
  if (!list.length) {
    elements.budgets.innerHTML = `<p class='muted'>${t("transactions_empty")}</p>`;
    return;
  }
  const scenario = BUDGET_SCENARIOS[state.activeScenario] || BUDGET_SCENARIOS.normal;
  elements.budgets.innerHTML = list
    .map((item) => {
      const percent = Math.min(100, Math.round(item.percent || 0));
      const spent = formatCurrency(convertAmount(item.spent, state.baseCurrency));
      const limitAmount = item.limit && item.limit.amount ? item.limit.amount : 0;
      const limit = formatCurrency(convertAmount(limitAmount, state.baseCurrency));
      const remaining = formatCurrency(convertAmount(item.remaining, state.baseCurrency));
      const categoryName = item.limit && item.limit.category_name ? item.limit.category_name : t("category_none");
      const goalId = item.limit && item.limit.id ? item.limit.id : "";
      const recommendedMultiplier = getScenarioMultiplier(categoryName, scenario);
      const recommendedAmount = limitAmount ? limitAmount * recommendedMultiplier : 0;
      const recommendedLabel = formatCurrency(convertAmount(recommendedAmount, state.baseCurrency));
      const delta = limitAmount ? Math.round((recommendedMultiplier - 1) * 100) : 0;
      const showRecommendation = state.activeScenario !== "normal" && limitAmount > 0;
      const recommendationLine = showRecommendation
        ? `<div class="scenario-recommendation"><span>${t("scenario_recommended")}: ${recommendedLabel}</span><span class="muted">${t("scenario_delta")}: ${delta > 0 ? "+" : ""}${delta}%</span></div>`
        : "";
      return `
        <div class="budget-row">
          <div class="budget-details">
            <strong>${escapeHtml(categoryName)}</strong>
            <p class="muted">${spent} / ${limit}</p>
            <div class="progress"><span style="width:${percent}%"></span></div>
            <span class="muted">${percent}% · ${remaining}</span>
            ${recommendationLine}
          </div>
          <button class="ghost-btn small danger" data-goal-delete="${goalId}">${t("goal_delete_action")}</button>
        </div>
      `;
    })
    .join("");
}

function getScenarioMultiplier(categoryName, scenario) {
  if (!scenario) return 1;
  const base = scenario.multiplier || 1;
  const name = (categoryName || "").toLowerCase();
  const adjustments = scenario.adjust || [];
  for (const rule of adjustments) {
    if (!rule.keywords) continue;
    if (rule.keywords.some((keyword) => name.includes(keyword))) {
      return rule.multiplier || base;
    }
  }
  return base;
}

function renderScenarioRecommendations() {
  if (!elements.scenarioFeedback || !elements.scenarioRecommendations) return;
  const scenario = BUDGET_SCENARIOS[state.activeScenario] || BUDGET_SCENARIOS.normal;
  const hintKey =
    state.activeScenario === "economy"
      ? "scenario_economy_hint"
      : state.activeScenario === "vacation"
      ? "scenario_vacation_hint"
      : "scenario_normal_hint";
  elements.scenarioFeedback.textContent = t(hintKey);
  const tips = (scenario && scenario.tips ? scenario.tips : []).map((key) => t(key)).filter(Boolean);
  elements.scenarioRecommendations.innerHTML = tips.map((tip) => `<p class="muted">${tip}</p>`).join("");
}

function applyPeriodPreset(preset) {
  state.periodPreset = preset || "month";
  if (elements.periodControls) {
    elements.periodControls.querySelectorAll("[data-period]").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-period") === state.periodPreset);
    });
  }
  if (elements.toolbarMoreBtn && elements.toolbarMorePanel && elements.toolbarMorePanel.hasAttribute("hidden")) {
    elements.toolbarMoreBtn.classList.toggle("active", state.periodPreset === "custom");
  }
  togglePeriodControls();
}

function formatLocalDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function closeToolbarMorePanel() {
  if (!elements.toolbarMorePanel) return;
  elements.toolbarMorePanel.setAttribute("hidden", "hidden");
  if (elements.toolbarMoreBtn) {
    elements.toolbarMoreBtn.classList.toggle("active", state.periodPreset === "custom");
    elements.toolbarMoreBtn.setAttribute("aria-expanded", "false");
  }
}

function openToolbarMorePanel() {
  if (!elements.toolbarMorePanel) return;
  elements.toolbarMorePanel.removeAttribute("hidden");
  if (elements.toolbarMoreBtn) {
    elements.toolbarMoreBtn.classList.add("active");
    elements.toolbarMoreBtn.setAttribute("aria-expanded", "true");
  }
}

function toggleToolbarMorePanel() {
  if (!elements.toolbarMorePanel) return;
  if (elements.toolbarMorePanel.hasAttribute("hidden")) {
    openToolbarMorePanel();
  } else {
    closeToolbarMorePanel();
  }
}

function applyCustomRangePreset(preset) {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let start = new Date(end);
  let finish = new Date(end);

  if (preset === "this_month") {
    start = new Date(end.getFullYear(), end.getMonth(), 1);
  } else if (preset === "prev_month") {
    start = new Date(end.getFullYear(), end.getMonth() - 1, 1);
    finish = new Date(end.getFullYear(), end.getMonth(), 0);
  } else if (preset === "last_90d") {
    start.setDate(start.getDate() - 89);
  } else {
    return;
  }

  const startValue = formatLocalDateInput(start);
  const endValue = formatLocalDateInput(finish);
  state.customPeriodStart = startValue;
  state.customPeriodEnd = endValue;
  if (elements.periodStart) elements.periodStart.value = startValue;
  if (elements.periodEnd) elements.periodEnd.value = endValue;
  applyPeriodPreset("custom");
  closeToolbarMorePanel();
  refreshData();
}

function setChartType(chartType) {
  if (!chartType || chartType === state.chartType) return;
  state.chartType = chartType;
  if (elements.chartControls) {
    elements.chartControls.querySelectorAll("[data-chart]").forEach((node) => {
      node.classList.toggle("active", node.getAttribute("data-chart") === chartType);
    });
  }
  loadChartData();
}

function handleToolbarMoreAction(action) {
  if (!action) return;
  if (action === "open-custom") {
    applyPeriodPreset("custom");
    closeToolbarMorePanel();
    if (elements.periodCustom) {
      elements.periodCustom.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    if (elements.periodStart) elements.periodStart.focus();
    return;
  }
  if (action === "open-categories") {
    closeToolbarMorePanel();
    if (state.activeScreen !== "overview") {
      setActiveScreen("overview");
    }
    setChartType("category_bar");
    scrollToTarget(".chart-panel");
    return;
  }
  if (action === "open-tags") {
    closeToolbarMorePanel();
    if (state.activeScreen !== "goals") {
      setActiveScreen("goals");
    }
    scrollToTarget("#emotion-list");
  }
}

function setCategoryStatus(message = "", variant = "muted") {
  if (!elements.categoryLoadingIndicator) return;
  elements.categoryLoadingIndicator.textContent = message;
  elements.categoryLoadingIndicator.hidden = !message;
  elements.categoryLoadingIndicator.classList.toggle("error", variant === "error");
}

function setTransactionFormPending(isPending) {
  if (!elements.transactionForm) return;
  elements.transactionForm.querySelectorAll("input, select, button").forEach((control) => {
    control.disabled = isPending;
  });
  if (elements.transactionSubmitState) {
    elements.transactionSubmitState.textContent = isPending ? t("transactions_saving") : "";
    elements.transactionSubmitState.hidden = !isPending;
  }
  const submitBtn = elements.transactionForm.querySelector("button[type='submit']");
  if (submitBtn) submitBtn.textContent = isPending ? t("transactions_saving") : t("transactions_submit");
}

function ensureAssistantWelcome() {
  if (state.assistantWelcomeShown) return;
  state.assistantMessages.push({
    role: "assistant",
    content: t("assistant_welcome"),
    detail: t("assistant_welcome_examples"),
    timestamp: new Date().toISOString(),
    variant: "welcome",
  });
  state.assistantWelcomeShown = true;
}

function syncAssistantWelcomeMessage() {
  const welcome = state.assistantMessages.find((message) => message.variant === "welcome");
  if (!welcome) return;
  welcome.content = t("assistant_welcome");
  welcome.detail = t("assistant_welcome_examples");
}

  function appendAssistantMessage(role, content, options = {}) {
    if (!content) return;
    state.assistantMessages.push({
      role,
      content,
      detail: options.detail || "",
      timestamp: options.timestamp || new Date().toISOString(),
      variant: options.variant || "",
      meta: options.meta || {},
      feedbackStatus: options.feedbackStatus || "",
    });
  }

function renderAssistantHistory() {
  if (!elements.assistantHistory) return;
  if (!state.assistantMessages.length && !state.assistantPending) {
    elements.assistantHistory.innerHTML = `<p class="muted placeholder">${t("assistant_history_placeholder")}</p>`;
    return;
  }
  const youLabel = t("assistant_you");
    const items = state.assistantMessages
      .map((entry, index) => {
        const timeLabel = formatTimeLabel(entry.timestamp);
        const metaLabel = entry.role === "user" ? youLabel : "AI";
        const messageClass = entry.role === "user" ? "user" : "ai";
        const contentHtml =
          entry.role === "user"
            ? `<p>${formatMultiline(entry.content)}</p>`
            : `<div class="assistant-content">${renderAssistantContent(entry.content)}</div>`;
        const detailHtml = entry.detail
          ? entry.role === "user"
            ? `<p class="muted">${formatMultiline(entry.detail)}</p>`
            : `<div class="assistant-detail">${renderAssistantContent(entry.detail)}</div>`
          : "";
        const feedbackVisible = entry.role === "assistant" && entry.variant !== "welcome";
        const feedbackLocked = entry.feedbackStatus === "sent" || entry.feedbackStatus === "sending";
        const feedbackLabel =
          entry.feedbackStatus === "sent" ? t("assistant_feedback_thanks") : t("assistant_feedback_wrong");
        const feedbackDisabled = feedbackLocked ? "disabled" : "";
        const feedbackError =
          entry.feedbackStatus === "error"
            ? `<span class="assistant-feedback-error">${t("assistant_feedback_error")}</span>`
            : "";
        const feedbackHtml = feedbackVisible
          ? `
            <div class="assistant-feedback">
              <button type="button" class="assistant-feedback-btn" data-feedback="wrong" data-message-index="${index}" ${feedbackDisabled}>
                ${feedbackLabel}
              </button>
              ${feedbackError}
            </div>
          `
          : "";
        return `
          <div class="assistant-message ${messageClass}">
            <div class="assistant-meta">
              <span>${metaLabel}</span>
              ${timeLabel ? `<span>${timeLabel}</span>` : ""}
            </div>
            <div class="assistant-bubble">
              ${contentHtml}
              ${detailHtml}
            </div>
            ${feedbackHtml}
          </div>
        `;
      })
      .join("");
  const pending = state.assistantPending
    ? `
        <div class="assistant-message ai pending">
          <div class="assistant-meta"><span>AI</span></div>
          <div class="assistant-bubble">
            <div class="assistant-typing" aria-hidden="true"><span></span><span></span><span></span></div>
            <p class="muted">${t("assistant_pending")}</p>
          </div>
        </div>
      `
    : "";
  elements.assistantHistory.innerHTML = items + pending;
  elements.assistantHistory.scrollTop = elements.assistantHistory.scrollHeight;
}


async function loadCategories(direction = "expense") {
  if (!elements.categoriesSelect) return;
  setCategoryStatus(t("category_loading"));
  elements.categoriesSelect.disabled = true;
  elements.categoriesSelect.innerHTML = `<option value="" disabled selected>${t("category_loading")}</option>`;
  try {
    const categories = await authorizedFetch(`/api/v1/web/categories?direction=${direction}`, {
      cancelKey: "categories:list",
      cancelPrevious: true,
    });
    state.categories = categories || [];
    if (direction === "expense") {
      state.expenseCategories = state.categories;
    }
    if (!state.categories.length) {
      elements.categoriesSelect.innerHTML = `<option value="" disabled>${t("category_none")}</option>`;
      setCategoryStatus(t("category_none"), "error");
      return;
    }
    const options = ['<option value="" disabled selected>', t("transactions_category_placeholder"), "</option>"]
      .concat(state.categories.map((category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`))
      .join("");
    elements.categoriesSelect.innerHTML = options;
    elements.categoriesSelect.disabled = false;
    setCategoryStatus("");
    if (direction === "expense") {
      renderEmotionTags();
    }
  } catch (error) {
    if (isAbortError(error)) return;
    console.error(error);
    elements.categoriesSelect.innerHTML = `<option value="" disabled>${t("category_error")}</option>`;
    setCategoryStatus(t("category_error"), "error");
  }
}

async function loadBudgetCategories() {
  if (!elements.goalCategorySelect) return;
  toggleGoalFormAvailability(true, t("category_loading"));
  const existingCategories =
    (Array.isArray(state.budgetCategories) && state.budgetCategories.length && state.budgetCategories) ||
    (Array.isArray(state.expenseCategories) && state.expenseCategories.length && state.expenseCategories) ||
    [];
  if (existingCategories.length) {
    state.budgetCategories = existingCategories;
    renderEmotionTags();
    elements.goalCategorySelect.innerHTML = state.budgetCategories
      .map((category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`)
      .join("");
    toggleGoalFormAvailability(false);
    return;
  }
  try {
    const categories = await authorizedFetch(`/api/v1/web/categories?direction=expense`, {
      cancelKey: "categories:budget",
      cancelPrevious: true,
    });
    state.budgetCategories = categories || [];
    state.expenseCategories = state.budgetCategories;
    renderEmotionTags();
    if (!state.budgetCategories.length) {
      toggleGoalFormAvailability(true, t("category_none"));
      return;
    }
    elements.goalCategorySelect.innerHTML = state.budgetCategories
      .map((category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`)
      .join("");
    toggleGoalFormAvailability(false);
  } catch (error) {
    if (isAbortError(error)) return;
    console.error(error);
    toggleGoalFormAvailability(true, t("category_error"));
  }
}

function toggleGoalFormAvailability(disabled, placeholderText) {
  if (elements.goalCategorySelect) {
    elements.goalCategorySelect.disabled = disabled;
    if (placeholderText) elements.goalCategorySelect.innerHTML = `<option value="">${placeholderText}</option>`;
  }
  if (elements.goalForm) {
    const submitBtn = elements.goalForm.querySelector("button[type='submit']");
    if (submitBtn) submitBtn.disabled = disabled;
  }
}

