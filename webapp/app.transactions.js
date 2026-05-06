// App transactions: history filters, swipe actions, edit flow, and export/settings helpers.
function createTransactionSpacer(height) {
  const spacer = document.createElement("div");
  spacer.className = "transactions-spacer";
  spacer.setAttribute("aria-hidden", "true");
  spacer.style.height = `${Math.max(0, Math.round(height))}px`;
  return spacer;
}

function transactionTimestamp(item) {
  const date = item && item.occurred_at ? new Date(item.occurred_at) : null;
  return date && Number.isFinite(date.getTime()) ? date.getTime() : 0;
}

function sortTransactionsInState() {
  state.transactionsItems = (state.transactionsItems || []).slice().sort((a, b) => transactionTimestamp(b) - transactionTimestamp(a));
}

function historyDayKey(value) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "unknown";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatHistoryDayLabel(dayKey) {
  if (!dayKey || dayKey === "unknown") return t("history_day_unknown");
  const [year, month, day] = dayKey.split("-").map((part) => Number(part));
  const date = new Date(year, (month || 1) - 1, day || 1);
  if (!Number.isFinite(date.getTime())) return dayKey;
  return date.toLocaleDateString(currentLocale(), { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}

function formatDateInputValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isValidMonthKey(value) {
  return /^\d{4}-\d{2}$/.test(String(value || ""));
}

function isValidDayKey(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
}

function monthKeyFromDate(date) {
  if (!(date instanceof Date) || !Number.isFinite(date.getTime())) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function dayKeyFromDate(date) {
  if (!(date instanceof Date) || !Number.isFinite(date.getTime())) return "";
  return `${monthKeyFromDate(date)}-${String(date.getDate()).padStart(2, "0")}`;
}

function parseMonthKey(value) {
  if (!isValidMonthKey(value)) return null;
  const [yearPart, monthPart] = value.split("-");
  const year = Number(yearPart);
  const month = Number(monthPart);
  if (!Number.isFinite(year) || !Number.isFinite(month) || month < 1 || month > 12) return null;
  return { year, month };
}

function historyCalendarWeekStart() {
  const locale = currentLocale();
  return locale === "en-US" ? 0 : 1;
}

function addDaysToDayKey(dayKey, daysDelta) {
  if (!isValidDayKey(dayKey)) return "";
  const [yearPart, monthPart, dayPart] = dayKey.split("-").map((part) => Number(part));
  const date = new Date(yearPart, monthPart - 1, dayPart + (Number(daysDelta) || 0));
  if (!Number.isFinite(date.getTime())) return "";
  return dayKeyFromDate(date);
}

function ensureHistoryCalendarState() {
  const selectedMonth = isValidMonthKey(state.selectedMonth) ? state.selectedMonth : "";
  if (!isValidMonthKey(state.historyCalendarMonth)) {
    state.historyCalendarMonth = selectedMonth || monthKeyFromDate(new Date());
    state.historyCalendarAuto = true;
  } else if (state.historyCalendarAuto && selectedMonth && state.historyCalendarMonth !== selectedMonth) {
    state.historyCalendarMonth = selectedMonth;
  }
  if (!isValidMonthKey(state.historyCalendarMonth)) {
    state.historyCalendarMonth = monthKeyFromDate(new Date());
  }

  if (!isValidDayKey(state.historySelectedDay) || !String(state.historySelectedDay).startsWith(`${state.historyCalendarMonth}-`)) {
    const today = dayKeyFromDate(new Date());
    if (today && today.startsWith(`${state.historyCalendarMonth}-`)) {
      state.historySelectedDay = today;
    } else {
      state.historySelectedDay = `${state.historyCalendarMonth}-01`;
    }
  }
}

function syncHistoryCalendarModeControls() {
  const isMonthMode = state.historyCalendarMode === "month";
  if (elements.historyCalendar) {
    elements.historyCalendar.classList.toggle("is-month-mode", isMonthMode);
  }
  if (elements.historyCalendarMonth) {
    elements.historyCalendarMonth.classList.toggle("active", isMonthMode);
    elements.historyCalendarMonth.setAttribute("aria-pressed", isMonthMode ? "true" : "false");
  }
}

function setHistoryCalendarMode(mode, options = {}) {
  const nextMode = mode === "month" ? "month" : "day";
  const { reset = true, force = false } = options;
  if (!force && state.historyCalendarMode === nextMode) return;
  state.historyCalendarMode = nextMode;
  renderHistoryCalendar({ smooth: false });
  if (reset) {
    closeSwipedTransaction();
    resetTransactions();
  }
}

function renderHistoryCalendar(options = {}) {
  if (!elements.historyCalendarDays) return;
  ensureHistoryCalendarState();
  const parsedMonth = parseMonthKey(state.historyCalendarMonth);
  if (!parsedMonth) return;

  const { year, month } = parsedMonth;
  const monthStart = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  if (elements.historyCalendarMonthLabel) {
    elements.historyCalendarMonthLabel.textContent = monthStart.toLocaleDateString(currentLocale(), { month: "long", year: "numeric" });
  }

  const isMonthMode = state.historyCalendarMode === "month";
  const todayKey = dayKeyFromDate(new Date());
  const selectedDay = isValidDayKey(state.historySelectedDay) ? state.historySelectedDay : `${state.historyCalendarMonth}-01`;
  const fragment = document.createDocumentFragment();
  const weekStart = historyCalendarWeekStart();
  const monthStartIndex = monthStart.getDay();
  const leadingEmpty = (monthStartIndex - weekStart + 7) % 7;
  const totalCells = leadingEmpty + daysInMonth;
  const trailingEmpty = (7 - (totalCells % 7)) % 7;
  let cellIndex = 0;
  for (let i = 0; i < leadingEmpty; i += 1) {
    const empty = document.createElement("span");
    empty.className = "history-calendar__day is-empty";
    empty.setAttribute("aria-hidden", "true");
    empty.style.setProperty("--calendar-day-index", String(cellIndex));
    cellIndex += 1;
    fragment.appendChild(empty);
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = new Date(year, month - 1, day);
    const dayKey = dayKeyFromDate(date);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-calendar__day";
    button.setAttribute("data-history-day", dayKey);
    button.setAttribute("role", "option");
    const isSelected = !isMonthMode && dayKey === selectedDay;
    button.setAttribute("aria-selected", isSelected ? "true" : "false");
    if (isMonthMode) {
      button.tabIndex = day === 1 ? 0 : -1;
    } else {
      button.tabIndex = isSelected ? 0 : -1;
    }
    if (isSelected) {
      button.classList.add("is-selected");
    }
    if (dayKey === todayKey) {
      button.classList.add("is-today");
      button.setAttribute("aria-current", "date");
    }
    button.style.setProperty("--calendar-day-index", String(cellIndex));
    cellIndex += 1;
    button.innerHTML = `
      <span class="history-calendar__weekday">${escapeHtml(date.toLocaleDateString(currentLocale(), { weekday: "short" }))}</span>
      <span class="history-calendar__date">${escapeHtml(String(day))}</span>
    `;
    fragment.appendChild(button);
  }
  for (let i = 0; i < trailingEmpty; i += 1) {
    const empty = document.createElement("span");
    empty.className = "history-calendar__day is-empty";
    empty.setAttribute("aria-hidden", "true");
    empty.style.setProperty("--calendar-day-index", String(cellIndex));
    cellIndex += 1;
    fragment.appendChild(empty);
  }

  elements.historyCalendarDays.replaceChildren(fragment);
  syncHistoryCalendarModeControls();

  if (elements.historyCalendar && options.direction) {
    const className = options.direction > 0 ? "is-slide-left" : "is-slide-right";
    elements.historyCalendar.classList.remove("is-slide-left", "is-slide-right");
    // Restart animation for repeated swipes in the same direction.
    void elements.historyCalendar.offsetWidth;
    elements.historyCalendar.classList.add(className);
    window.setTimeout(() => elements.historyCalendar.classList.remove(className), 280);
  }
}

function applyHistoryCalendarParams(params) {
  if (!params) return;
  ensureHistoryCalendarState();
  if (state.historyCalendarMode !== "month" && isValidDayKey(state.historySelectedDay)) {
    const startDay = state.historySelectedDay;
    const endDay = addDaysToDayKey(startDay, 1);
    if (endDay) {
      params.set("period", "custom");
      params.set("start", `${startDay}T00:00:00`);
      params.set("end", `${endDay}T00:00:00`);
      params.delete("month");
      return;
    }
  }
  if (isValidMonthKey(state.historyCalendarMonth)) {
    params.set("period", "month");
    params.set("month", state.historyCalendarMonth);
    params.delete("start");
    params.delete("end");
  }
}

function shiftHistoryCalendarMonth(step) {
  const delta = Number(step) || 0;
  if (!delta) return;
  ensureHistoryCalendarState();
  state.historyCalendarAuto = false;
  const current = parseMonthKey(state.historyCalendarMonth);
  if (!current) return;
  const dayPart = Number(String(state.historySelectedDay || "").slice(8, 10)) || 1;
  const targetDate = new Date(current.year, current.month - 1 + delta, 1);
  state.historyCalendarMonth = monthKeyFromDate(targetDate);
  const maxDay = new Date(targetDate.getFullYear(), targetDate.getMonth() + 1, 0).getDate();
  state.historySelectedDay = `${state.historyCalendarMonth}-${String(Math.min(dayPart, maxDay)).padStart(2, "0")}`;
  renderHistoryCalendar({ direction: delta, smooth: false });
  closeSwipedTransaction();
  resetTransactions();
}

function selectHistoryCalendarDay(dayKey, options = {}) {
  if (!isValidDayKey(dayKey)) return;
  const targetMonth = dayKey.slice(0, 7);
  const changed = state.historySelectedDay !== dayKey || state.historyCalendarMonth !== targetMonth;
  state.historyCalendarMode = "day";
  state.historyCalendarAuto = false;
  state.historySelectedDay = dayKey;
  state.historyCalendarMonth = targetMonth;
  renderHistoryCalendar({ smooth: options.smooth !== false });
  if (changed && options.reset !== false) {
    closeSwipedTransaction();
    resetTransactions();
  }
}

function jumpHistoryCalendarToday() {
  const today = dayKeyFromDate(new Date());
  if (!today) return;
  selectHistoryCalendarDay(today);
}

function handleHistoryCalendarDayClick(event) {
  const target = event.target && event.target.closest ? event.target.closest("[data-history-day]") : null;
  if (!target) return;
  const dayKey = target.getAttribute("data-history-day");
  if (!dayKey) return;
  selectHistoryCalendarDay(dayKey);
}

function handleHistoryCalendarKeydown(event) {
  const key = event.key;
  if (key !== "ArrowLeft" && key !== "ArrowRight") return;
  const target = event.target && event.target.closest ? event.target.closest("[data-history-day]") : null;
  if (!target) return;
  const dayKey = target.getAttribute("data-history-day");
  if (!dayKey) return;
  const nextDay = addDaysToDayKey(dayKey, key === "ArrowRight" ? 1 : -1);
  if (!nextDay) return;
  event.preventDefault();
  selectHistoryCalendarDay(nextDay);
}

function handleHistoryCalendarTouchStart(event) {
  if (!event.touches || event.touches.length !== 1) return;
  const touch = event.touches[0];
  state.historyCalendarTouchStart = { x: touch.clientX, y: touch.clientY };
}

function handleHistoryCalendarTouchEnd(event) {
  const start = state.historyCalendarTouchStart;
  state.historyCalendarTouchStart = null;
  if (!start || !event.changedTouches || !event.changedTouches.length) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  if (Math.abs(dx) < 80 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
  if (dx < 0) shiftHistoryCalendarMonth(1);
  else shiftHistoryCalendarMonth(-1);
}

function getHistoryCategoryPool() {
  if (Array.isArray(state.historyCategories) && state.historyCategories.length) return state.historyCategories;
  return [];
}

function getHistoryCategoriesByDirection(direction) {
  const categories = getHistoryCategoryPool();
  if (direction !== "expense" && direction !== "income") return categories;
  return categories.filter((item) => item.direction === direction);
}

function getEmotionFilteredCategoryIds() {
  const filter = state.historyFilterEmotion || "all";
  if (filter === "all") return null;
  const labels = state.emotionLabels || {};
  const picked = getHistoryCategoryPool().filter((category) => {
    const value = labels[String(category.id)] || "";
    return filter === "none" ? !value : value === filter;
  });
  return picked.map((item) => Number(item.id)).filter((id) => Number.isFinite(id));
}

function buildHistoryRequestParams(params) {
  if (!params) return false;
  const query = (state.historySearchQuery || "").trim();
  if (query) params.set("q", query);
  if (state.historyFilterDirection && state.historyFilterDirection !== "all") params.set("direction", state.historyFilterDirection);
  if (state.historyFilterAmountMin !== "") params.set("amount_min", String(state.historyFilterAmountMin));
  if (state.historyFilterAmountMax !== "") params.set("amount_max", String(state.historyFilterAmountMax));

  let selectedCategoryId = null;
  if (state.historyFilterCategory && state.historyFilterCategory !== "all") {
    const parsed = Number(state.historyFilterCategory);
    selectedCategoryId = Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  const emotionIds = getEmotionFilteredCategoryIds();
  if (emotionIds && !emotionIds.length) return false;
  if (emotionIds && emotionIds.length) {
    const intersection = selectedCategoryId ? emotionIds.filter((id) => id === selectedCategoryId) : emotionIds;
    if (!intersection.length) return false;
    params.set("category_ids", intersection.join(","));
  } else if (selectedCategoryId) {
    params.set("category_id", String(selectedCategoryId));
  }
  return true;
}

async function loadHistoryFilterCategories() {
  if (!state.authToken && !state.initData) return;
  try {
    const [expense, income] = await Promise.all([
      authorizedFetch("/api/v1/web/categories?direction=expense", { cancelKey: "history:categories:expense", cancelPrevious: true }),
      authorizedFetch("/api/v1/web/categories?direction=income", { cancelKey: "history:categories:income", cancelPrevious: true }),
    ]);
    state.historyCategories = (expense || []).map((item) => ({ ...item, direction: "expense" }))
      .concat((income || []).map((item) => ({ ...item, direction: "income" })));
  } catch (error) {
    if (!isAbortError(error)) console.warn("Failed to load history categories", error);
    state.historyCategories = [];
  }
  populateHistoryCategoryOptions();
}

function populateHistoryCategoryOptions() {
  const categories = getHistoryCategoryPool().slice().sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), currentLocale()));
  const expenseCategories = categories.filter((item) => item.direction === "expense");
  const incomeCategories = categories.filter((item) => item.direction === "income");
  if (elements.historyFilterCategory) {
    const selected = state.historyFilterCategory || "all";
    const groups = [];
    if (expenseCategories.length) {
      groups.push(
        `<optgroup label=\"${escapeHtml(t("transactions_type_expense"))}\">` +
          expenseCategories.map((item) => `<option value=\"${item.id}\">${escapeHtml(item.name || "")}</option>`).join("") +
          `</optgroup>`
      );
    }
    if (incomeCategories.length) {
      groups.push(
        `<optgroup label=\"${escapeHtml(t("transactions_type_income"))}\">` +
          incomeCategories.map((item) => `<option value=\"${item.id}\">${escapeHtml(item.name || "")}</option>`).join("") +
          `</optgroup>`
      );
    }
    elements.historyFilterCategory.innerHTML = [`<option value=\"all\">${escapeHtml(t("history_filter_all_categories"))}</option>`]
      .concat(groups).join("");
    elements.historyFilterCategory.value = selected;
  }
  if (elements.historyEditForm) {
    const directionInput = elements.historyEditForm.querySelector("select[name='direction']");
    const categoryInput = elements.historyEditForm.querySelector("select[name='category_id']");
    populateHistoryEditCategoryOptions(directionInput ? directionInput.value : "expense", categoryInput ? categoryInput.value : "");
  }
}

function populateHistoryEditCategoryOptions(direction = "expense", selected = "") {
  const categoryInput = elements.historyEditForm ? elements.historyEditForm.querySelector("select[name='category_id']") : null;
  if (!categoryInput) return;
  const categories = getHistoryCategoriesByDirection(direction).slice().sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), currentLocale()));
  categoryInput.innerHTML = [`<option value=\"\">${escapeHtml(t("history_filter_all_categories"))}</option>`]
    .concat(categories.map((item) => `<option value=\"${item.id}\">${escapeHtml(item.name || "")}</option>`)).join("");
  categoryInput.value = selected || "";
}

