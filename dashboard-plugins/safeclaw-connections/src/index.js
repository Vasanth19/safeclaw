/**
 * SafeClaw Connections — manage integrations from the dashboard.
 *
 * Lists configured connections, the provider catalog, and an add form. The
 * scope a connection gets is DERIVED server-side from (provider, agent) and
 * rendered here as a hard, read-only lock — the UI never lets you pick "send".
 *
 * Pure Hermes Plugin SDK (React from window.__HERMES_PLUGIN_SDK__), no npm
 * imports — so dashboard/dist/index.js is just this file (optionally minified
 * with esbuild). React is NOT bundled.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var C = SDK.components;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;

  var BASE = "/api/plugins/safeclaw-connections";

  function getJSON(path) {
    return fetch(BASE + path).then(function (r) {
      return r.json().then(function (b) {
        if (!r.ok) throw new Error((b && b.detail) || ("HTTP " + r.status));
        return b;
      });
    });
  }

  function badgeColor(scope) {
    if (scope === "read") return "#3ddc97";   // read-only — green
    if (scope === "draft") return "#f5a623";   // draft — amber
    return "#7a8a99";                          // chat/other — grey
  }

  function ConnectionsPage() {
    var connS = useState([]); var conns = connS[0], setConns = connS[1];
    var provS = useState([]); var providers = provS[0], setProviders = provS[1];
    var stS = useState({ status: "loading", err: null }); var st = stS[0], setSt = stS[1];
    // add-form state
    var formS = useState({ provider: "", agent: "", label: "", account: "", name: "" });
    var form = formS[0], setForm = formS[1];
    var busyS = useState(false); var busy = busyS[0], setBusy = busyS[1];

    function reload() {
      setSt({ status: "loading", err: null });
      Promise.all([getJSON("/connections"), getJSON("/providers")])
        .then(function (res) {
          setConns(res[0].connections || []);
          setProviders(res[1].providers || []);
          setSt({ status: "ready", err: null });
        })
        .catch(function (e) { setSt({ status: "error", err: e.message }); });
    }
    useEffect(function () { reload(); }, []);

    var selectedProvider = providers.filter(function (p) { return p.id === form.provider; })[0];
    var agentOptions = selectedProvider ? selectedProvider.bindings : [];

    function submit() {
      if (!form.provider || !form.agent || !form.label) return;
      setBusy(true);
      var id = form.provider + "-" + form.label;
      var body = {
        id: id, provider: form.provider, agent: form.agent,
        label: form.label, display_name: form.name || form.label,
      };
      if (form.account) body.composio_account_id = form.account;
      fetch(BASE + "/connections", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }).then(function (r) {
        return r.json().then(function (b) {
          if (!r.ok) throw new Error((b && b.detail) || ("HTTP " + r.status));
          return b;
        });
      }).then(function () {
        setForm({ provider: "", agent: "", label: "", account: "", name: "" });
        setBusy(false); reload();
      }).catch(function (e) { setBusy(false); setSt({ status: "ready", err: e.message }); });
    }

    function remove(id) {
      fetch(BASE + "/connections/" + id, { method: "DELETE" })
        .then(function () { reload(); });
    }

    // ── connection cards ──
    var cards = conns.map(function (c) {
      return h(C.Card, { key: c.id, className: "p-0" },
        h(C.CardContent, { className: "flex items-center justify-between gap-3 py-3" },
          h("div", { className: "flex flex-col gap-0.5" },
            h("div", { className: "flex items-center gap-2" },
              h("span", { className: "font-medium" }, c.display_name || c.label),
              h(C.Badge, { variant: "outline" }, c.provider_label),
              h("span", {
                className: "inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded",
                style: { color: badgeColor(c.scope), border: "1px solid " + badgeColor(c.scope) },
              }, "🔒 " + c.agent_label + " · " + c.scope),
            ),
            c.mcp_server && h("span", { className: "text-[11px] text-muted-foreground font-mono" },
              "mcp: " + c.mcp_server + (c.env_var ? "  ·  env: " + c.env_var : "")),
          ),
          h(C.Button, {
            onClick: function () { remove(c.id); },
            className: "border border-border px-2 py-1 text-xs hover:bg-destructive/15 cursor-pointer",
          }, "Disconnect"),
        ),
      );
    });

    return h("div", { className: "flex flex-col gap-4" },
      h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, { className: "text-lg" }, "Connections")),
        h(C.CardContent, null,
          h("p", { className: "text-sm text-muted-foreground" },
            "Wire up Gmail (one or many accounts), Slack, Telegram, and Google Drive. ",
            "Each connection binds to a trust boundary and gets only that boundary's scope — ",
            h("b", null, "Reader is read-only, Actor is draft-only"),
            ". You can't grant a send tool here; that's the whole point."),
          st.err && h("p", { className: "text-sm text-destructive mt-2" }, st.err),
        ),
      ),

      // Add form
      h(C.Card, null,
        h(C.CardHeader, null, h(C.CardTitle, { className: "text-sm" }, "Add a connection")),
        h(C.CardContent, { className: "flex flex-col gap-3" },
          h("div", { className: "flex flex-wrap gap-3" },
            // provider
            h("select", {
              className: "border border-border bg-background px-2 py-1.5 text-sm",
              value: form.provider,
              onChange: function (e) { setForm(Object.assign({}, form, { provider: e.target.value, agent: "" })); },
            },
              h("option", { value: "" }, "Provider…"),
              providers.map(function (p) { return h("option", { key: p.id, value: p.id }, p.label); }),
            ),
            // agent (constrained by provider)
            h("select", {
              className: "border border-border bg-background px-2 py-1.5 text-sm",
              value: form.agent, disabled: !selectedProvider,
              onChange: function (e) { setForm(Object.assign({}, form, { agent: e.target.value })); },
            },
              h("option", { value: "" }, "Boundary…"),
              agentOptions.map(function (b) {
                return h("option", { key: b.agent, value: b.agent },
                  b.agent_label + " (" + b.scope + ")");
              }),
            ),
            h("input", {
              className: "border border-border bg-background px-2 py-1.5 text-sm",
              placeholder: "label (e.g. hyphenlabs)", value: form.label,
              onChange: function (e) { setForm(Object.assign({}, form, { label: e.target.value })); },
            }),
            selectedProvider && selectedProvider.needs_account_id &&
              h("input", {
                className: "border border-border bg-background px-2 py-1.5 text-sm",
                placeholder: "Composio connected_account_id", value: form.account,
                onChange: function (e) { setForm(Object.assign({}, form, { account: e.target.value })); },
              }),
            h(C.Button, {
              onClick: submit, disabled: busy || !form.provider || !form.agent || !form.label,
              className: "border border-border bg-foreground/10 px-3 py-1.5 text-sm hover:bg-foreground/20 cursor-pointer",
            }, busy ? "Connecting…" : "Connect"),
          ),
          selectedProvider && form.agent &&
            h("p", { className: "text-[11px] text-muted-foreground" },
              "This will be granted scope ",
              h("b", null, (agentOptions.filter(function (b) { return b.agent === form.agent; })[0] || {}).scope),
              " — locked. It cannot send or exfiltrate."),
        ),
      ),

      // List
      st.status === "loading"
        ? h("p", { className: "text-sm text-muted-foreground" }, "Loading connections…")
        : conns.length === 0
          ? h("p", { className: "text-sm text-muted-foreground" }, "No connections yet.")
          : h("div", { className: "flex flex-col gap-2" }, cards),
    );
  }

  window.__HERMES_PLUGINS__.register("safeclaw-connections", ConnectionsPage);
})();
