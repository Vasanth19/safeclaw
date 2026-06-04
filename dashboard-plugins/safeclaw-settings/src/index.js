/**
 * SafeClaw Settings — one screen for the operator's setup state.
 *
 * Consolidates the manual onboarding steps: Composio project + trust-split MCP
 * readiness, GBrain health, connected-account count, and the client handoff URL
 * (the one-click link you share so the customer just opens the Connections page
 * and clicks each connector). Status-only — it never renders a secret value.
 *
 * Pure Hermes Plugin SDK (React from window.__HERMES_PLUGIN_SDK__), no npm
 * imports — dashboard/dist/index.js is this file (optionally esbuild-minified).
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var C = SDK.components;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;

  var BASE = "/api/plugins/safeclaw-settings";

  function getJSON(path) {
    return fetch(BASE + path).then(function (r) {
      return r.json().then(function (b) {
        if (!r.ok) throw new Error((b && b.detail) || ("HTTP " + r.status));
        return b;
      });
    });
  }

  function dot(ok) {
    return h("span", {
      style: {
        display: "inline-block", width: "9px", height: "9px", borderRadius: "999px",
        background: ok ? "#3ddc97" : "#f5a623", marginRight: "8px", flex: "0 0 auto",
      },
    });
  }

  function Row(label, ok, hint) {
    return h("div", { key: label, className: "flex items-start gap-2 py-1.5" },
      h("span", { className: "mt-1" }, dot(ok)),
      h("div", { className: "flex flex-col" },
        h("span", { className: "text-sm" }, (ok ? "" : "") + label),
        hint && h("span", { className: "text-[11px] text-muted-foreground font-mono" }, hint),
      ),
    );
  }

  function SettingsPage() {
    var stS = useState(null); var st = stS[0], setSt = stS[1];
    var accS = useState(null); var acc = accS[0], setAcc = accS[1];
    var ckS = useState(null); var ck = ckS[0], setCk = ckS[1];
    var errS = useState(null); var err = errS[0], setErr = errS[1];
    var copiedS = useState(false); var copied = copiedS[0], setCopied = copiedS[1];

    function reload() {
      setErr(null);
      Promise.all([getJSON("/status"), getJSON("/access"), getJSON("/checklist")])
        .then(function (r) { setSt(r[0]); setAcc(r[1]); setCk(r[2]); })
        .catch(function (e) { setErr(e.message); });
    }
    useEffect(function () { reload(); }, []);

    function copyHandoff() {
      if (!acc || !acc.handoff_url) return;
      try {
        navigator.clipboard.writeText(acc.handoff_url);
        setCopied(true);
        setTimeout(function () { setCopied(false); }, 1500);
      } catch (e) { /* clipboard may be blocked over plain http — ignore */ }
    }

    var composio = st && st.composio;

    return h("div", { className: "flex flex-col gap-4" },
      // Header
      h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, { className: "text-lg" }, "Settings")),
        h(C.CardContent, null,
          h("p", { className: "text-sm text-muted-foreground" },
            "Everything you need to finish onboarding ", st && st.client ? h("b", null, st.client) : "this client",
            " in one place. Share the handoff URL below; the customer opens it and clicks each connector on the Connections tab."),
          err && h("p", { className: "text-sm text-destructive mt-2" }, err),
        ),
      ),

      // Setup checklist
      ck && h(C.Card, null,
        h(C.CardHeader, null,
          h(C.CardTitle, { className: "text-sm" },
            "Setup checklist — " + ck.done + "/" + ck.total + (ck.complete ? "  ✅ ready" : ""))),
        h(C.CardContent, null,
          ck.items.map(function (i) { return Row(i.label, i.done, i.hint); })),
      ),

      // Composio + Brain
      st && h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, { className: "text-sm" }, "Composio & brain")),
        h(C.CardContent, null,
          Row("Project key on box (COMPOSIO_API_KEY)", composio.project_key_set, "project-scoped — org key never reaches the box"),
          Row("Reader MCP wired (read-only)", composio.reader_mcp_url_set, null),
          Row("Actor MCP wired (draft, no send)", composio.actor_mcp_url_set, null),
          Row("GBrain HTTP server alive", st.brain.alive, st.brain.http_url),
          Row("Accounts connected by customer", st.connections.count > 0, st.connections.count + " connected"),
        ),
      ),

      // Client handoff URL
      acc && h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, { className: "text-sm" }, "Client handoff link")),
        h(C.CardContent, { className: "flex flex-col gap-2" },
          acc.handoff_url
            ? h("div", { className: "flex flex-col gap-2" },
                h("p", { className: "text-sm text-muted-foreground" },
                  "Share this one-click link. It opens the Connections page already signed in — the customer just clicks each connector."),
                h("div", { className: "flex items-center gap-2" },
                  h("code", { className: "text-[12px] break-all bg-foreground/5 border border-border px-2 py-1.5 rounded flex-1" }, acc.handoff_url),
                  h(C.Button, {
                    onClick: copyHandoff,
                    className: "border border-border px-3 py-1.5 text-sm hover:bg-foreground/10 cursor-pointer whitespace-nowrap",
                  }, copied ? "Copied ✓" : "Copy"),
                ),
                h("p", { className: "text-[11px] text-destructive" },
                  "⚠ This link contains the access password — share it over a private channel only."),
              )
            : h("div", { className: "flex flex-col gap-1" },
                acc.host_url && h("p", { className: "text-sm" },
                  "Connections page: ", h("code", { className: "text-[12px]" }, acc.host_url)),
                h("p", { className: "text-[11px] text-muted-foreground" }, acc.reason || "Handoff URL not available yet."),
              ),
        ),
      ),

      h(C.Button, {
        onClick: reload,
        className: "self-start border border-border px-3 py-1.5 text-sm hover:bg-foreground/10 cursor-pointer",
      }, "Refresh"),
    );
  }

  window.__HERMES_PLUGINS__.register("safeclaw-settings", SettingsPage);
})();
