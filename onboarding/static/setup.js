/* SafeClaw setup wizard — vanilla JS, no framework.
 *
 * Responsibilities:
 *   - Step navigation (4 steps, hidden fieldsets)
 *   - Conditional field visibility (LLM provider, Telegram on/off)
 *   - Client-side format validation (cheap, gives instant feedback)
 *   - Submit -> POST /api/provision with the right payload shape
 *   - Surface server-side validation errors per-field
 *   - On success -> redirect to /progress/<id>
 *
 * Composio credentials are collected from the customer in Step 2. They
 * own the Composio account (that's where they did their OAuth for Gmail /
 * Drive / Slack), so the four COMPOSIO_* values come from them, not from
 * the operator.
 */
(function () {
  "use strict";

  const TOTAL_STEPS = 4;

  const form = document.getElementById("setup-form");
  if (!form) return;

  const stepper = document.getElementById("stepper");
  const panels = form.querySelectorAll(".step-panel");
  const errorBanner = document.getElementById("form-error");

  // ── Step navigation ──────────────────────────────────────────────────
  function gotoStep(n) {
    panels.forEach(function (panel) {
      panel.classList.toggle("hidden", panel.dataset.step !== String(n));
    });
    stepper.querySelectorAll(".step").forEach(function (li) {
      const step = Number(li.dataset.step);
      li.classList.toggle("active", step === n);
      li.classList.toggle("complete", step < n);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  form.querySelectorAll(".btn-next, .btn-prev").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const target = Number(btn.dataset.goto);
      if (btn.classList.contains("btn-next")) {
        const current = Number(btn.closest(".step-panel").dataset.step);
        if (!validateStep(current)) return;
      }
      gotoStep(target);
    });
  });

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

  const telegramToggle = document.getElementById("telegram_enabled");
  const telegramFields = document.getElementById("telegram-fields");
  telegramToggle.addEventListener("change", function () {
    telegramFields.classList.toggle("hidden", !telegramToggle.checked);
  });

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

      const reader = (form.COMPOSIO_READER_MCP_URL.value || "").trim();
      if (!reader) {
        setFieldError("COMPOSIO_READER_MCP_URL", "Reader MCP URL is required");
        ok = false;
      } else if (!looksLikeMcpUrl(reader)) {
        setFieldError("COMPOSIO_READER_MCP_URL", "Must end with /mcp?user_id=<your_user_id>");
        ok = false;
      }

      const actor = (form.COMPOSIO_ACTOR_MCP_URL.value || "").trim();
      if (!actor) {
        setFieldError("COMPOSIO_ACTOR_MCP_URL", "Actor MCP URL is required");
        ok = false;
      } else if (!looksLikeMcpUrl(actor)) {
        setFieldError("COMPOSIO_ACTOR_MCP_URL", "Must end with /mcp?user_id=<your_user_id>");
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
      COMPOSIO_READER_MCP_URL: form.COMPOSIO_READER_MCP_URL.value.trim(),
      COMPOSIO_ACTOR_MCP_URL: form.COMPOSIO_ACTOR_MCP_URL.value.trim(),
      // Slack
      SLACK_BOT_TOKEN: form.SLACK_BOT_TOKEN.value.trim(),
      SLACK_APP_TOKEN: form.SLACK_APP_TOKEN.value.trim(),
      SLACK_WORKSPACE_ID: form.SLACK_WORKSPACE_ID.value.trim(),
      SLACK_BOT_ADMIN_USER_ID: form.SLACK_BOT_ADMIN_USER_ID.value.trim(),
      SLACK_PUBLIC_CHANNELS: form.SLACK_PUBLIC_CHANNELS.value.trim(),
      telegram_enabled: telegramToggle.checked,
      // The single LLM_API_KEY field — the provisioner routes it to the
      // right env var (OLLAMA_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY)
      // server-side based on the provider radio.
      LLM_API_KEY: apiKey,
    };

    if (telegramToggle.checked) {
      payload.TELEGRAM_BOT_TOKEN = form.TELEGRAM_BOT_TOKEN.value.trim();
      payload.TELEGRAM_ALLOWED_USERS = form.TELEGRAM_ALLOWED_USERS.value.trim();
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
        // Map "llm" pseudo-field back to LLM_API_KEY for highlighting.
        const target = key === "llm" ? "LLM_API_KEY" : key;
        setFieldError(target, errs[key]);
      });
      const summary = body.error || "Some fields didn't check out — see highlighted inputs.";
      errorBanner.textContent = summary;
      errorBanner.classList.remove("hidden");
      // jump to step that contains first error
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
    return null;
  }
})();
