/**
 * SafeClaw Memory — 3D brain constellation.
 *
 * The chrome (cards, legend, toggles) is built with the Hermes Plugin SDK's
 * shared React. The 3D canvas itself is vanilla `3d-force-graph` (three.js
 * under the hood), mounted imperatively into a ref'd <div> — so no React
 * reconciler fights the WebGL render loop.
 *
 * Bundled with esbuild into dashboard/dist/index.js (IIFE). React is NOT
 * bundled: it comes from window.__HERMES_PLUGIN_SDK__.
 */
import ForceGraph3D from "3d-force-graph";

(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var C = SDK.components;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useRef = SDK.hooks.useRef;

  var BASE = "/api/plugins/safeclaw-memory";
  var BG = "#0a1612";

  function MemoryPage() {
    var mountRef = useRef(null);
    var graphRef = useRef(null);
    var stateS = useState({ status: "loading", legend: [], stats: null, err: null });
    var st = stateS[0], setSt = stateS[1];
    var drawerS = useState(false);
    var includeDrawer = drawerS[0], setIncludeDrawer = drawerS[1];

    useEffect(function () {
      var disposed = false;
      setSt({ status: "loading", legend: [], stats: null, err: null });

      fetch(BASE + "/graph?include_drawer=" + (includeDrawer ? "true" : "false"))
        .then(function (r) {
          return r.json().then(function (b) {
            if (!r.ok) throw new Error((b && b.detail) || ("HTTP " + r.status));
            return b;
          });
        })
        .then(function (data) {
          if (disposed) return;
          var el = mountRef.current;
          if (!el) return;

          var width = el.clientWidth || 800;
          var height = el.clientHeight || 600;

          var G = ForceGraph3D()(el)
            .backgroundColor(BG)
            .width(width)
            .height(height)
            .graphData({ nodes: data.nodes, links: data.links })
            .nodeColor(function (n) { return n.color; })
            .nodeVal(function (n) { return n.val; })
            .nodeOpacity(0.92)
            .nodeResolution(12)
            .nodeLabel(function (n) {
              return '<div style="font-family:monospace;font-size:12px;color:#e6ebf2;' +
                'background:rgba(10,22,18,.9);padding:4px 8px;border:1px solid ' +
                (n.color || "#3ddc97") + '">' + n.name +
                (n.kind === "page" ? '<br/><span style="opacity:.6">' + n.type + "</span>" : "") +
                "</div>";
            })
            .linkColor(function (l) { return l.kind === "core" ? "#3ddc97" : "#2c4a40"; })
            .linkOpacity(0.35)
            .linkWidth(function (l) { return l.kind === "core" ? 0.6 : 0.3; })
            .warmupTicks(40)
            .cooldownTime(6000);

          // Gentle auto-rotate for the "wow" idle state.
          var angle = 0;
          var distance = 520;
          G.cameraPosition({ z: distance });
          var timer = setInterval(function () {
            if (disposed) return;
            angle += Math.PI / 900;
            G.cameraPosition({
              x: distance * Math.sin(angle),
              z: distance * Math.cos(angle),
            });
          }, 40);

          graphRef.current = { graph: G, timer: timer, el: el };
          setSt({ status: "ready", legend: data.legend || [], stats: data.stats, err: null });
        })
        .catch(function (e) {
          if (!disposed) setSt({ status: "error", legend: [], stats: null, err: e.message });
        });

      return function () {
        disposed = true;
        var g = graphRef.current;
        if (g) {
          clearInterval(g.timer);
          try { g.graph._destructor && g.graph._destructor(); } catch (e) {}
          if (g.el) g.el.innerHTML = "";
          graphRef.current = null;
        }
      };
    }, [includeDrawer]);

    var legendChips = st.legend.map(function (item) {
      return h("div", { key: item.type, className: "flex items-center gap-1.5" },
        h("span", { className: "inline-block w-2.5 h-2.5 rounded-full",
          style: { backgroundColor: item.color } }),
        h("span", { className: "text-[11px] text-muted-foreground" },
          item.type + " · " + item.count));
    });

    return h("div", { className: "flex flex-col gap-4" },
      // Header
      h(C.Card, null,
        h(C.CardHeader, null,
          h("div", { className: "flex items-center justify-between gap-3 flex-wrap" },
            h("div", { className: "flex items-center gap-3" },
              h(C.CardTitle, { className: "text-lg" }, "Memory"),
              st.stats && h(C.Badge, { variant: "outline" },
                st.stats.pages + " pages · " + st.stats.types + " types"),
            ),
            h(C.Button, {
              onClick: function () { setIncludeDrawer(!includeDrawer); },
              className: "border border-border bg-foreground/10 px-3 py-1.5 text-sm hover:bg-foreground/20 cursor-pointer",
            }, includeDrawer ? "Hide legacy drawer" : "Show legacy drawer"),
          ),
        ),
        h(C.CardContent, null,
          h("p", { className: "text-sm text-muted-foreground" },
            "A live 3D map of everything SafeClaw knows. Each star is a page in the brain; ",
            "pages orbit their type, and the types orbit the core. Drag to rotate, scroll to zoom."),
          st.legend.length > 0 &&
            h("div", { className: "flex flex-wrap gap-x-4 gap-y-1.5 mt-3" }, legendChips),
        ),
      ),

      // Canvas / states
      st.status === "error"
        ? h(C.Card, null, h(C.CardContent, null,
            h("p", { className: "text-sm text-destructive py-6 text-center" },
              "Couldn't reach the brain: " + st.err)))
        : h("div", {
            className: "relative w-full overflow-hidden border border-border",
            style: { height: "70vh", background: BG },
          },
            h("div", { ref: mountRef, className: "absolute inset-0" }),
            st.status === "loading" &&
              h("div", { className: "absolute inset-0 flex items-center justify-center" },
                h("span", { className: "text-sm text-muted-foreground" }, "Mapping the brain…")),
          ),
    );
  }

  window.__HERMES_PLUGINS__.register("safeclaw-memory", MemoryPage);
})();
