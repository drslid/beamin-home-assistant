// The /beam page: show a code, wait for the approval, then hand the session to
// the Home Assistant frontend. Plain ES2017 so old car and TV browsers run it.
(function () {
  "use strict";

  var i18n = self.BeamInI18n.createTranslator(navigator.languages || [navigator.language]);
  var t = i18n.t;
  // Same key and shape as the frontend's token storage (src/common/auth/token_storage.ts).
  var STORAGE_KEY = "hassTokens";
  var ORIGIN = location.protocol + "//" + location.host;

  // The secret lives only here: never in the DOM, the URL or storage.
  var state = {
    requestId: null,
    secret: null,
    deadline: 0,
    ttl: 0,
    pollDelay: 2000,
    pollTimer: null,
    tickTimer: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function localize() {
    document.documentElement.lang = i18n.language;
    document.title = t("title") + " · Home Assistant";
    var texts = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < texts.length; i++) {
      texts[i].textContent = t(texts[i].getAttribute("data-i18n"));
    }
    var images = document.querySelectorAll("[data-i18n-alt]");
    for (var j = 0; j < images.length; j++) {
      images[j].alt = t(images[j].getAttribute("data-i18n-alt"));
    }
  }

  function show(view) {
    ["loading", "waiting", "result"].forEach(function (name) {
      $("view-" + name).hidden = name !== view;
    });
  }

  function forget() {
    state.requestId = null;
    state.secret = null;
  }

  function stop() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    if (state.tickTimer) clearInterval(state.tickTimer);
    state.pollTimer = null;
    state.tickTimer = null;
    forget();
  }

  function showResult(success, message, buttonKey) {
    stop();
    var icon = $("result-icon");
    icon.textContent = success ? "✓" : "!";
    icon.className = "result-icon " + (success ? "ok" : "error");
    $("result").textContent = message;
    var button = $("new-code");
    button.hidden = !buttonKey;
    if (buttonKey) button.textContent = t(buttonKey);
    show("result");
    if (buttonKey) button.focus();
  }

  async function post(path, body) {
    var response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
    var data = {};
    try {
      data = await response.json();
    } catch (err) {
      data = {};
    }
    return { status: response.status, data: data || {} };
  }

  function save(tokens) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
      return true;
    } catch (err) {
      return false;
    }
  }

  // A device that is still signed in goes straight to the dashboard. Refreshing
  // proves the session is valid; stale tokens are dropped so a code is shown.
  async function resumeSession() {
    var tokens;
    try {
      tokens = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    } catch (err) {
      return false;
    }
    if (!tokens || tokens.hassUrl !== ORIGIN || !tokens.refresh_token) return false;
    var form = new URLSearchParams();
    form.set("grant_type", "refresh_token");
    form.set("refresh_token", tokens.refresh_token);
    if (tokens.clientId) form.set("client_id", tokens.clientId);
    var response;
    try {
      response = await fetch("/auth/token", {
        method: "POST",
        body: form,
        credentials: "same-origin",
        cache: "no-store",
      });
    } catch (err) {
      return false;
    }
    if (response.ok) {
      var data = await response.json();
      tokens.access_token = data.access_token;
      tokens.expires_in = data.expires_in;
      tokens.token_type = data.token_type;
      tokens.expires = Date.now() + data.expires_in * 1000;
      return save(tokens);
    }
    if (response.status === 400 || response.status === 403) {
      localStorage.removeItem(STORAGE_KEY);
    }
    return false;
  }

  function formatTime(seconds) {
    var minutes = Math.floor(seconds / 60);
    var rest = seconds % 60;
    return minutes + ":" + (rest < 10 ? "0" : "") + rest;
  }

  function tick() {
    var remaining = Math.max(0, Math.round((state.deadline - performance.now()) / 1000));
    $("countdown").textContent = t("expires_in", { time: formatTime(remaining) });
    $("progress").value = state.ttl ? remaining / state.ttl : 0;
    if (remaining <= 0) showResult(false, t("expired"), "new_code");
  }

  function errorMessage(result) {
    var seconds = result.data.retry_after || 60;
    if (result.data.code === "rate_limited") return t("error_rate_limited", { seconds: seconds });
    if (result.data.code === "too_many_pending") {
      return t("error_too_many_pending", { seconds: seconds });
    }
    if (result.data.code === "unavailable") return t("error_unavailable");
    return t("error_generic");
  }

  function deniedMessage(reason) {
    if (reason === "wrong_number") return t("denied_wrong_number");
    if (reason === "local_only") return t("denied_local_only");
    return t("denied");
  }

  function complete(data) {
    var tokens = {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_in: data.expires_in,
      token_type: data.token_type,
      expires: Date.now() + data.expires_in * 1000,
      hassUrl: ORIGIN,
      clientId: data.client_id,
    };
    if (!save(tokens)) {
      showResult(false, t("error_storage"), "new_code");
      return;
    }
    showResult(true, t("approved"));
    setTimeout(function () {
      location.replace("/");
    }, 600);
  }

  function schedulePoll(delay) {
    state.pollTimer = setTimeout(poll, delay || state.pollDelay);
  }

  async function poll() {
    state.pollTimer = null;
    var secret = state.secret;
    if (!secret) return;
    var result;
    try {
      result = await post("/api/beamin/poll", { request_id: state.requestId, secret: secret });
    } catch (err) {
      schedulePoll(); // Network hiccup (car in a tunnel): keep trying until expiry.
      return;
    }
    if (state.secret !== secret) return;
    var data = result.data;
    if (result.status === 200 && data.status === "pending") {
      schedulePoll();
    } else if (result.status === 200 && data.status === "approved") {
      stop();
      complete(data);
    } else if (result.status === 200 && data.status === "denied") {
      showResult(false, deniedMessage(data.reason), "new_code");
    } else if (result.status === 404) {
      showResult(false, t("expired"), "new_code");
    } else if (result.status === 429) {
      schedulePoll((data.retry_after || 5) * 1000);
    } else if (result.status >= 500) {
      schedulePoll();
    } else {
      showResult(false, t("error_generic"), "new_code");
    }
  }

  async function start() {
    stop();
    show("loading");
    var result;
    try {
      result = await post("/api/beamin/request", {
        client_id: ORIGIN + "/",
        touch: navigator.maxTouchPoints > 1,
      });
    } catch (err) {
      showResult(false, t("error_generic"), "retry");
      return;
    }
    if (result.status !== 200) {
      showResult(false, errorMessage(result), "retry");
      return;
    }
    var data = result.data;
    state.requestId = data.request_id;
    state.secret = data.secret;
    state.ttl = data.expires_in;
    state.deadline = performance.now() + data.expires_in * 1000;
    state.pollDelay = (data.poll_interval || 2) * 1000;

    $("qr").src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(data.qr_svg);
    $("code").textContent = data.code;
    // Screen readers spell the code character by character.
    $("code").setAttribute("aria-label", data.code.split("").join(" "));
    $("match").textContent = String(data.match_number);
    show("waiting");
    tick();
    state.tickTimer = setInterval(tick, 1000);
    schedulePoll();
  }

  async function init() {
    localize();
    $("new-code").addEventListener("click", start);
    if (await resumeSession()) {
      location.replace("/");
      return;
    }
    start();
  }

  init();
})();
