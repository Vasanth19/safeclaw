/**
 * SafeClaw Personas — dashboard plugin (no build step; plain IIFE on the SDK).
 *
 * Renders the personas grouped by trust boundary (Reader / Actor). Each
 * persona shows its voice (model, tone, summon phrases, skills) and its
 * INHERITED, locked tool allowlist — reinforcing that a persona can change
 * how the assistant speaks but never what it can touch.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var C = SDK.components;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useCallback = SDK.hooks.useCallback;
  var cn = SDK.utils.cn;

  var BASE = "/api/plugins/safeclaw-personas";

  function api(path, options) {
    return fetch(BASE + path, options).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) {
          var msg = (body && body.detail) || ("HTTP " + r.status);
          var err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
          err.status = r.status;
          throw err;
        }
        return body;
      });
    });
  }

  function csv(arr) {
    return (arr || []).join(", ");
  }
  function fromCsv(s) {
    return (s || "")
      .split(",")
      .map(function (x) { return x.trim(); })
      .filter(Boolean);
  }

  // ── Locked inherited-tools strip ──────────────────────────────────────────
  function ToolLock(props) {
    var tools = props.tools || [];
    return h("div", { className: "flex flex-col gap-1.5 border border-border/60 bg-background/30 p-3" },
      h("div", { className: "flex items-center gap-2" },
        h("span", { className: "text-xs", "aria-hidden": true }, "🔒"),
        h("span", { className: "text-xs font-medium tracking-wide uppercase text-muted-foreground" },
          "Inherited tools — locked"),
      ),
      h("div", { className: "flex flex-wrap gap-1.5" },
        tools.length === 0
          ? h("span", { className: "text-xs text-muted-foreground" }, "(agent config not found)")
          : tools.map(function (t) {
              return h(C.Badge, { key: t, variant: "outline", className: "font-mono text-[11px]" }, t);
            }),
      ),
      h("p", { className: "text-[11px] leading-snug text-muted-foreground/80" },
        "Bound to this persona's agent. A persona cannot grant itself new tools — that's the trust-boundary guarantee."),
    );
  }

  // ── One persona card ──────────────────────────────────────────────────────
  function PersonaCard(props) {
    var p = props.persona;
    var model = p.model || {};
    return h(C.Card, { className: "flex flex-col gap-3" },
      h(C.CardHeader, null,
        h("div", { className: "flex items-start justify-between gap-3" },
          h("div", { className: "flex flex-col gap-1" },
            h(C.CardTitle, { className: "text-base" }, p.name || p.id),
            p.job && h("span", { className: "text-xs text-muted-foreground" }, p.job),
          ),
          h(C.Badge, { variant: "outline", className: "shrink-0 font-mono text-[11px]" },
            (model.provider || "?") + " · " + (model.name || "?")),
        ),
      ),
      h(C.CardContent, { className: "flex flex-col gap-3" },
        p.behavior && p.behavior.tone &&
          h("div", { className: "flex flex-col gap-0.5" },
            h("span", { className: "text-[11px] uppercase tracking-wide text-muted-foreground" }, "Tone"),
            h("span", { className: "text-sm" }, p.behavior.tone),
          ),
        p.summon_phrases && p.summon_phrases.length > 0 &&
          h("div", { className: "flex flex-col gap-1" },
            h("span", { className: "text-[11px] uppercase tracking-wide text-muted-foreground" }, "Summon phrases"),
            h("div", { className: "flex flex-wrap gap-1.5" },
              p.summon_phrases.map(function (s) {
                return h(C.Badge, { key: s, variant: "secondary", className: "text-[11px]" }, "“" + s + "”");
              }),
            ),
          ),
        p.skills && p.skills.length > 0 &&
          h("div", { className: "flex flex-wrap gap-1.5" },
            p.skills.map(function (s) {
              return h(C.Badge, { key: s, className: "text-[11px]" }, s);
            }),
          ),
        h(ToolLock, { tools: p.inherited_tools }),
        h("div", { className: "flex justify-end" },
          h(C.Button, {
            onClick: function () { props.onDelete(p.id); },
            className: cn("text-xs text-muted-foreground hover:text-destructive transition-colors cursor-pointer"),
          }, "Delete"),
        ),
      ),
    );
  }

  // ── Agent (trust boundary) column ─────────────────────────────────────────
  function AgentColumn(props) {
    var agent = props.agent;
    var personas = props.personas;
    return h("div", { className: "flex flex-col gap-3" },
      h("div", { className: "flex items-center gap-2 border-b border-border pb-2" },
        h("h2", { className: "text-lg font-medium" }, agent.label),
        h(C.Badge, { variant: "outline", className: "text-[11px]" }, agent.badge),
      ),
      h("p", { className: "text-xs leading-snug text-muted-foreground" }, agent.trust),
      personas.length === 0
        ? h("p", { className: "text-sm text-muted-foreground italic py-4" },
            "No " + agent.label + " personas yet.")
        : personas.map(function (p) {
            return h(PersonaCard, { key: p.id, persona: p, onDelete: props.onDelete });
          }),
    );
  }

  // ── Create form ───────────────────────────────────────────────────────────
  function CreateForm(props) {
    var s = useState({
      id: "", name: "", agent: "actor", job: "",
      provider: "anthropic", model: "claude-opus-4.7",
      tone: "", system_prompt: "", summon: "", skills: "",
    });
    var form = s[0], setForm = s[1];
    var errS = useState(null); var err = errS[0], setErr = errS[1];
    var busyS = useState(false); var busy = busyS[0], setBusy = busyS[1];

    function set(k, v) { setForm(Object.assign({}, form, { [k]: v })); }

    function submit() {
      setErr(null); setBusy(true);
      api("/personas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: form.id, name: form.name, agent: form.agent, job: form.job,
          model: { provider: form.provider, name: form.model },
          behavior: { tone: form.tone, system_prompt: form.system_prompt },
          summon_phrases: fromCsv(form.summon),
          skills: fromCsv(form.skills),
        }),
      }).then(function () {
        setBusy(false);
        props.onCreated();
      }).catch(function (e) {
        setBusy(false);
        setErr(e.message);
      });
    }

    var field = function (label, node) {
      return h("div", { className: "flex flex-col gap-1" },
        h(C.Label, null, label), node);
    };
    var inputCls = "w-full bg-background/40 border border-border px-3 py-2 text-sm";

    return h(C.Card, null,
      h(C.CardHeader, null, h(C.CardTitle, { className: "text-base" }, "New persona")),
      h(C.CardContent, { className: "flex flex-col gap-3" },
        h("div", { className: "grid grid-cols-2 gap-3" },
          field("ID (kebab-case)", h(C.Input, { value: form.id, placeholder: "email-concierge",
            onChange: function (e) { set("id", e.target.value); } })),
          field("Name", h(C.Input, { value: form.name, placeholder: "Email Concierge",
            onChange: function (e) { set("name", e.target.value); } })),
          field("Trust boundary", h(C.Select, {
              value: form.agent, onChange: function (e) { set("agent", e.target.value); } },
            h(C.SelectOption, { value: "reader" }, "Reader (read-only)"),
            h(C.SelectOption, { value: "actor" }, "Actor (draft + send)"),
          )),
          field("Job (one line)", h(C.Input, { value: form.job, placeholder: "Drafts replies in your voice",
            onChange: function (e) { set("job", e.target.value); } })),
          field("Model provider", h(C.Input, { value: form.provider,
            onChange: function (e) { set("provider", e.target.value); } })),
          field("Model name", h(C.Input, { value: form.model,
            onChange: function (e) { set("model", e.target.value); } })),
        ),
        field("Tone", h(C.Input, { value: form.tone, placeholder: "warm, concise, professional",
          onChange: function (e) { set("tone", e.target.value); } })),
        field("System prompt", h("textarea", { className: cn(inputCls, "min-h-[120px] font-mono"),
          value: form.system_prompt, onChange: function (e) { set("system_prompt", e.target.value); } })),
        field("Summon phrases (comma-separated)", h(C.Input, { value: form.summon,
          placeholder: "draft a reply, respond to this",
          onChange: function (e) { set("summon", e.target.value); } })),
        field("Skills (comma-separated)", h(C.Input, { value: form.skills, placeholder: "email-triage",
          onChange: function (e) { set("skills", e.target.value); } })),
        err && h("p", { className: "text-sm text-destructive border border-destructive/40 bg-destructive/10 p-2" }, err),
        h("div", { className: "flex justify-end gap-2" },
          h(C.Button, { onClick: props.onCancel, className: "text-sm text-muted-foreground cursor-pointer" }, "Cancel"),
          h(C.Button, { onClick: submit, disabled: busy || !form.id || !form.name,
            className: cn("border border-border bg-foreground/10 px-4 py-2 text-sm hover:bg-foreground/20 cursor-pointer") },
            busy ? "Saving…" : "Create persona"),
        ),
      ),
    );
  }

  // ── Page ──────────────────────────────────────────────────────────────────
  function PersonasPage() {
    var pS = useState([]); var personas = pS[0], setPersonas = pS[1];
    var aS = useState([]); var agents = aS[0], setAgents = aS[1];
    var lS = useState(true); var loading = lS[0], setLoading = lS[1];
    var fS = useState(false); var showForm = fS[0], setShowForm = fS[1];
    var eS = useState(null); var loadErr = eS[0], setLoadErr = eS[1];

    var refresh = useCallback(function () {
      setLoading(true);
      Promise.all([api("/personas"), api("/agents")])
        .then(function (res) {
          setPersonas(res[0].personas || []);
          setAgents(res[1].agents || []);
          setLoading(false);
        })
        .catch(function (e) { setLoadErr(e.message); setLoading(false); });
    }, []);

    useEffect(function () { refresh(); }, [refresh]);

    function del(id) {
      api("/personas/" + id, { method: "DELETE" }).then(refresh);
    }

    if (loadErr) {
      return h("div", { className: "p-4 text-sm text-destructive" },
        "Failed to load personas: " + loadErr);
    }

    return h("div", { className: "flex flex-col gap-6" },
      // Intro banner
      h(C.Card, null,
        h(C.CardHeader, null,
          h("div", { className: "flex items-center justify-between gap-3" },
            h(C.CardTitle, { className: "text-lg" }, "Personas"),
            h(C.Button, {
              onClick: function () { setShowForm(!showForm); },
              className: cn("border border-border bg-foreground/10 px-3 py-1.5 text-sm hover:bg-foreground/20 cursor-pointer") },
              showForm ? "Close" : "+ New persona"),
          ),
        ),
        h(C.CardContent, null,
          h("p", { className: "text-sm text-muted-foreground leading-relaxed" },
            "A persona is a voice — a prompt, model, and tone bound to one trust boundary. ",
            "It inherits that agent's tools and can never grant itself more. ",
            "Change how SafeClaw speaks; never change what it's allowed to touch."),
        ),
      ),

      showForm && h(CreateForm, {
        onCancel: function () { setShowForm(false); },
        onCreated: function () { setShowForm(false); refresh(); },
      }),

      loading
        ? h("p", { className: "text-sm text-muted-foreground p-4" }, "Loading…")
        : h("div", { className: "grid grid-cols-1 lg:grid-cols-2 gap-6 items-start" },
            agents.map(function (a) {
              return h(AgentColumn, {
                key: a.id,
                agent: a,
                personas: personas.filter(function (p) { return p.agent === a.id; }),
                onDelete: del,
              });
            }),
          ),
    );
  }

  window.__HERMES_PLUGINS__.register("safeclaw-personas", PersonasPage);
})();
