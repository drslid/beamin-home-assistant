// BeamIn approval panel: type or scan a code, check the device, pick the
// number shown on it, approve. Vanilla custom element styled with the Home
// Assistant theme variables; every dynamic value goes through textContent.
import "./i18n.js";

const { createTranslator, formatDuration } = self.BeamInI18n;

// Module scope: the frontend may re-create the panel element just after load
// (cached panels replaced by fresh ones), after the code left the URL.
let codeFromLink = "";

const CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";
const KIND_ICONS = {
  car: "mdi:car",
  tv: "mdi:television",
  tablet: "mdi:tablet",
  phone: "mdi:cellphone",
  computer: "mdi:monitor",
  unknown: "mdi:devices",
};
const ERROR_KEYS = {
  invalid_code: "error_invalid_code",
  expired: "error_invalid_code",
  invalid_format: "invalid_format",
  wrong_number: "error_wrong_number",
  not_interactive: "error_not_interactive",
  temporary_session: "error_temporary_session",
  local_only: "error_local_only",
  not_allowed: "error_not_allowed",
};

const STYLE = `
  :host {
    display: block;
    min-height: 100%;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--ha-font-family-body, Roboto, sans-serif);
    -webkit-font-smoothing: antialiased;
  }
  [hidden] { display: none !important; }
  .toolbar {
    display: flex;
    align-items: center;
    height: var(--header-height, 56px);
    padding: 0 12px;
    background: var(--app-header-background-color);
    color: var(--app-header-text-color, var(--text-primary-color));
    border-bottom: var(--app-header-border-bottom, none);
    box-sizing: border-box;
  }
  .toolbar .title { margin-left: 12px; font-size: 20px; font-weight: 400; }
  .icon-button {
    width: 48px; height: 48px; border: 0; border-radius: 50%;
    background: none; color: inherit; cursor: pointer;
  }
  .content { max-width: 600px; margin: 0 auto; padding: 16px; }
  .card {
    padding: 20px;
    border-radius: var(--ha-card-border-radius, 12px);
    background: var(--ha-card-background, var(--card-background-color));
    box-shadow: var(--ha-card-box-shadow, none);
    border: 1px solid var(--divider-color);
  }
  h2 { margin: 0 0 12px; font-size: 22px; font-weight: 500; outline: none; }
  p { margin: 8px 0; }
  .muted { color: var(--secondary-text-color); }
  label { display: block; margin: 16px 0 6px; font-weight: 500; }
  input[type="text"], select {
    width: 100%; box-sizing: border-box; padding: 12px;
    border: 1px solid var(--divider-color); border-radius: 8px;
    background: var(--card-background-color); color: var(--primary-text-color);
    font: inherit;
  }
  input.code {
    font-family: "Roboto Mono", Menlo, Consolas, monospace;
    font-size: 32px; letter-spacing: 0.15em; text-align: center; text-transform: uppercase;
  }
  .actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 12px; margin-top: 20px; }
  button.primary, button.secondary {
    min-height: 44px; padding: 0 24px; border-radius: 22px;
    font: inherit; font-weight: 500; cursor: pointer;
  }
  button.primary { border: 0; background: var(--primary-color); color: var(--text-primary-color); }
  button.secondary { border: 1px solid var(--divider-color); background: none; color: var(--primary-color); }
  button:disabled { opacity: 0.45; cursor: default; }
  button:focus-visible, input:focus-visible, select:focus-visible {
    outline: 2px solid var(--primary-color); outline-offset: 2px;
  }
  .link { border: 0; background: none; padding: 0; color: var(--primary-color); font: inherit; cursor: pointer; text-decoration: underline; }
  .device { display: flex; align-items: center; gap: 16px; margin: 4px 0 12px; }
  .device ha-icon { --mdc-icon-size: 40px; color: var(--primary-color); }
  .device .label { font-size: 20px; font-weight: 500; }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; margin: 12px 0; }
  dt { color: var(--secondary-text-color); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .callout {
    margin: 16px 0; padding: 12px 14px; border-radius: 8px;
    border-left: 4px solid var(--warning-color, #ffa600);
    background: rgba(255, 166, 0, 0.12);
  }
  .callout.error { border-left-color: var(--error-color, #db4437); background: rgba(219, 68, 55, 0.12); }
  .numbers { display: flex; gap: 12px; margin: 8px 0 4px; }
  .numbers button {
    flex: 1; min-height: 72px; border-radius: 12px;
    border: 2px solid var(--divider-color); background: none;
    color: var(--primary-text-color); font-size: 32px; font-weight: 700; cursor: pointer;
  }
  .numbers button[aria-checked="true"] {
    border-color: var(--primary-color); background: var(--primary-color); color: var(--text-primary-color);
  }
  fieldset { border: 0; margin: 16px 0 0; padding: 0; }
  legend { font-weight: 500; margin-bottom: 6px; padding: 0; }
  .radio { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
  .radio input { width: 20px; height: 20px; margin: 0; accent-color: var(--primary-color); }
  .done { text-align: center; }
  .done .symbol { font-size: 56px; font-weight: 700; line-height: 1.2; }
  .done .symbol.ok { color: var(--success-color, #43a047); }
  .done .symbol.error { color: var(--error-color, #db4437); }
  .done .actions { justify-content: center; }
`;

