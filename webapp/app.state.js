// App runtime state: storage helpers, auth wiring, feature flags, and cached DOM references.
function readStoredObject(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed ?? fallback;
  } catch (error) {
    return fallback;
  }
}

function storeObject(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    console.error(error);
  }
}

function serializeTelegramLoginPayload(payload) {
  if (!payload || typeof payload !== "object") return "";
  const params = new URLSearchParams();
  Object.entries(payload).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    params.set(key, value);
  });
  return params.toString();
}

const state = {
  initData: "",
  authToken: localStorage.getItem(STORAGE_KEYS.authToken) || "",
  authTokenExpiresAt: localStorage.getItem(STORAGE_KEYS.authTokenExpiry) || "",
  user: null,
  overview: null,
  categories: [],
  expenseCategories: [],
  budgetCategories: [],
  budgets: [],
  savingsGoals: readStoredObject(STORAGE_KEYS.savingsGoals, []),
  emotionLabels: readStoredObject(STORAGE_KEYS.emotionLabels, {}),
  baseCurrency: "UAH",
  availableMonths: [],
  selectedMonth: "",
  periodPreset: "month",
  customPeriodStart: "",
  customPeriodEnd: "",
  transactionsPage: 0,
  transactionsPageSize: 10,
  hasMoreTransactions: true,
  transactionsItems: [],
  historySearchQuery: "",
  historyFilterDirection: "all",
  historyFilterCategory: "all",
  historyFilterEmotion: "all",
  historyFilterAmountMin: "",
  historyFilterAmountMax: "",
  historyCalendarMonth: "",
  historySelectedDay: "",
  historyCalendarMode: "month",
  historyCalendarAuto: true,
  historyCalendarTouchStart: null,
  historyCategories: [],
  historyFiltersExpanded: window.innerWidth > 720,
  historySwipedId: null,
  historyTouchStart: null,
  historyEditingId: null,
  historySearchTimer: 0,
  transactionsRenderScheduled: false,
  transactionsVirtualThreshold: 120,
  transactionsOverscan: 6,
  transactionsRowHeight: 148,
  transactionsLastRangeKey: "",
  chartType: "category_bar",
  chartInstance: null,
  assistantMessages: [],
  assistantPending: false,
  assistantWelcomeShown: false,
  assistantTone: localStorage.getItem(STORAGE_KEYS.assistantTone) || "short",
  activeScenario: "normal",
  receiptPreviewUrl: "",
  activeScreen: "overview",
  theme: localStorage.getItem(STORAGE_KEYS.theme) || "dark",
  language: localStorage.getItem(STORAGE_KEYS.language) || "uk",
  currency: localStorage.getItem(STORAGE_KEYS.currency) || "UAH",
  exchangeRates: { UAH: 1, USD: 38 },
  telegramBotUsername: "",
  showAllTimeTotals: localStorage.getItem("manager_bot_all_time_toggle") !== "0",
  initDataSource: "none",
  hasFreshInitData: false,
  lastHeatmap: { cells: [], currency: "UAH" },
  lastRefreshedAt: Number(localStorage.getItem(STORAGE_KEYS.lastRefreshedAt) || 0),
  refreshInFlight: false,
  pendingRefreshType: "",
  chatLayoutSyncScheduled: false,
  chatNavHeight: 0,
  chatComposerHeight: 0,
  chartRequestId: 0,
  insightsRequestId: 0,
  transactionsRequestId: 0,
  transactionsLoading: false,
};

const formatterCache = {
  currency: new Map(),
  relativeTime: new Map(),
  date: new Map(),
  time: new Map(),
};

const auth = authModule.createAuth({
  storageKeys: STORAGE_KEYS,
  state,
  tg,
  onUnauthorized: () => handleUnauthorized(),
});

const FEATURE_FLAGS = {
  insights: true,
  heatmap: true,
};

const EMOTION_OPTIONS = [
  { value: "", labelKey: "emotion_option_none" },
  { value: "joy", labelKey: "emotion_option_joy" },
  { value: "useful", labelKey: "emotion_option_useful" },
  { value: "neutral", labelKey: "emotion_option_neutral" },
  { value: "stress", labelKey: "emotion_option_stress" },
];