function historyDirectionFilterLabel(value) {
  if (value === "expense") return t("transactions_type_expense");
  if (value === "income") return t("transactions_type_income");
  return t("history_filter_all_types");
}

function historyEmotionFilterLabel(value) {
  if (!value || value === "all") return t("history_emotion_all");
  if (value === "none") return t("history_emotion_none");
  const option = EMOTION_OPTIONS.find((item) => item.value === value);
  return option ? t(option.labelKey) : value;
}

function getHistoryActiveFilters() {
  const filters = [];
  const query = (state.historySearchQuery || "").trim();
  if (query) {
    filters.push({ key: "q", label: `${t("history_search_label")}: ${query}` });
  }
  if (state.historyFilterDirection && state.historyFilterDirection !== "all") {
    filters.push({ key: "direction", label: `${t("history_filter_type")}: ${historyDirectionFilterLabel(state.historyFilterDirection)}` });
  }
  if (state.historyFilterCategory && state.historyFilterCategory !== "all") {
    const categoryOption = elements.historyFilterCategory
      ? elements.historyFilterCategory.querySelector(`option[value="${state.historyFilterCategory}"]`)
      : null;
    const categoryLabel = categoryOption ? categoryOption.textContent.trim() : state.historyFilterCategory;
    filters.push({ key: "category", label: `${t("history_filter_category")}: ${categoryLabel}` });
  }
  if (state.historyFilterAmountMin !== "") {
    filters.push({ key: "amount_min", label: `${t("history_filter_amount_min")}: ${state.historyFilterAmountMin}` });
  }
  if (state.historyFilterAmountMax !== "") {
    filters.push({ key: "amount_max", label: `${t("history_filter_amount_max")}: ${state.historyFilterAmountMax}` });
  }
  if (state.historyFilterEmotion && state.historyFilterEmotion !== "all") {
    filters.push({ key: "emotion", label: `${t("history_filter_emotion")}: ${historyEmotionFilterLabel(state.historyFilterEmotion)}` });
  }
  return filters;
}

