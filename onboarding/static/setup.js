(function () {
  "use strict";

  const TOTAL_STEPS = 5;

  const form = document.getElementById("setup-form");
  if (!form) return;

  const stepper = document.getElementById("stepper");
  const panels = form.querySelectorAll(".step-panel");
  const instrPanels = document.querySelectorAll(".instr-panel");
  const errorBanner = document.getElementById("form-error");
  const instrToggle = document.getElementById("instructions-toggle");
  const instrPane = document.getElementById("setup-instructions");

  // ── Tab navigation ──────────────────────────────────────────────────
  function gotoStep(n) {
    console.log("Navigating to step:", n);
    panels.forEach(function (panel) {
      panel.classList.toggle("hidden", panel.dataset.step !== String(n));
    });
    instrPanels.forEach(function (panel) {
      panel.classList.toggle("hidden", panel.id !== "instr-step-" + n);
    });
    stepper.querySelectorAll(".step").forEach(function (li) {
      const step = Number(li.dataset.step);
      li.classList.toggle("active", step === n);
    });
  }

  // Use event delegation or direct attachment, ensuring it works
  stepper.addEventListener("click", function (e) {
    const li = e.target.closest(".step");
    if (li) {
      const step = Number(li.dataset.step);
      gotoStep(step);
    }
  });

  // Default to first step
  gotoStep(1);

  // ── Instructions slide-over ──────────────────────────────────────────
  const backdrop = document.getElementById("instr-backdrop");
  const instrClose = document.getElementById("instr-close");

  function openInstr() {
    instrPane.classList.add("show");
    backdrop && backdrop.classList.add("show");
    instrToggle.querySelector("span").textContent = "Hide Instructions";
  }
  function closeInstr() {
    instrPane.classList.remove("show");
    backdrop && backdrop.classList.remove("show");
    instrToggle.querySelector("span").textContent = "Show Instructions";
  }

  if (instrToggle) {
    instrToggle.addEventListener("click", function () {
      instrPane.classList.contains("show") ? closeInstr() : openInstr();
    });
  }
  if (instrClose) instrClose.addEventListener("click", closeInstr);
  if (backdrop) backdrop.addEventListener("click", closeInstr);

  // ── JSON copy button ─────────────────────────────────────────────────
  const copyBtn = document.getElementById("slack-manifest-copy");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      const text = document.getElementById("slack-manifest").textContent;
      navigator.clipboard.writeText(text).then(function () {
        copyBtn.textContent = "Copied!";
        copyBtn.classList.add("copied");
        setTimeout(function () {
          copyBtn.textContent = "Copy";
          copyBtn.classList.remove("copied");
        }, 2000);
      });
    });
  }

  // ── Conditional visibility ───────────────────────────────────────────
  function refreshLLMVisibility() {
    const provider = form.querySelector('input[name="llm_provider"]:checked').value;
    form.querySelectorAll("[data-show-when]").forEach(function (el) {
      const cond = el.dataset.showWhen.split("=");
      const shouldShow = cond[0] === "llm_provider" && cond[1] === provider;
      el.classList.toggle("hidden", !shouldShow);
    });
    form.querySelectorAll("[data-when]").forEach(function (el) {
      const cond = el.dataset.when.split("=");
      const shouldShow = cond[0] === "llm_provider" && cond[1] === provider;
      el.classList.toggle("show", shouldShow);
    });
    // Adjust API key label / placeholder to match the chosen provider.
    const labelText = document.querySelector(".api-key-label-text");
    const placeholders = {
      "ollama-cloud": "ollama_...",
      "anthropic": "sk-ant-...",
      "openai": "sk-...",
    };
    const labels = {
      "ollama-cloud": "Ollama API key",
      "anthropic": "Anthropic API key",
      "openai": "OpenAI API key",
    };
    const apiInput = document.getElementById("LLM_API_KEY");
    if (apiInput) apiInput.placeholder = placeholders[provider] || "paste key";
    if (labelText) labelText.textContent = labels[provider] || "API key";
  }
  form.querySelectorAll('input[name="llm_provider"]').forEach(function (r) {
    r.addEventListener("change", refreshLLMVisibility);
  });
  refreshLLMVisibility();

  // ── Slack auto-populate: workspace ID + admin user ID ───────────────────
  (function () {
    const botTokenEl  = form.SLACK_BOT_TOKEN;
    const workspaceEl = form.SLACK_WORKSPACE_ID;
    const adminUserEl = form.SLACK_BOT_ADMIN_USER_ID;
    if (!botTokenEl || !workspaceEl) return;

    let _lastToken = "";

    async function lookupToken(token) {
      if (!token.startsWith("xoxb-") || token.length < 20) return;
      if (token === _lastToken) return;
      _lastToken = token;

      workspaceEl.placeholder = "Looking up…";
      workspaceEl.disabled = true;
      if (adminUserEl) { adminUserEl.placeholder = "Looking up…"; adminUserEl.disabled = true; }

      try {
        const resp = await fetch("/api/slack/lookup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bot_token: token }),
        });
        const body = await resp.json();
        if (body.ok) {
          if (body.team_id) { workspaceEl.value = body.team_id; workspaceEl.placeholder = "T…"; }
          if (body.user_id && adminUserEl && !adminUserEl.value) {
            adminUserEl.value = body.user_id;
          }
        } else {
          const hint = body.error === "invalid_auth" || body.error === "not_found"
            ? "token invalid or revoked"
            : body.error || "unknown";
          workspaceEl.placeholder = "T… (lookup failed: " + hint + ")";
        }
      } catch (_) {
        workspaceEl.placeholder = "T… (network error)";
      } finally {
        workspaceEl.disabled = false;
        if (adminUserEl) { adminUserEl.placeholder = "U…"; adminUserEl.disabled = false; }
      }
    }

    botTokenEl.addEventListener("blur", function () { lookupToken(botTokenEl.value.trim()); });
    botTokenEl.addEventListener("paste", function (e) {
      const pasted = (e.clipboardData || window.clipboardData).getData("text").trim();
      setTimeout(function () { lookupToken(pasted); }, 0);
    });
  })();

  // ── Slack channel ID validation ──────────────────────────────────────────
  (function () {
    const botTokenEl   = form.SLACK_BOT_TOKEN;
    const channelsEl   = form.SLACK_PUBLIC_CHANNELS;
    if (!channelsEl) return;

    let _badgesEl = null;

    function getBadgesContainer() {
      if (!_badgesEl) {
        _badgesEl = document.createElement("div");
        _badgesEl.className = "channel-badges";
        channelsEl.closest(".field").appendChild(_badgesEl);
      }
      return _badgesEl;
    }

    function renderBadges(channels) {
      const container = getBadgesContainer();
      container.innerHTML = "";
      channels.forEach(function (ch) {
        const b = document.createElement("span");
        b.className = "channel-badge " + (ch.ok ? "badge-ok" : "badge-err");
        b.textContent = ch.ok ? ("✓ #" + ch.name) : ("✗ " + ch.id);
        if (!ch.ok) b.title = ch.error || "not accessible";
        container.appendChild(b);
      });
    }

    async function checkChannels() {
      const token    = (botTokenEl && botTokenEl.value.trim()) || "";
      const rawInput = channelsEl.value.trim();
      const ids      = rawInput.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      if (!token.startsWith("xoxb-") || ids.length === 0) return;

      getBadgesContainer().textContent = "Checking…";
      try {
        const resp = await fetch("/api/slack/check-channels", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bot_token: token, channel_ids: ids }),
        });
        const body = await resp.json();
        if (body.ok) renderBadges(body.channels);
        else getBadgesContainer().textContent = "Check failed: " + (body.error || "unknown");
      } catch (_) {
        getBadgesContainer().textContent = "Network error";
      }
    }

    channelsEl.addEventListener("blur", checkChannels);
    channelsEl.addEventListener("paste", function () { setTimeout(checkChannels, 50); });

    // ── Channel browser ──────────────────────────────────────────────────────
    const browseBtn    = document.getElementById("slack-browse-channels");
    const browserEl    = document.getElementById("channel-browser");
    const searchEl     = document.getElementById("channel-search");
    const listEl       = document.getElementById("channel-list");
    let   _allChannels = [];

    // Enable browse button once we have a valid token
    function updateBrowseBtn() {
      const token = (botTokenEl && botTokenEl.value.trim()) || "";
      browseBtn.disabled = !token.startsWith("xoxb-");
    }
    if (botTokenEl) {
      botTokenEl.addEventListener("input", updateBrowseBtn);
      botTokenEl.addEventListener("blur", updateBrowseBtn);
    }

    function renderChannelList(channels) {
      listEl.innerHTML = "";
      const selected = channelsEl.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      channels.forEach(function (ch) {
        const li = document.createElement("li");
        const checked = selected.includes(ch.id);
        li.className = checked ? "ch-selected" : "";
        li.innerHTML = '<label><input type="checkbox"' + (checked ? " checked" : "") + '> ' +
          (ch.is_private ? "🔒 " : "#") + ch.name +
          ' <span class="ch-id">' + ch.id + '</span></label>';
        li.querySelector("input").addEventListener("change", function (e) {
          let ids = channelsEl.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
          if (e.target.checked) {
            if (!ids.includes(ch.id)) ids.push(ch.id);
          } else {
            ids = ids.filter(function (id) { return id !== ch.id; });
          }
          channelsEl.value = ids.join(", ");
          li.className = e.target.checked ? "ch-selected" : "";
          checkChannels();
        });
        listEl.appendChild(li);
      });
    }

    searchEl.addEventListener("input", function () {
      const q = searchEl.value.toLowerCase();
      const filtered = q ? _allChannels.filter(function (c) { return c.name.toLowerCase().includes(q); }) : _allChannels;
      renderChannelList(filtered);
    });

    browseBtn.addEventListener("click", async function () {
      if (!browserEl.classList.contains("hidden")) {
        browserEl.classList.add("hidden");
        return;
      }
      const token = (botTokenEl && botTokenEl.value.trim()) || "";
      listEl.innerHTML = '<li class="ch-loading">Loading channels…</li>';
      browserEl.classList.remove("hidden");
      try {
        const resp = await fetch("/api/slack/list-channels?bot_token=" + encodeURIComponent(token));
        const body = await resp.json();
        if (body.ok) {
          _allChannels = body.channels;
          searchEl.value = "";
          renderChannelList(_allChannels);
        } else {
          listEl.innerHTML = '<li class="ch-error">Error: ' + (body.error || "unknown") + '</li>';
        }
      } catch (_) {
        listEl.innerHTML = '<li class="ch-error">Network error</li>';
      }
    });

    // Close browser on outside click
    document.addEventListener("click", function (e) {
      if (!browserEl.contains(e.target) && e.target !== browseBtn) {
        browserEl.classList.add("hidden");
      }
    });
  })();

  const telegramToggle = document.getElementById("telegram_enabled");
  const telegramFields = document.getElementById("telegram-fields");
  telegramToggle.addEventListener("change", function () {
    telegramFields.classList.toggle("hidden", !telegramToggle.checked);
  });

  // ── Google Drive: drag-and-drop + paste + file picker ───────────────────
  (function () {
    const dropZone   = document.getElementById("gdrive-drop-zone");
    const overlay    = document.getElementById("gdrive-drop-overlay");
    const textarea   = document.getElementById("GDRIVE_SERVICE_ACCOUNT_JSON");
    const fileBtn    = document.getElementById("gdrive-file-btn");
    const fileInput  = document.getElementById("gdrive-file-input");
    const statusEl   = document.getElementById("gdrive-status");
    const emailBadge = document.getElementById("gdrive-email-badge");
    const emailValue = document.getElementById("gdrive-email-value");
    const copyEmail  = document.getElementById("gdrive-copy-email");
    const shareHint  = document.getElementById("gdrive-share-hint");
    if (!dropZone || !textarea) return;

    function applyJson(text) {
      textarea.value = text;
      validateGdriveJson(text);
    }

    async function validateGdriveJson(text) {
      text = (text || "").trim();
      if (!text) { setGdriveStatus(""); hideEmailBadge(); return; }

      setGdriveStatus("Validating…");
      try {
        var resp = await fetch("/api/gdrive/validate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ json_str: text }),
        });
        var body = await resp.json();
        if (body.ok) {
          setGdriveStatus("✓ Valid service account key", "ok");
          showEmailBadge(body.client_email);
        } else {
          setGdriveStatus("✗ " + (body.error || "Invalid JSON"), "err");
          hideEmailBadge();
        }
      } catch (_) {
        setGdriveStatus("✗ Network error", "err");
        hideEmailBadge();
      }
    }

    function setGdriveStatus(msg, kind) {
      if (!statusEl) return;
      statusEl.textContent = msg;
      statusEl.className = "gdrive-status" + (kind ? " gdrive-status-" + kind : "");
    }
    function showEmailBadge(email) {
      if (!emailBadge || !emailValue) return;
      emailValue.textContent = email || "";
      emailBadge.classList.remove("hidden");
      if (shareHint) shareHint.classList.remove("hidden");
    }
    function hideEmailBadge() {
      if (emailBadge) emailBadge.classList.add("hidden");
      if (shareHint) shareHint.classList.add("hidden");
    }

    // Copy email button
    if (copyEmail) {
      copyEmail.addEventListener("click", function () {
        var email = (emailValue && emailValue.textContent) || "";
        navigator.clipboard.writeText(email).then(function () {
          copyEmail.textContent = "Copied!";
          setTimeout(function () { copyEmail.textContent = "Copy"; }, 2000);
        });
      });
    }

    // Drag events on the drop zone
    ["dragenter", "dragover"].forEach(function (evt) {
      dropZone.addEventListener(evt, function (e) {
        e.preventDefault(); e.stopPropagation();
        overlay.classList.add("active");
      });
    });
    ["dragleave", "dragend"].forEach(function (evt) {
      dropZone.addEventListener(evt, function (e) {
        if (!dropZone.contains(e.relatedTarget)) overlay.classList.remove("active");
      });
    });
    dropZone.addEventListener("drop", function (e) {
      e.preventDefault(); e.stopPropagation();
      overlay.classList.remove("active");
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function (ev) { applyJson(ev.target.result); };
      reader.readAsText(file);
    });

    // File picker
    if (fileBtn && fileInput) {
      fileBtn.addEventListener("click", function () { fileInput.click(); });
      fileInput.addEventListener("change", function () {
        var file = fileInput.files && fileInput.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function (ev) { applyJson(ev.target.result); };
        reader.readAsText(file);
        fileInput.value = "";
      });
    }

    // Validate on manual paste or blur
    textarea.addEventListener("blur", function () { validateGdriveJson(textarea.value); });
    textarea.addEventListener("paste", function () {
      setTimeout(function () { validateGdriveJson(textarea.value); }, 50);
    });
  })();

  // ── Client-side validation ───────────────────────────────────────────
  function setFieldError(name, msg) {
    const el = form.querySelector('[name="' + name + '"]');
    if (!el) return;
    el.classList.toggle("invalid", !!msg);
    let errEl = el.parentElement.querySelector(".field-error");
    if (msg) {
      if (!errEl) {
        errEl = document.createElement("p");
        errEl.className = "field-error";
        el.parentElement.appendChild(errEl);
      }
      errEl.textContent = msg;
    } else if (errEl) {
      errEl.remove();
    }
  }

  function clearErrors() {
    form.querySelectorAll(".invalid").forEach(function (el) {
      el.classList.remove("invalid");
    });
    form.querySelectorAll(".field-error").forEach(function (el) { el.remove(); });
    if (errorBanner) {
      errorBanner.classList.add("hidden");
      errorBanner.textContent = "";
    }
  }

  function looksLikeMcpUrl(url) {
    // Must be http(s) and end with /mcp...?user_id=<something>.
    if (!/^https?:\/\//i.test(url)) return false;
    if (url.indexOf("/mcp") === -1) return false;
    if (url.indexOf("user_id=") === -1) return false;
    // Make sure user_id has a non-empty value.
    const m = url.match(/user_id=([^&\s]+)/);
    return !!(m && m[1]);
  }

  function validateStep(step) {
    clearErrors();
    let ok = true;
    const provider = form.querySelector('input[name="llm_provider"]:checked').value;

    if (step === 1) {
      const apiKey = (form.LLM_API_KEY.value || "").trim();
      if (!apiKey) {
        setFieldError("LLM_API_KEY", "API key is required");
        ok = false;
      } else if (provider === "ollama-cloud" && !apiKey.startsWith("ollama_")) {
        setFieldError("LLM_API_KEY", "Ollama Cloud keys start with ollama_");
        ok = false;
      } else if (provider === "anthropic" && !apiKey.startsWith("sk-ant-")) {
        setFieldError("LLM_API_KEY", "Anthropic keys start with sk-ant-");
        ok = false;
      } else if (provider === "openai" && !apiKey.startsWith("sk-")) {
        setFieldError("LLM_API_KEY", "OpenAI keys start with sk-");
        ok = false;
      }
    }

    if (step === 2) {
      const apiKey = (form.COMPOSIO_API_KEY.value || "").trim();
      if (!apiKey) {
        setFieldError("COMPOSIO_API_KEY", "Composio API key is required");
        ok = false;
      } else if (!apiKey.startsWith("ak_")) {
        setFieldError("COMPOSIO_API_KEY", "Composio API key must start with ak_");
        ok = false;
      }

      const userId = (form.COMPOSIO_USER_ID.value || "").trim();
      if (!userId) {
        setFieldError("COMPOSIO_USER_ID", "Composio user ID is required");
        ok = false;
      }
    }

    if (step === 3) {
      if (!form.SLACK_BOT_TOKEN.value.startsWith("xoxb-")) {
        setFieldError("SLACK_BOT_TOKEN", "Must start with xoxb-");
        ok = false;
      }
      if (!form.SLACK_APP_TOKEN.value.startsWith("xapp-")) {
        setFieldError("SLACK_APP_TOKEN", "Must start with xapp-");
        ok = false;
      }
      if (!form.SLACK_WORKSPACE_ID.value.startsWith("T")) {
        setFieldError("SLACK_WORKSPACE_ID", "Must start with T");
        ok = false;
      }
      if (!form.SLACK_BOT_ADMIN_USER_ID.value.startsWith("U")) {
        setFieldError("SLACK_BOT_ADMIN_USER_ID", "Must start with U");
        ok = false;
      }
      if (!form.SLACK_PUBLIC_CHANNELS.value.trim()) {
        setFieldError("SLACK_PUBLIC_CHANNELS", "At least one channel ID");
        ok = false;
      }
    }

    if (step === 4 && telegramToggle.checked) {
      const t = form.TELEGRAM_BOT_TOKEN.value.trim();
      if (!t.includes(":")) {
        setFieldError("TELEGRAM_BOT_TOKEN", "Looks like 123456:ABC-...");
        ok = false;
      }
      if (!form.TELEGRAM_ALLOWED_USERS.value.trim()) {
        setFieldError("TELEGRAM_ALLOWED_USERS", "At least one user ID");
        ok = false;
      }
    }

    if (step === 5) {
      const ta = document.getElementById("GDRIVE_SERVICE_ACCOUNT_JSON");
      const raw = (ta && ta.value || "").trim();
      if (!raw) {
        setFieldError("GDRIVE_SERVICE_ACCOUNT_JSON", "Service account JSON is required");
        ok = false;
      } else {
        try {
          const parsed = JSON.parse(raw);
          if (parsed.type !== "service_account") {
            setFieldError("GDRIVE_SERVICE_ACCOUNT_JSON", "JSON must be a service_account key type");
            ok = false;
          }
        } catch (_) {
          setFieldError("GDRIVE_SERVICE_ACCOUNT_JSON", "Invalid JSON — paste the full contents of the downloaded key file");
          ok = false;
        }
      }
    }

    return ok;
  }

  // ── Build payload ────────────────────────────────────────────────────
  function buildPayload() {
    const provider = form.querySelector('input[name="llm_provider"]:checked').value;
    const apiKey = (form.LLM_API_KEY.value || "").trim();

    const payload = {
      llm_provider: provider,
      HERMES_INFERENCE_PROVIDER: provider,
      // Composio (customer-supplied)
      COMPOSIO_API_KEY: form.COMPOSIO_API_KEY.value.trim(),
      COMPOSIO_USER_ID: form.COMPOSIO_USER_ID.value.trim(),
      // Slack
      SLACK_BOT_TOKEN: form.SLACK_BOT_TOKEN.value.trim(),
      SLACK_APP_TOKEN: form.SLACK_APP_TOKEN.value.trim(),
      SLACK_WORKSPACE_ID: form.SLACK_WORKSPACE_ID.value.trim(),
      SLACK_BOT_ADMIN_USER_ID: form.SLACK_BOT_ADMIN_USER_ID.value.trim(),
      SLACK_PUBLIC_CHANNELS: form.SLACK_PUBLIC_CHANNELS.value.trim(),
      telegram_enabled: telegramToggle.checked,
      LLM_API_KEY: apiKey,
    };

    if (telegramToggle.checked) {
      payload.TELEGRAM_BOT_TOKEN = form.TELEGRAM_BOT_TOKEN.value.trim();
      payload.TELEGRAM_ALLOWED_USERS = form.TELEGRAM_ALLOWED_USERS.value.trim();
    }

    const gdriveEl = document.getElementById("GDRIVE_SERVICE_ACCOUNT_JSON");
    if (gdriveEl && gdriveEl.value.trim()) {
      payload.GDRIVE_SERVICE_ACCOUNT_JSON = gdriveEl.value.trim();
    }

    return payload;
  }

  // ── Submit ───────────────────────────────────────────────────────────
  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    let firstBadStep = 0;
    for (let i = 1; i <= TOTAL_STEPS; i++) {
      if (!validateStep(i) && firstBadStep === 0) firstBadStep = i;
    }
    if (firstBadStep) {
      gotoStep(firstBadStep);
      return;
    }

    const submitBtn = form.querySelector(".btn-submit");
    submitBtn.disabled = true;
    submitBtn.textContent = "Validating with upstream APIs...";

    let resp, body;
    try {
      resp = await fetch("/api/provision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload()),
      });
      body = await resp.json();
    } catch (err) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Provision now";
      errorBanner.textContent = "Network error: " + err.message;
      errorBanner.classList.remove("hidden");
      return;
    }

    if (!resp.ok) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Provision now";
      const errs = body.errors || {};
      Object.keys(errs).forEach(function (key) {
        const target = key === "llm" ? "LLM_API_KEY" : key;
        setFieldError(target, errs[key]);
      });
      const summary = body.error || "Some fields didn't check out — see highlighted inputs.";
      errorBanner.textContent = summary;
      errorBanner.classList.remove("hidden");
      const firstBad = Object.keys(errs)[0];
      const step = stepOf(firstBad);
      if (step) gotoStep(step);
      return;
    }

    if (body.install_id) {
      window.location.href = "/progress/" + body.install_id;
    }
  });

  function stepOf(field) {
    if (!field) return null;
    if (field === "llm" || field === "LLM_API_KEY") return 1;
    if (field.startsWith("COMPOSIO_")) return 2;
    if (field.startsWith("SLACK_")) return 3;
    if (field.startsWith("TELEGRAM_")) return 4;
    if (field.startsWith("GDRIVE_")) return 5;
    return null;
  }
})();