function loadFeatureFlags() {
  try {
    const raw = localStorage.getItem("manager_bot_feature_flags");
    if (!raw) return FEATURE_FLAGS;
    const parsed = JSON.parse(raw);
    return { ...FEATURE_FLAGS, ...(parsed || {}) };
  } catch (error) {
    console.warn("Feature flags parse failed", error);
    return FEATURE_FLAGS;
  }
}

function applyFeatureFlags() {
  const flags = loadFeatureFlags();
  document.querySelectorAll("[data-feature]").forEach((node) => {
    const key = node.getAttribute("data-feature");
    if (!key) return;
    node.hidden = flags[key] === false;
  });
}

function migrateLegacySavingsGoal() {
  const hasNew = localStorage.getItem(STORAGE_KEYS.savingsGoals);
  if (hasNew) return;
  const legacy = readStoredObject(LEGACY_SAVINGS_KEY, null);
  if (!legacy) return;
  const migrated = normalizeSavingsGoals(legacy);
  if (migrated.length) {
    saveSavingsGoals(migrated);
  }
}

const resolvedInitData = auth.resolveInitData();
state.initData = resolvedInitData.initData;
state.initDataSource = resolvedInitData.source;
state.hasFreshInitData = resolvedInitData.fresh;

const persistAuthToken = (token, expiresAt) => auth.persistAuthToken(token, expiresAt);
const clearAuthToken = () => auth.clearAuthToken();
const authorizedFetch = (...args) => auth.authorizedFetch(...args);
const cancelManagedRequest = (key) => (auth.cancelManagedRequest ? auth.cancelManagedRequest(key) : false);