function renderHistoryActiveFilters(filters = null) {
  if (!elements.historyActiveFilters) return;
  const activeFilters = Array.isArray(filters) ? filters : getHistoryActiveFilters();
  if (!activeFilters.length) {
    elements.historyActiveFilters.setAttribute("hidden", "hidden");
    elements.historyActiveFilters.innerHTML = "";
    return;
  }
  elements.historyActiveFilters.removeAttribute("hidden");
  elements.historyActiveFilters.innerHTML = activeFilters
    .map((item) => {
      return `<button type=\"button\" class=\"history-active-chip\" data-history-clear=\"${item.key}\" title=\"${escapeHtml(t("history_filter_chip_clear"))}\">${escapeHtml(item.label)} <span aria-hidden=\"true\">×</span></button>`;
    })
    .join("");
}

function syncHistoryQuickFilterButtons() {
  const direction = state.historyFilterDirection || "all";
  (elements.historyDirectionButtons || []).forEach((button) => {
    const value = button.getAttribute("data-history-direction") || "all";
    button.classList.toggle("active", value === direction);
  });
}

function setHistoryFiltersPanelExpanded(expanded) {
  const isDesktop = window.matchMedia && window.matchMedia("(min-width: 721px)").matches;
  const nextState = isDesktop ? true : Boolean(expanded);
  state.historyFiltersExpanded = nextState;
  if (elements.historyFiltersPanel) {
    if (nextState) elements.historyFiltersPanel.removeAttribute("hidden");
    else elements.historyFiltersPanel.setAttribute("hidden", "hidden");
  }
  if (elements.historyFiltersToggle) {
    elements.historyFiltersToggle.setAttribute("aria-expanded", nextState ? "true" : "false");
    elements.historyFiltersToggle.classList.toggle("active", nextState);
  }
}

