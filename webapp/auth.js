(function (window) {
  function looksLikeInitData(value) {
    if (!value) return false;
    const normalized = String(value).trim();
    if (!normalized) return false;
    return /(?:^|&)hash=/.test(normalized) && /(?:^|&)auth_date=/.test(normalized);
  }

  function buildInitDataFromHashParams(hashParams) {
    if (!hashParams) return "";
    const tgWebAppDataRaw = hashParams.get("tgWebAppData");
    if (!tgWebAppDataRaw) return "";

    const direct = normalizeInitData(tgWebAppDataRaw);
    if (looksLikeInitData(direct)) return direct;

    const stitched = new URLSearchParams(direct || "");
    const stitchedKeys = [
      "query_id",
      "user",
      "receiver",
      "chat_instance",
      "chat_type",
      "chat",
      "start_param",
      "can_send_after",
      "auth_date",
      "signature",
      "hash",
    ];
    stitchedKeys.forEach((key) => {
      if (stitched.has(key)) return;
      const value = hashParams.get(key);
      if (value !== null && value !== "") stitched.set(key, value);
    });

    const rebuilt = stitched.toString();
    return looksLikeInitData(rebuilt) ? rebuilt : "";
  }

  function normalizeInitData(raw) {
    if (!raw) return "";
    const trimmed = raw.trim();
    if (!trimmed) return "";

    const isUrl = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed);
    const snippets = [];
    if (!isUrl) {
      snippets.push(trimmed);
    }
    const hashIndex = trimmed.indexOf("#");
    if (hashIndex !== -1) {
      snippets.push(trimmed.slice(hashIndex + 1));
    }
    const queryIndex = trimmed.indexOf("?");
    if (queryIndex !== -1) {
      const end = hashIndex !== -1 && hashIndex > queryIndex ? hashIndex : undefined;
      snippets.push(trimmed.slice(queryIndex + 1, end));
    }

    for (const snippet of snippets) {
      if (!snippet || !/(?:^|[?#&])(tgWebAppData|init_data|initData)=/.test(snippet)) {
        continue;
      }
      try {
        const params = new URLSearchParams(snippet.replace(/^[?#]/, ""));
        const direct = params.get("init_data") || params.get("initData") || params.get("tgWebAppData") || "";
        if (direct) {
          return direct.trim();
        }
      } catch {
        // ignore malformed snippets
      }
    }

    if (isUrl) {
      return "";
    }

    return trimmed;
  }

  function normalizeLoginData(raw) {
    if (!raw) return "";
    const trimmed = raw.trim();
    if (!trimmed) return "";
    const snippets = [trimmed];
    const hashIndex = trimmed.indexOf("#");
    if (hashIndex !== -1) {
      snippets.push(trimmed.slice(hashIndex + 1));
    }
    const queryIndex = trimmed.indexOf("?");
    if (queryIndex !== -1) {
      const querySlice = trimmed.slice(queryIndex + 1, hashIndex !== -1 && hashIndex > queryIndex ? hashIndex : undefined);
      snippets.push(querySlice);
    }

    for (const rawSnippet of snippets) {
      if (!rawSnippet) continue;
      let snippet = rawSnippet.trim();
      if (snippet.startsWith("tgAuthResult=")) {
        snippet = snippet.slice("tgAuthResult=".length);
      }
      snippet = snippet.replace(/^[?#]/, "");
      if (!snippet || !snippet.includes("hash=") || !snippet.includes("auth_date=")) continue;
      try {
        const params = new URLSearchParams(snippet);
        if (params.has("hash") && params.has("auth_date")) {
          return params.toString();
        }
      } catch {
        // ignore malformed payloads
      }
    }
    return "";
  }

  function createAuth({ storageKeys, state, tg, onUnauthorized }) {
    const managedControllers = new Map();

    function isAbortError(error) {
      return Boolean(error && (error.name === "AbortError" || String(error.message || "").toLowerCase().includes("abort")));
    }

    function mergeAbortSignals(signals) {
      const valid = (signals || []).filter(Boolean);
      if (!valid.length) return undefined;
      if (valid.length === 1) return valid[0];
      if (typeof AbortSignal !== "undefined" && typeof AbortSignal.any === "function") {
        return AbortSignal.any(valid);
      }
      const controller = new AbortController();
      const abort = () => controller.abort();
      valid.forEach((signal) => {
        if (signal.aborted) {
          abort();
          return;
        }
        signal.addEventListener("abort", abort, { once: true });
      });
      return controller.signal;
    }

    function cancelManagedRequest(key) {
      if (!key) return false;
      const controller = managedControllers.get(key);
      if (!controller) return false;
      controller.abort();
      managedControllers.delete(key);
      return true;
    }

    function resolveInitData() {
      const storedRaw = localStorage.getItem(storageKeys.initData) || "";
      const stored = normalizeInitData(storedRaw);
      let source = "none";
      let initData = "";

      const searchParams = new URLSearchParams(window.location.search);
      const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));

      const queryCandidates = [
        normalizeInitData(searchParams.get("init_data") || searchParams.get("initData")),
        normalizeInitData(searchParams.get("tgWebAppData")),
        buildInitDataFromHashParams(searchParams),
        normalizeInitData(hashParams.get("init_data") || hashParams.get("initData")),
        normalizeInitData(hashParams.get("tgWebAppData")),
        buildInitDataFromHashParams(hashParams),
      ];
      const queryInit = queryCandidates.find((candidate) => looksLikeInitData(candidate)) || "";
      if (queryInit) {
        initData = queryInit;
        source = "query";
      }

      if (!initData && tg && tg.initData) {
        const normalized = normalizeInitData(tg.initData);
        if (looksLikeInitData(normalized)) {
          initData = normalized;
          source = "telegram";
        }
      }

      if (!initData) {
        const unsafe = tg && tg.initDataUnsafe;
        if (unsafe) {
          const params = new URLSearchParams();
          Object.entries(unsafe).forEach(([key, value]) => {
            if (value === undefined || value === null) return;
            if (typeof value === "object") {
              params.set(key, JSON.stringify(value));
            } else {
              params.set(key, String(value));
            }
          });
          const serialized = params.toString();
          const normalized = normalizeInitData(serialized);
          if (looksLikeInitData(normalized)) {
            initData = normalized;
            source = "telegram_unsafe";
          }
        }
      }

      if (!initData && looksLikeInitData(stored)) {
        initData = stored;
        source = "storage";
      }

      if (initData) {
        localStorage.setItem(storageKeys.initData, initData);
      } else {
        localStorage.removeItem(storageKeys.initData);
      }

      const changed = Boolean(initData && stored && initData !== stored);
      const fresh = source !== "storage" && Boolean(initData);

      return { initData, source, changed, fresh, storedInitData: stored };
    }

    function clearInitData() {
      state.initData = "";
      localStorage.removeItem(storageKeys.initData);
    }

    function persistAuthToken(token, expiresAt) {
      if (!token) {
        clearAuthToken();
        return;
      }
      state.authToken = token;
      localStorage.setItem(storageKeys.authToken, token);
      if (expiresAt) {
        state.authTokenExpiresAt = expiresAt;
        localStorage.setItem(storageKeys.authTokenExpiry, expiresAt);
      } else {
        state.authTokenExpiresAt = "";
        localStorage.removeItem(storageKeys.authTokenExpiry);
      }
    }

    function clearAuthToken() {
      state.authToken = "";
      state.authTokenExpiresAt = "";
      localStorage.removeItem(storageKeys.authToken);
      localStorage.removeItem(storageKeys.authTokenExpiry);
    }

    async function authorizedFetch(path, options = {}) {
      if (!state.authToken && !state.initData) {
        throw new Error("Authorization is missing.");
      }
      const {
        cancelKey = "",
        cancelPrevious = false,
        signal: externalSignal,
        ...fetchOptions
      } = options || {};
      const headers = new Headers(fetchOptions.headers || {});
      if (state.initData) {
        headers.set("X-Telegram-Init", state.initData);
      }
      if (state.authToken) {
        headers.set("Authorization", `Bearer ${state.authToken}`);
      }
      if (fetchOptions.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

      let managedController = null;
      let signal = externalSignal;
      if (cancelKey) {
        if (cancelPrevious) {
          cancelManagedRequest(cancelKey);
        }
        managedController = new AbortController();
        managedControllers.set(cancelKey, managedController);
        signal = mergeAbortSignals([externalSignal, managedController.signal]);
      }

      try {
        const response = await fetch(path, { ...fetchOptions, headers, signal });
        if (!response.ok) {
          if (response.status === 401) {
            clearAuthToken();
            if (onUnauthorized) onUnauthorized();
          }
          const detail = await response.text();
          throw new Error(detail || "Request failed");
        }
        if (response.status === 204) return null;
        const text = await response.text();
        return text ? JSON.parse(text) : null;
      } catch (error) {
        if (isAbortError(error)) {
          const aborted = new Error("Request aborted");
          aborted.name = "AbortError";
          throw aborted;
        }
        throw error;
      } finally {
        if (cancelKey && managedController && managedControllers.get(cancelKey) === managedController) {
          managedControllers.delete(cancelKey);
        }
      }
    }

    async function authenticateWithTelegram(payload) {
      if (!payload || (!payload.init_data && !payload.login_data)) {
        return null;
      }
      const response = await fetch("/api/v1/web/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "Unable to create session");
      }
      const session = await response.json();
      persistAuthToken(session.token, session.token_expires_at);
      if (payload.init_data) {
        state.initData = payload.init_data;
        localStorage.setItem(storageKeys.initData, payload.init_data);
      }
      return session;
    }

    async function initSession() {
      if (state.authToken) {
        try {
          const session = await authorizedFetch("/api/v1/web/session");
          return session;
        } catch {
          clearAuthToken();
        }
      }
      if (!state.initData) {
        return null;
      }
      return authenticateWithTelegram({ init_data: state.initData });
    }

    return {
      normalizeInitData,
      normalizeLoginData,
      resolveInitData,
      clearInitData,
      persistAuthToken,
      clearAuthToken,
      authorizedFetch,
      cancelManagedRequest,
      authenticateWithTelegram,
      initSession,
    };
  }

  window.AppAuth = { createAuth, normalizeInitData, normalizeLoginData };
})(window);