const elements = {
  i18nTextNodes: Array.from(document.querySelectorAll("[data-i18n]")),
  i18nPlaceholderNodes: Array.from(document.querySelectorAll("[data-i18n-placeholder]")),
  i18nAriaNodes: Array.from(document.querySelectorAll("[data-i18n-aria-label]")),
  screenNodes: Array.from(document.querySelectorAll("[data-screen]")),
  screenNavButtons: Array.from(document.querySelectorAll("[data-screen-target]")),
  greeting: document.getElementById("user-greeting"),
  userName: document.getElementById("user-name"),
  userAvatar: document.getElementById("user-avatar"),
  settingsBtn: document.getElementById("settings-btn"),
  settingsPanel: document.getElementById("settings-panel"),
  settingsOverlay: document.getElementById("settings-overlay"),
  settingsClose: document.getElementById("settings-close"),
  languageSelect: document.getElementById("language-select"),
  currencySelect: document.getElementById("currency-select"),
  themeSelect: document.getElementById("theme-select"),
  downloadCsvBtn: document.getElementById("download-csv-btn"),
  income: document.getElementById("summary-income"),
  expense: document.getElementById("summary-expense"),
  net: document.getElementById("summary-net"),
  allTimeExpense: document.getElementById("summary-alltime-expense"),
  allTimeIncome: document.getElementById("summary-alltime-income"),
  allTimeToggle: document.getElementById("alltime-toggle"),
  allTimeCards: Array.from(document.querySelectorAll(".alltime-card")),
  budgets: document.getElementById("budgets"),
  categoriesSelect: document.getElementById("category-select"),
  transactionForm: document.getElementById("transaction-form"),
  transactionFeedback: document.getElementById("transaction-feedback"),
  assistantForm: document.getElementById("assistant-form"),
  assistantFeedback: document.getElementById("assistant-feedback"),
  assistantHistory: document.getElementById("assistant-history"),
  assistantChips: document.getElementById("assistant-chips"),
  assistantTone: document.getElementById("assistant-tone"),
  receiptInput: document.getElementById("receipt-input"),
  receiptResult: document.getElementById("receipt-result"),
  receiptPreview: document.getElementById("receipt-preview"),
  statementInput: document.getElementById("statement-input"),
  statementResult: document.getElementById("statement-result"),
  lastUpdated: document.getElementById("last-updated"),
  monthSelect: document.getElementById("month-select"),
  periodControls: document.getElementById("period-controls"),
  toolbarMoreBtn: document.getElementById("toolbar-more-btn"),
  toolbarMorePanel: document.getElementById("toolbar-more-panel"),
  periodCustom: document.getElementById("period-custom"),
  periodStart: document.getElementById("period-start"),
  periodEnd: document.getElementById("period-end"),
  periodApply: document.getElementById("period-apply"),
  transactionsContainer: document.getElementById("transactions-container"),
  loadMoreBtn: document.getElementById("load-more-btn"),
  historySearch: document.getElementById("history-search"),
  historyFilterDirection: document.getElementById("history-filter-direction"),
  historyFilterCategory: document.getElementById("history-filter-category"),
  historyFilterAmountMin: document.getElementById("history-filter-amount-min"),
  historyFilterAmountMax: document.getElementById("history-filter-amount-max"),
  historyFilterEmotion: document.getElementById("history-filter-emotion"),
  historyCalendar: document.getElementById("history-calendar"),
  historyCalendarDays: document.getElementById("history-calendar-days"),
  historyCalendarMonthLabel: document.getElementById("history-calendar-month-label"),
  historyCalendarPrev: document.getElementById("history-calendar-prev"),
  historyCalendarNext: document.getElementById("history-calendar-next"),
  historyCalendarMonth: document.getElementById("history-calendar-month"),
  historyCalendarToday: document.getElementById("history-calendar-today"),
  historyFiltersToggle: document.getElementById("history-filters-toggle"),
  historyFiltersPanel: document.getElementById("history-filters-panel"),
  historyFiltersCount: document.getElementById("history-filters-count"),
  historyActiveFilters: document.getElementById("history-active-filters"),
  historyDirectionButtons: Array.from(document.querySelectorAll("[data-history-direction]")),
  historyFiltersReset: document.getElementById("history-filters-reset"),
  historyEditModal: document.getElementById("history-edit-modal"),
  historyEditForm: document.getElementById("history-edit-form"),
  historyEditCategory: document.getElementById("history-edit-category"),
  historyEditCancel: document.getElementById("history-edit-cancel"),
  historyEditCloseTriggers: Array.from(document.querySelectorAll("[data-history-edit-close]")),
  goalForm: document.getElementById("goal-form"),
  goalFeedback: document.getElementById("goal-feedback"),
  goalCategorySelect: document.getElementById("goal-category"),
  scenarioActions: document.getElementById("scenario-actions"),
  scenarioFeedback: document.getElementById("scenario-feedback"),
  scenarioRecommendations: document.getElementById("scenario-recommendations"),
  goalThreshold: document.getElementById("goal-threshold"),
  goalThresholdValue: document.getElementById("goal-threshold-value"),
  savingsForm: document.getElementById("savings-form"),
  savingsFeedback: document.getElementById("savings-feedback"),
  savingsGoals: document.getElementById("savings-goals"),
  emotionList: document.getElementById("emotion-list"),
  emotionFeedback: document.getElementById("emotion-feedback"),
  chartCanvas: document.getElementById("analytics-chart"),
  chartEmpty: document.getElementById("chart-empty"),
  chartMetrics: document.getElementById("chart-metrics"),
  chartThreshold: document.getElementById("chart-threshold"),
  chartInsights: document.getElementById("chart-insights"),
  chartControls: document.getElementById("chart-type-nav"),
  heatmap: document.getElementById("expense-heatmap"),
  heatmapModal: document.getElementById("heatmap-modal"),
  heatmapModalBody: document.getElementById("heatmap-modal-body"),
  transactionSubmitState: document.getElementById("transaction-submit-state"),
  categoryLoadingIndicator: document.getElementById("category-loading-indicator"),
  bottomNav: document.getElementById("bottom-nav"),
  manualAuth: document.getElementById("manual-auth"),
  manualInitInput: document.getElementById("manual-init-input"),
  manualInitButton: document.getElementById("manual-init-submit"),
  manualAuthError: document.getElementById("manual-auth-error"),
  telegramLoginContainer: document.getElementById("telegram-login-container"),
};