function toggleHistoryFiltersPanel(forceState = null) {
  const targetState = typeof forceState === "boolean" ? forceState : !Boolean(state.historyFiltersExpanded);
  setHistoryFiltersPanelExpanded(targetState);
}

function setHistoryQuickFilter(type, value) {
  if (type === "direction" && elements.historyFilterDirection) {
    elements.historyFilterDirection.value = value || "all";
  }
  applyHistoryFiltersFromControls();
}

function clearHistoryFilterTag(tagKey) {
  if (!tagKey) return;
  if (tagKey === "q") state.historySearchQuery = "";
  if (tagKey === "direction") state.historyFilterDirection = "all";
  if (tagKey === "category") state.historyFilterCategory = "all";
  if (tagKey === "amount_min") state.historyFilterAmountMin = "";
  if (tagKey === "amount_max") state.historyFilterAmountMax = "";
  if (tagKey === "emotion") state.historyFilterEmotion = "all";
  syncHistoryFilterControls();
  closeSwipedTransaction();
  resetTransactions();
}

function syncHistoryFilterControls() {
  if (elements.historySearch) elements.historySearch.value = state.historySearchQuery || "";
  if (elements.historyFilterDirection) elements.historyFilterDirection.value = state.historyFilterDirection || "all";
  if (elements.historyFilterEmotion) elements.historyFilterEmotion.value = state.historyFilterEmotion || "all";
  if (elements.historyFilterAmountMin) elements.historyFilterAmountMin.value = state.historyFilterAmountMin === "" ? "" : String(state.historyFilterAmountMin);
  if (elements.historyFilterAmountMax) elements.historyFilterAmountMax.value = state.historyFilterAmountMax === "" ? "" : String(state.historyFilterAmountMax);
  populateHistoryCategoryOptions();
  syncHistoryQuickFilterButtons();
  const activeFilters = getHistoryActiveFilters();
  if (elements.historyFiltersCount) {
    elements.historyFiltersCount.textContent = String(activeFilters.length);
    if (activeFilters.length) elements.historyFiltersCount.removeAttribute("hidden");
    else elements.historyFiltersCount.setAttribute("hidden", "hidden");
  }
  if (elements.historyFiltersToggle) {
    elements.historyFiltersToggle.classList.toggle("has-active", activeFilters.length > 0);
  }
  renderHistoryActiveFilters(activeFilters);
  setHistoryFiltersPanelExpanded(state.historyFiltersExpanded);
  renderHistoryCalendar({ smooth: false });
}

function getTransactionCardElement(transactionId) {
  if (!elements.transactionsContainer) return null;
  const id = Number(transactionId) || 0;
  if (!id) return null;
  return elements.transactionsContainer.querySelector(`[data-transaction-id="${id}"]`);
}

function setTransactionCardSwipedState(card, isOpen) {
  if (!card) return;
  const opened = Boolean(isOpen);
  card.classList.toggle("is-swiped", opened);
  const toggle = card.querySelector(".history-actions-toggle");
  if (!toggle) return;
  toggle.classList.toggle("active", opened);
  toggle.setAttribute("aria-expanded", opened ? "true" : "false");
  toggle.setAttribute("aria-label", t(opened ? "history_actions_close" : "history_actions_open"));
}

function syncSwipedTransactionDom(previousId, nextId) {
  const prevCard = previousId ? getTransactionCardElement(previousId) : null;
  const nextCard = nextId ? getTransactionCardElement(nextId) : null;
  if (!prevCard && !nextCard) return false;
  if (prevCard && prevCard !== nextCard) setTransactionCardSwipedState(prevCard, false);
  if (nextCard) setTransactionCardSwipedState(nextCard, true);
  return true;
}

function closeSwipedTransaction() {
  const previousId = Number(state.historySwipedId) || 0;
  if (!previousId) return;
  state.historySwipedId = null;
  if (!syncSwipedTransactionDom(previousId, 0)) {
    scheduleTransactionsRender({ force: true });
  }
}