function normalizeCode(value) {
  return String(value || "")
    .toUpperCase()
    .split("")
    .filter((char) => CODE_ALPHABET.includes(char))
    .join("")
    .slice(0, 6);
}

function formatCode(code) {
  return code.length > 3 ? `${code.slice(0, 3)}-${code.slice(3)}` : code;
}

function element(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "text") node.textContent = value;
    else if (key === "on") for (const [event, handler] of Object.entries(value)) node.addEventListener(event, handler);
    else if (key.startsWith("aria-") || key === "role" || key === "for" || key === "icon") node.setAttribute(key, value);
    else node[key] = value;
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

class BeamInPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._step = "enter";
    this._code = "";
    this._error = "";
    this._busy = false;
    this._ticker = null;
  }

  set hass(hass) {
    const first = !this._hass;
    const language = hass.locale?.language || hass.language;
    const languageChanged = this._hass && language !== this._language;
    this._hass = hass;
    if (first) {
      this._setLanguage(language);
      this._takeCodeFromUrl();
      this._render();
    } else if (languageChanged) {
      this._setLanguage(language);
      this._render();
    }
  }

  set narrow(narrow) {
    this._narrow = narrow;
    const menu = this.shadowRoot.querySelector(".menu");
    if (menu) menu.hidden = !narrow;
  }

  disconnectedCallback() {
    this._stopTicker();
  }

  _setLanguage(language) {
    this._language = language;
    ({ t: this._t } = createTranslator([language, navigator.language]));
  }

  // The QR code opens /beamin?code=…: prefill, then drop the code from the URL
  // and history. Opening the link only shows the request, never approves it.
  _takeCodeFromUrl() {
    const url = new URL(location.href);
    if (url.searchParams.has("code")) {
      codeFromLink = normalizeCode(url.searchParams.get("code"));
      url.searchParams.delete("code");
      history.replaceState(history.state, "", url.pathname + url.search + url.hash);
    }
    if (codeFromLink.length === 6) {
      this._code = codeFromLink;
      this._lookup();
    }
  }

  _render() {
    const t = this._t;
    const root = this.shadowRoot;
    root.textContent = "";
    root.append(element("style", { text: STYLE }));
    const menu = element(
      "button",
      {
        className: "icon-button menu",
        hidden: !this._narrow,
        "aria-label": t("menu"),
        on: { click: () => this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true })) },
      },
      [element("ha-icon", { icon: "mdi:menu" })],
    );
    root.append(element("div", { className: "toolbar" }, [menu, element("div", { className: "title", text: "BeamIn" })]));

    let card;
    if (this._step === "review") card = this._renderReview();
    else if (this._step === "done") card = this._renderDone();
    else card = this._renderEnter();
    root.append(element("div", { className: "content" }, [card]));
    // Move focus only when the step changes, so screen readers announce it.
    if (this._focusedStep !== this._step) {
      this._focusedStep = this._step;
      root.querySelector("h2")?.focus();
    }
  }

  _renderEnter() {
    const t = this._t;
    const input = element("input", {
      type: "text",
      id: "code",
      className: "code",
      value: formatCode(this._code),
      placeholder: "K7F-29X",
      autocomplete: "off",
      autocapitalize: "characters",
      spellcheck: false,
      inputMode: "text",
      enterKeyHint: "go",
      maxLength: 7,
      on: {
        input: (event) => {
          this._code = normalizeCode(event.target.value);
          event.target.value = formatCode(this._code);
        },
        keydown: (event) => {
          if (event.key === "Enter") this._submitCode();
        },
      },
    });
    return element("div", { className: "card" }, [
      element("h2", { text: t("enter_title"), tabIndex: -1 }),
      element("p", { className: "muted", text: t("enter_help", { url: `${location.origin}/beam` }) }),
      element("label", { for: "code", text: t("code_input") }),
      input,
      this._error ? element("div", { className: "callout error", role: "alert", text: this._error }) : null,
      element("div", { className: "actions" }, [
        element("button", {
          className: "primary",
          text: t("continue"),
          disabled: this._busy,
          on: { click: () => this._submitCode() },
        }),
      ]),
    ]);
  }

  _renderReview() {
    const t = this._t;
    const data = this._data;
    const device = data.device;
    const admin = data.approver.is_admin && data.targets.length > 1;
    const target = data.targets.find((user) => user.id === this._target) || data.approver;
    const choices = element(
      "div",
      { className: "numbers", role: "radiogroup", "aria-labelledby": "pick" },
      data.choices.map((number) =>
        element("button", {
          role: "radio",
          "aria-checked": String(this._choice === number),
          text: String(number),
          on: {
            click: () => {
              this._choice = number;
              this._render();
            },
          },
        }),
      ),
    );

    const durationRadio = (value, label) =>
      element("label", { className: "radio" }, [
        element("input", {
          type: "radio",
          name: "duration",
          value,
          checked: this._duration === value,
          on: { change: () => (this._duration = value) },
        }),
        element("span", { text: label }),
      ]);

    const userBlock = [];
    if (admin && this._showTargets) {
      const select = element(
        "select",
        {
          id: "target",
          on: {
            change: (event) => {
              this._target = event.target.value;
              this._render();
            },
          },
        },
        data.targets.map((user) =>
          element("option", {
            value: user.id,
            selected: user.id === target.id,
            text: user.id === data.approver.id ? t("you", { name: user.name }) : user.name,
          }),
        ),
      );
      userBlock.push(element("label", { for: "target", text: t("sign_in_as") }), select);
    } else {
      userBlock.push(
        element("p", {}, [
          element("span", { className: "muted", text: t("sign_in_as") }),
          " ",
          element("strong", { text: target.name }),
        ]),
      );
      if (admin) {
        userBlock.push(
          element("button", {
            className: "link",
            text: t("another_user"),
            on: {
              click: () => {
                this._showTargets = true;
                this._render();
              },
            },
          }),
        );
      }
    }
    if (target.is_admin && device.shared) {
      userBlock.push(
        element("div", {
          className: "callout",
          text: t("admin_shared_warning", { kind: t(`kind_${device.kind}`) }),
        }),
      );
    }

    this._ageNode = element("dd");
    this._expiresNode = element("dd");
    this._updateClock();

    return element("div", { className: "card" }, [
      element("h2", { text: t("review_title"), tabIndex: -1 }),
      element("div", { className: "device" }, [
        element("ha-icon", { icon: KIND_ICONS[device.kind] || KIND_ICONS.unknown }),
        element("div", {}, [
          element("div", { className: "label", text: device.label }),
          element("div", { className: "muted", text: `${t(`kind_${device.kind}`)} · ${t("device_reported")}` }),
        ]),
      ]),
      element("dl", {}, [
        element("dt", { text: t("ip_address") }),
        element("dd", { text: data.ip || "—" }),
        element("dt", { text: t("network") }),
        element("dd", { text: t(`network_${data.network}`) }),
        element("dt", { text: t("requested") }),
        this._ageNode,
        element("dt", { text: t("expires") }),
        this._expiresNode,
      ]),
      element("div", { className: "callout", role: "note", text: t("warning") }),
      element("p", { id: "pick", text: t("pick_number") }),
      choices,
      element("fieldset", {}, [
        element("legend", { text: t("session") }),
        durationRadio("normal", t("duration_normal")),
        durationRadio("temporary", t("duration_temporary", { duration: formatDuration(t, data.temporary_minutes) })),
      ]),
      ...userBlock,
      this._error ? element("div", { className: "callout error", role: "alert", text: this._error }) : null,
      element("div", { className: "actions" }, [
        element("button", {
          className: "secondary",
          text: t("deny"),
          disabled: this._busy,
          on: { click: () => this._deny() },
        }),
        element("button", {
          className: "primary",
          text: t("approve"),
          disabled: this._busy || this._choice === null,
          on: { click: () => this._approve() },
        }),
      ]),
    ]);
  }

  _renderDone() {
    const t = this._t;
    return element("div", { className: "card done" }, [
      element("div", { className: `symbol ${this._result.ok ? "ok" : "error"}`, "aria-hidden": "true", text: this._result.ok ? "✓" : "✕" }),
      element("h2", { text: this._result.message, tabIndex: -1, role: "status" }),
      element("div", { className: "actions" }, [
        element("button", { className: "primary", text: t("again"), on: { click: () => this._reset() } }),
      ]),
    ]);
  }

  _reset() {
    this._stopTicker();
    codeFromLink = "";
    Object.assign(this, { _step: "enter", _code: "", _error: "", _data: null, _result: null });
    this._render();
  }

  _submitCode() {
    if (this._code.length !== 6) {
      this._error = this._t("invalid_format");
      this._render();
      return;
    }
    this._lookup();
  }

  async _lookup() {
    this._busy = true;
    this._error = "";
    try {
      const data = await this._hass.callApi("GET", `beamin/pending/${this._code}`);
      Object.assign(this, {
        _step: "review",
        _data: data,
        _loadedAt: performance.now(),
        _choice: null,
        _duration: "normal",
        _target: data.approver.id,
        _showTargets: false,
      });
      this._startTicker();
    } catch (err) {
      codeFromLink = "";
      this._step = "enter";
      this._error = this._message(err);
    }
    this._busy = false;
    this._render();
  }

  async _approve() {
    if (this._choice === null) return;
    this._busy = true;
    this._render();
    try {
      const result = await this._hass.callApi("POST", "beamin/approve", {
        code: this._code,
        match_choice: this._choice,
        duration: this._duration,
        target_user_id: this._target,
      });
      this._finish(true, this._t("done_approved", { device: result.device, user: result.user }));
    } catch (err) {
      const code = err?.body?.code;
      if (code === "local_only" || code === "not_allowed") {
        this._busy = false;
        this._error = this._message(err);
        this._render();
      } else {
        this._finish(false, this._message(err));
      }
    }
  }

  async _deny() {
    this._busy = true;
    this._render();
    try {
      await this._hass.callApi("POST", "beamin/deny", { code: this._code });
      this._finish(false, this._t("done_denied"));
    } catch (err) {
      this._finish(false, this._message(err));
    }
  }

  _finish(ok, message) {
    this._stopTicker();
    codeFromLink = "";
    Object.assign(this, { _step: "done", _busy: false, _error: "", _code: "", _result: { ok, message } });
    this._render();
  }

  _message(err) {
    const body = err?.body || {};
    if (body.code === "locked") {
      return this._t("error_locked", { minutes: Math.max(1, Math.ceil((body.retry_after || 300) / 60)) });
    }
    return this._t(ERROR_KEYS[body.code] || "error_approve_generic");
  }

  _startTicker() {
    this._stopTicker();
    this._ticker = setInterval(() => this._updateClock(), 1000);
  }

  _stopTicker() {
    clearInterval(this._ticker);
    this._ticker = null;
  }

  _updateClock() {
    if (this._step !== "review" || !this._data || !this._ageNode) return;
    const elapsed = Math.round((performance.now() - this._loadedAt) / 1000);
    const remaining = Math.max(0, this._data.expires_in - elapsed);
    this._ageNode.textContent = this._t("seconds_ago", { seconds: this._data.age + elapsed });
    this._expiresNode.textContent = this._t("in_seconds", { seconds: remaining });
    if (remaining === 0 && !this._busy) {
      this._stopTicker();
      Object.assign(this, { _step: "enter", _error: this._t("error_invalid_code") });
      this._render();
    }
  }
}

customElements.define("beamin-panel", BeamInPanel);