function setSwipedTransaction(transactionId) {
  const id = Number(transactionId) || 0;
  if (!id) return;
  const previousId = Number(state.historySwipedId) || 0;
  if (previousId === id) return;
  state.historySwipedId = id;
  if (!syncSwipedTransactionDom(previousId, id)) {
    scheduleTransactionsRender({ force: true });
  }
}

function historyActionLabel(item) {
  const isMust = Boolean(item.must || (Array.isArray(item.tags) && item.tags.includes("must")));
  return isMust ? t("history_action_unmust") : t("history_action_must");
}

function buildTransactionCardNode(item) {
  const card = document.createElement("article");
  card.className = "transaction-card";
  card.setAttribute("data-transaction-id", String(item.id));
  const isSwiped = Number(item.id) === Number(state.historySwipedId);
  if (isSwiped) card.classList.add("is-swiped");

  const sourceLabel = item.source === "statement" ? t("history_source_statement") : t("history_source_manual");
  const amount = formatCurrency(convertAmount(item.amount, item.currency));
  const sign = item.direction === "expense" ? "-" : "+";
  const emotionValue = state.emotionLabels[String(item.category_id)] || "";
  const emotionOption = EMOTION_OPTIONS.find((option) => option.value === emotionValue);
  const emotionLabel = emotionOption ? t(emotionOption.labelKey) : "";
  const merchantBadge = item.merchant ? `<span class=\"meta-pill\">${escapeHtml(item.merchant)}</span>` : "";
  const emotionBadge = emotionLabel ? `<span class=\"meta-pill\">${escapeHtml(emotionLabel)}</span>` : "";
  const mustBadge = (item.must || (Array.isArray(item.tags) && item.tags.includes("must")))
    ? `<span class=\"meta-pill must\">${escapeHtml(t("history_must_badge"))}</span>` : "";

  card.innerHTML = `
    <div class=\"transaction-card__actions\">
      <button type=\"button\" class=\"history-action-btn\" data-action=\"toggle-must\" data-id=\"${item.id}\">${escapeHtml(historyActionLabel(item))}</button>
      <button type=\"button\" class=\"history-action-btn\" data-action=\"duplicate\" data-id=\"${item.id}\">${escapeHtml(t("history_action_duplicate"))}</button>
      <button type=\"button\" class=\"history-action-btn\" data-action=\"edit\" data-id=\"${item.id}\">${escapeHtml(t("history_action_edit"))}</button>
      <button type=\"button\" class=\"history-action-btn danger\" data-action=\"delete\" data-id=\"${item.id}\">${escapeHtml(t("goal_delete_action"))}</button>
    </div>
    <div class=\"transaction-card__surface\" data-swipe-surface=\"1\">
      <div class=\"card-header\">
        <div class=\"card-title\">
          <p class=\"muted\">${formatDateLabel(item.occurred_at)}</p>
          <h4>${escapeHtml(item.category || t("category_none"))}</h4>
        </div>
        <div class=\"card-header__amount\">
          <span class=\"${item.direction === "expense" ? "amount-negative" : "amount-positive"}\">${sign}${amount}</span>
          <button type=\"button\" class=\"icon-btn small history-actions-toggle${isSwiped ? " active" : ""}\" data-action=\"toggle-actions\" data-id=\"${item.id}\" aria-label=\"${escapeHtml(t(isSwiped ? "history_actions_close" : "history_actions_open"))}\" aria-expanded=\"${isSwiped ? "true" : "false"}\">
            <svg viewBox=\"0 0 24 24\" aria-hidden=\"true\" focusable=\"false\">
              <circle cx=\"12\" cy=\"5\" r=\"1.8\" fill=\"currentColor\" />
              <circle cx=\"12\" cy=\"12\" r=\"1.8\" fill=\"currentColor\" />
              <circle cx=\"12\" cy=\"19\" r=\"1.8\" fill=\"currentColor\" />
            </svg>
          </button>
        </div>
      </div>
      <p class=\"muted\">${escapeHtml(item.description || "-")}</p>
      <div class=\"transaction-meta\"><span class=\"meta-pill\">${escapeHtml(sourceLabel)}</span>${merchantBadge}${emotionBadge}${mustBadge}</div>
    </div>
  `;
  return card;
}

function buildHistoryDayGroupNode(dayKey, items) {
  const group = document.createElement("section");
  group.className = "history-day-group";
  let expenseTotal = 0;
  let incomeTotal = 0;
  items.forEach((item) => {
    const value = convertAmount(item.amount, item.currency);
    if (item.direction === "expense") expenseTotal += value;
    else incomeTotal += value;
  });
  const header = document.createElement("header");
  header.className = "history-day-header";
  header.innerHTML = `
    <div><h4>${escapeHtml(formatHistoryDayLabel(dayKey))}</h4><p class=\"muted\">${items.length} ${escapeHtml(t("history_day_transactions"))}</p></div>
    <div class=\"history-day-summary\"><span class=\"amount-negative\">-${formatCurrency(expenseTotal)}</span><span class=\"amount-positive\">+${formatCurrency(incomeTotal)}</span><strong>${formatCurrency(incomeTotal - expenseTotal)}</strong></div>
  `;
  group.appendChild(header);
  const list = document.createElement("div");
  list.className = "history-day-list";
  items.forEach((item) => list.appendChild(buildTransactionCardNode(item)));
  group.appendChild(list);
  return group;
}

function renderTransactionsList(options = {}) {
  const { force = false } = options;
  if (!elements.transactionsContainer) return;
  if (!force && state.activeScreen !== "history") return;
  const items = state.transactionsItems || [];
  if (!items.length) {
    if (state.transactionsLoading) return;
    elements.transactionsContainer.innerHTML = `<p class='muted'>${t("transactions_empty")}</p>`;
    state.transactionsLastRangeKey = "empty";
    return;
  }
  const rangeKey = `grouped|${items.length}|${state.historySwipedId || ""}`;
  if (!force && state.transactionsLastRangeKey === rangeKey) return;

  const grouped = new Map();
  items.forEach((item) => {
    const key = historyDayKey(item.occurred_at);
    const bucket = grouped.get(key) || [];
    bucket.push(item);
    grouped.set(key, bucket);
  });

  const fragment = document.createDocumentFragment();
  grouped.forEach((groupItems, dayKey) => fragment.appendChild(buildHistoryDayGroupNode(dayKey, groupItems)));
  elements.transactionsContainer.replaceChildren(fragment);
  state.transactionsLastRangeKey = rangeKey;
}

function scheduleTransactionsRender(options = {}) {
  const { force = false } = options;
  if (!elements.transactionsContainer) return;
  if (!force && state.activeScreen !== "history") return;
  if (force) state.transactionsLastRangeKey = "";
  if (state.transactionsRenderScheduled) return;
  state.transactionsRenderScheduled = true;
  window.requestAnimationFrame(() => {
    state.transactionsRenderScheduled = false;
    renderTransactionsList({ force });
  });
}

function prependTransactionCard(item) {
  if (!item) return;
  state.transactionsItems = [item].concat(state.transactionsItems || []);
  sortTransactionsInState();
  scheduleTransactionsRender({ force: true });
}

function setHistoryEmptyState() {
  state.transactionsItems = [];
  state.hasMoreTransactions = false;
  state.transactionsLastRangeKey = "empty";
  if (elements.transactionsContainer) elements.transactionsContainer.innerHTML = `<p class='muted'>${t("transactions_empty")}</p>`;
  if (elements.loadMoreBtn) {
    elements.loadMoreBtn.textContent = t("transactions_empty");
    elements.loadMoreBtn.disabled = true;
  }
}
async function resetTransactions() {
  if (!elements.transactionsContainer) return;
  cancelManagedRequest("transactions:list");
  state.transactionsRequestId += 1;
  state.transactionsLoading = true;
  state.transactionsPage = 0;
  state.hasMoreTransactions = true;
  state.transactionsItems = [];
  state.transactionsLastRangeKey = "";
  state.historySwipedId = null;
  elements.transactionsContainer.innerHTML = `<p class='muted'>${t("transactions_loading")}</p>`;
  if (elements.loadMoreBtn) {
    elements.loadMoreBtn.textContent = t("transactions_loading");
    elements.loadMoreBtn.disabled = true;
  }
  await loadMoreTransactions(true);
}

async function loadMoreTransactions(isReset = false) {
  if (!elements.transactionsContainer || (!state.hasMoreTransactions && !isReset) || (state.transactionsLoading && !isReset)) return;
  const requestId = state.transactionsRequestId + 1;
  state.transactionsRequestId = requestId;
  state.transactionsLoading = true;
  try {
    const params = buildPeriodParams();
    applyHistoryCalendarParams(params);
    renderHistoryCalendar({ smooth: false });
    if (!buildHistoryRequestParams(params)) {
      if (requestId === state.transactionsRequestId) setHistoryEmptyState();
      return;
    }
    params.set("limit", String(state.transactionsPageSize));
    params.set("offset", String(state.transactionsPage * state.transactionsPageSize));
    const items = await authorizedFetch(`/api/v1/web/transactions?${params.toString()}`, {
      cancelKey: "transactions:list",
      cancelPrevious: true,
    });
    if (requestId !== state.transactionsRequestId) return;

    if (isReset) state.transactionsItems = [];
    const batch = Array.isArray(items) ? items : [];
    if (!batch.length && state.transactionsPage === 0) {
      setHistoryEmptyState();
      return;
    }

    state.transactionsItems = state.transactionsItems.concat(batch);
    sortTransactionsInState();
    state.transactionsPage += 1;
    state.hasMoreTransactions = batch.length === state.transactionsPageSize;
    scheduleTransactionsRender({ force: true });

    if (elements.loadMoreBtn) {
      elements.loadMoreBtn.textContent = state.hasMoreTransactions ? t("transactions_more") : t("transactions_nomore");
      elements.loadMoreBtn.disabled = !state.hasMoreTransactions;
    }
  } catch (error) {
    if (isAbortError(error)) return;
    console.error(error);
    if (elements.loadMoreBtn) {
      elements.loadMoreBtn.textContent = t("transactions_retry");
      elements.loadMoreBtn.disabled = false;
    }
  } finally {
    if (requestId === state.transactionsRequestId) state.transactionsLoading = false;
  }
}

function getTransactionById(transactionId) {
  const id = Number(transactionId);
  if (!id) return null;
  return (state.transactionsItems || []).find((item) => Number(item.id) === id) || null;
}

function replaceTransactionInState(nextItem) {
  if (!nextItem) return;
  const id = Number(nextItem.id);
  if (!id) return;
  const index = (state.transactionsItems || []).findIndex((item) => Number(item.id) === id);
  if (index < 0) return;
  const next = (state.transactionsItems || []).slice();
  next[index] = nextItem;
  state.transactionsItems = next;
  sortTransactionsInState();
}

function removeTransactionFromState(transactionId) {
  const id = Number(transactionId);
  if (!id) return;
  state.transactionsItems = (state.transactionsItems || []).filter((item) => Number(item.id) !== id);
}

async function deleteHistoryTransaction(transactionId) {
  await authorizedFetch(`/api/v1/web/transactions/${transactionId}`, { method: "DELETE" });
  removeTransactionFromState(transactionId);
  closeSwipedTransaction();
  if (!(state.transactionsItems || []).length && state.hasMoreTransactions) {
    await loadMoreTransactions();
  }
  scheduleTransactionsRender({ force: true });
  if (typeof refreshSummaryOnly === "function") await refreshSummaryOnly();
}

async function duplicateHistoryTransaction(transactionId) {
  const current = getTransactionById(transactionId);
  if (!current) return;
  const payload = {
    amount: Number(current.amount),
    direction: current.direction,
    category_id: current.category_id || null,
    description: current.description || null,
    occurred_at: current.occurred_at || null,
  };
  const created = await authorizedFetch("/api/v1/web/transactions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (current.must) {
    await authorizedFetch(`/api/v1/web/transactions/${created.id}`, {
      method: "PATCH",
      body: JSON.stringify({ must: true }),
    });
    created.must = true;
    created.tags = (created.tags || []).concat("must");
  }
  state.transactionsItems = [created].concat(state.transactionsItems || []);
  sortTransactionsInState();
  closeSwipedTransaction();
  scheduleTransactionsRender({ force: true });
  if (typeof refreshSummaryOnly === "function") await refreshSummaryOnly();
}

async function toggleHistoryTransactionMust(transactionId) {
  const current = getTransactionById(transactionId);
  if (!current) return;
  const nextMust = !Boolean(current.must || (Array.isArray(current.tags) && current.tags.includes("must")));
  const updated = await authorizedFetch(`/api/v1/web/transactions/${transactionId}`, {
    method: "PATCH",
    body: JSON.stringify({ must: nextMust }),
  });
  replaceTransactionInState(updated);
  closeSwipedTransaction();
  scheduleTransactionsRender({ force: true });
}

function openHistoryEditModal(transactionId) {
  if (!elements.historyEditModal || !elements.historyEditForm) return;
  const current = getTransactionById(transactionId);
  if (!current) return;
  state.historyEditingId = Number(current.id);

  const form = elements.historyEditForm;
  const amountInput = form.querySelector("input[name='amount']");
  const directionInput = form.querySelector("select[name='direction']");
  const categoryInput = form.querySelector("select[name='category_id']");
  const dateInput = form.querySelector("input[name='occurred_at']");
  const descriptionInput = form.querySelector("input[name='description']");
  const idInput = form.querySelector("input[name='transaction_id']");

  if (idInput) idInput.value = String(current.id);
  if (amountInput) amountInput.value = String(Number(current.amount) || "");
  if (directionInput) directionInput.value = current.direction || "expense";
  populateHistoryEditCategoryOptions(current.direction || "expense", current.category_id ? String(current.category_id) : "");
  if (categoryInput) categoryInput.value = current.category_id ? String(current.category_id) : "";
  if (dateInput) dateInput.value = formatDateInputValue(current.occurred_at);
  if (descriptionInput) descriptionInput.value = current.description || "";

  elements.historyEditModal.removeAttribute("hidden");
  document.body.style.overflow = "hidden";
}

function closeHistoryEditModal() {
  if (!elements.historyEditModal) return;
  elements.historyEditModal.setAttribute("hidden", "hidden");
  state.historyEditingId = null;
  document.body.style.overflow = "";
}

async function submitHistoryEdit() {
  if (!elements.historyEditForm || !state.historyEditingId) return;
  const formData = new FormData(elements.historyEditForm);
  const amount = Number(formData.get("amount"));
  if (!Number.isFinite(amount) || amount <= 0) return;
  const payload = {
    amount,
    direction: formData.get("direction") || "expense",
    category_id: Number(formData.get("category_id")) || null,
    description: (formData.get("description") || "").toString().trim() || null,
    occurred_at: formData.get("occurred_at") || null,
  };
  const updated = await authorizedFetch(`/api/v1/web/transactions/${state.historyEditingId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  replaceTransactionInState(updated);
  closeHistoryEditModal();
  scheduleTransactionsRender({ force: true });
  if (typeof refreshSummaryOnly === "function") await refreshSummaryOnly();
}

async function handleHistoryCardAction(action, transactionId, trigger) {
  const id = Number(transactionId);
  if (!id || !action) return;

  if (action === "toggle-actions") {
    if (Number(state.historySwipedId) === id) closeSwipedTransaction();
    else setSwipedTransaction(id);
    return;
  }

  if (action === "edit") {
    openHistoryEditModal(id);
    return;
  }

  const networkAction = ["delete", "duplicate", "toggle-must"].includes(action);
  if (networkAction && trigger) trigger.disabled = true;
  try {
    if (action === "delete") return await deleteHistoryTransaction(id);
    if (action === "duplicate") return await duplicateHistoryTransaction(id);
    if (action === "toggle-must") return await toggleHistoryTransactionMust(id);
  } catch (error) {
    console.error(error);
  } finally {
    if (networkAction && trigger) trigger.disabled = false;
  }
}

function applyHistoryFiltersFromControls(options = {}) {
  const { debounce = false } = options;
  const previous = JSON.stringify({
    q: state.historySearchQuery,
    dir: state.historyFilterDirection,
    cat: state.historyFilterCategory,
    emotion: state.historyFilterEmotion,
    min: state.historyFilterAmountMin,
    max: state.historyFilterAmountMax,
  });

  state.historySearchQuery = elements.historySearch ? elements.historySearch.value.trim() : "";
  state.historyFilterDirection = elements.historyFilterDirection ? elements.historyFilterDirection.value || "all" : "all";
  state.historyFilterCategory = elements.historyFilterCategory ? elements.historyFilterCategory.value || "all" : "all";
  state.historyFilterEmotion = elements.historyFilterEmotion ? elements.historyFilterEmotion.value || "all" : "all";

  const amountMin = elements.historyFilterAmountMin ? Number(elements.historyFilterAmountMin.value) : NaN;
  const amountMax = elements.historyFilterAmountMax ? Number(elements.historyFilterAmountMax.value) : NaN;
  state.historyFilterAmountMin = Number.isFinite(amountMin) && amountMin >= 0 ? amountMin : "";
  state.historyFilterAmountMax = Number.isFinite(amountMax) && amountMax >= 0 ? amountMax : "";

  const next = JSON.stringify({
    q: state.historySearchQuery,
    dir: state.historyFilterDirection,
    cat: state.historyFilterCategory,
    emotion: state.historyFilterEmotion,
    min: state.historyFilterAmountMin,
    max: state.historyFilterAmountMax,
  });

  if (previous === next) return;
  closeSwipedTransaction();
  if (state.historySearchTimer) {
    window.clearTimeout(state.historySearchTimer);
    state.historySearchTimer = 0;
  }
  syncHistoryFilterControls();

  if (debounce) {
    state.historySearchTimer = window.setTimeout(() => {
      state.historySearchTimer = 0;
      resetTransactions();
    }, 260);
    return;
  }
  resetTransactions();
}

function resetHistoryFilters() {
  state.historySearchQuery = "";
  state.historyFilterDirection = "all";
  state.historyFilterCategory = "all";
  state.historyFilterEmotion = "all";
  state.historyFilterAmountMin = "";
  state.historyFilterAmountMax = "";
  if (!window.matchMedia || !window.matchMedia("(min-width: 721px)").matches) {
    state.historyFiltersExpanded = false;
  }
  syncHistoryFilterControls();
  closeSwipedTransaction();
  resetTransactions();
}

function handleHistoryTouchStart(event) {
  if (!event.touches || event.touches.length !== 1) return;
  const surface = event.target.closest("[data-swipe-surface]");
  if (!surface) return;
  const card = surface.closest("[data-transaction-id]");
  if (!card) return;
  const touch = event.touches[0];
  state.historyTouchStart = {
    id: Number(card.getAttribute("data-transaction-id")) || 0,
    x: touch.clientX,
    y: touch.clientY,
  };
}

function handleHistoryTouchEnd(event) {
  const started = state.historyTouchStart;
  state.historyTouchStart = null;
  if (!started || !started.id || !event.changedTouches || !event.changedTouches.length) return;
  const touch = event.changedTouches[0];
  const dx = touch.clientX - started.x;
  const dy = touch.clientY - started.y;
  if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
  if (dx < 0) setSwipedTransaction(started.id);
  else closeSwipedTransaction();
}
function validateReceiptFile(file) {
  if (!file || !file.type.startsWith("image/")) return t("receipt_error");
  if (file.size > 5 * 1024 * 1024) return t("receipt_error");
  return "";
}

function validateStatementFile(file) {
  if (!file) return t("statement_error");
  const name = file.name || "";
  const allowed = [".csv", ".xls", ".xlsx"];
  const isAllowed = allowed.some((ext) => name.toLowerCase().endsWith(ext));
  if (!isAllowed) return t("statement_error");
  if (file.size > 10 * 1024 * 1024) return t("statement_error");
  return "";
}

function setStatementResult(content, variant = "info") {
  if (!elements.statementResult) return;
  elements.statementResult.innerHTML = `<p class="${variant === "error" ? "error" : "muted"}">${content}</p>`;
}

function updateReceiptPreview(file) {
  if (!elements.receiptPreview) return;
  if (state.receiptPreviewUrl) URL.revokeObjectURL(state.receiptPreviewUrl);
  if (!file) {
    elements.receiptPreview.hidden = true;
    elements.receiptPreview.innerHTML = "";
    state.receiptPreviewUrl = "";
    return;
  }
  const url = URL.createObjectURL(file);
  state.receiptPreviewUrl = url;
  elements.receiptPreview.innerHTML = `<img src="${url}" alt="receipt preview" />`;
  elements.receiptPreview.hidden = false;
}

function setReceiptResult(content, variant = "info") {
  if (!elements.receiptResult) return;
  if (variant === "html") {
    elements.receiptResult.innerHTML = content;
    return;
  }
  elements.receiptResult.innerHTML = `<p class="${variant === "error" ? "error" : "muted"}">${content}</p>`;
}

function toggleAllTimeVisibility() {
  const cards = elements.allTimeCards || [];
  const hasData = Boolean(state.overview?.all_time_summary);
  cards.forEach((card) => {
    card.hidden = !hasData;
    if (hasData) {
      card.classList.toggle("collapsed", !state.showAllTimeTotals);
    }
  });
}

function updateAllTimeToggleLabel() {
  if (!elements.allTimeToggle) return;
  const iconOn = elements.allTimeToggle.querySelector(".icon-eye-on");
  const iconOff = elements.allTimeToggle.querySelector(".icon-eye-off");
  if (iconOn) iconOn.hidden = !state.showAllTimeTotals;
  if (iconOff) iconOff.hidden = state.showAllTimeTotals;
  elements.allTimeToggle.setAttribute("aria-pressed", state.showAllTimeTotals ? "true" : "false");
}

async function exportTransactionsCSV() {
  if (!elements.downloadCsvBtn) return;
  elements.downloadCsvBtn.textContent = t("download_preparing");
  elements.downloadCsvBtn.disabled = true;
  try {
    const rows = [];
    let offset = 0;
    while (true) {
      const params = new URLSearchParams({ limit: "200", offset: String(offset) });
      if (state.selectedMonth) params.set("month", state.selectedMonth);
      const batch = await authorizedFetch(`/api/v1/web/transactions?${params.toString()}`);
      if (!batch || !batch.length) break;
      rows.push(...batch);
      offset += batch.length;
      if (batch.length < 200) break;
    }
    const header = [
      t("csv_header_date"),
      t("csv_header_amount"),
      t("csv_header_currency"),
      t("csv_header_type"),
      t("csv_header_category"),
      t("csv_header_description"),
    ];
    const csv = [header.join(",")].concat(
      rows.map((row) => {
        const amount = convertAmount(row.amount, row.currency).toFixed(2);
        return [
          row.occurred_at ? new Date(row.occurred_at).toISOString() : "",
          amount,
          state.currency,
          row.direction,
          `"${(row.category || "").replace(/"/g, '""')}"`,
          `"${(row.description || "").replace(/"/g, '""')}"`,
        ].join(",");
      })
    );
    const blob = new Blob([csv.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "transactions.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    elements.downloadCsvBtn.textContent = t("download_ready");
  } catch (error) {
    console.error(error);
    elements.downloadCsvBtn.textContent = t("download_error");
  } finally {
    setTimeout(() => {
      if (elements.downloadCsvBtn) {
        elements.downloadCsvBtn.textContent = t("settings_download");
        elements.downloadCsvBtn.disabled = false;
      }
    }, 2000);
  }
}

function openSettings() {
  if (elements.settingsPanel) {
    elements.settingsPanel.classList.add("open");
    elements.settingsPanel.removeAttribute("hidden");
  }
  if (elements.settingsOverlay) {
    elements.settingsOverlay.classList.add("visible");
    elements.settingsOverlay.removeAttribute("hidden");
  }
  document.body.style.overflow = "hidden";
}

function closeSettings() {
  if (elements.settingsPanel) {
    elements.settingsPanel.classList.remove("open");
    elements.settingsPanel.setAttribute("hidden", "hidden");
  }
  if (elements.settingsOverlay) {
    elements.settingsOverlay.classList.remove("visible");
    elements.settingsOverlay.setAttribute("hidden", "hidden");
  }
  document.body.style.overflow = "";
}
