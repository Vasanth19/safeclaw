/**
 * dashboard/dashboard-html.js — Marcus v2 SPA dashboard HTML.
 *
 * Returns the complete HTML string for the dashboard. All CSS and JS are
 * inline. No external dependencies. Vanilla JS SPA, dark theme with
 * RE Reset brand colors.
 */

export function getDashboardHtml() {
  return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Marcus v2 — Dashboard</title>
<style>
  /* ------------------------------------------------------------------ */
  /* Reset & base                                                         */
  /* ------------------------------------------------------------------ */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:          #0f0f1a;
    --card:        #1a1a2e;
    --border:      #2a2a4a;
    --terracotta:  #C65E2C;
    --green:       #36544F;
    --gold:        #EBA937;
    --beige:       #D6C6B9;
    --white:       #f0f0f0;
    --muted:       #6b7280;
    --danger:      #ef4444;
    --success:     #22c55e;
    --nav-width:   64px;
    --font:        system-ui, -apple-system, sans-serif;
    --mono:        'SF Mono', 'Cascadia Code', Consolas, monospace;
  }

  html, body {
    height: 100%;
    background: var(--bg);
    color: var(--beige);
    font-family: var(--font);
    font-size: 14px;
    line-height: 1.5;
    overflow: hidden;
  }

  /* ------------------------------------------------------------------ */
  /* Login screen                                                         */
  /* ------------------------------------------------------------------ */
  #login-screen {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100vh;
    background: var(--bg);
  }

  .login-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 40px;
    width: 360px;
    text-align: center;
  }

  .login-card .logo {
    font-size: 28px;
    font-weight: 700;
    color: var(--white);
    letter-spacing: -0.5px;
    margin-bottom: 4px;
  }

  .login-card .logo span { color: var(--terracotta); }

  .login-card .subtitle {
    color: var(--muted);
    font-size: 13px;
    margin-bottom: 28px;
  }

  .login-card input {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--white);
    font-family: var(--mono);
    font-size: 13px;
    padding: 10px 14px;
    margin-bottom: 12px;
    outline: none;
    transition: border-color 0.15s;
  }

  .login-card input:focus { border-color: var(--terracotta); }

  .login-card .error {
    color: var(--danger);
    font-size: 12px;
    margin-bottom: 10px;
    min-height: 16px;
  }

  /* ------------------------------------------------------------------ */
  /* App shell                                                            */
  /* ------------------------------------------------------------------ */
  #app {
    display: none;
    height: 100vh;
    flex-direction: row;
  }

  #app.visible { display: flex; }

  /* ------------------------------------------------------------------ */
  /* Sidebar nav                                                          */
  /* ------------------------------------------------------------------ */
  #sidebar {
    width: var(--nav-width);
    background: var(--card);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px 0;
    gap: 4px;
    flex-shrink: 0;
    z-index: 10;
  }

  .sidebar-brand {
    font-size: 18px;
    font-weight: 800;
    color: var(--terracotta);
    margin-bottom: 20px;
    letter-spacing: -1px;
  }

  .nav-btn {
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 10px;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    transition: all 0.15s;
    position: relative;
  }

  .nav-btn:hover { background: var(--bg); color: var(--beige); }

  .nav-btn.active {
    background: rgba(198, 94, 44, 0.15);
    color: var(--terracotta);
  }

  .nav-btn svg { width: 20px; height: 20px; flex-shrink: 0; }

  .nav-label {
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .nav-divider {
    width: 32px;
    height: 1px;
    background: var(--border);
    margin: 6px 0;
  }

  /* ------------------------------------------------------------------ */
  /* Main content area                                                    */
  /* ------------------------------------------------------------------ */
  #main {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ------------------------------------------------------------------ */
  /* Top bar                                                              */
  /* ------------------------------------------------------------------ */
  #topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
    height: 56px;
    border-bottom: 1px solid var(--border);
    background: var(--card);
    flex-shrink: 0;
  }

  .topbar-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--white);
    letter-spacing: -0.2px;
  }

  .topbar-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  #connection-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--muted);
  }

  #status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--muted);
    transition: background 0.3s;
  }

  #status-dot.connected { background: var(--success); }
  #status-dot.error { background: var(--danger); }

  .topbar-time {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
  }

  /* ------------------------------------------------------------------ */
  /* Content viewport                                                     */
  /* ------------------------------------------------------------------ */
  #content {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  #content::-webkit-scrollbar { width: 6px; }
  #content::-webkit-scrollbar-track { background: transparent; }
  #content::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  /* ------------------------------------------------------------------ */
  /* Tabs / views                                                         */
  /* ------------------------------------------------------------------ */
  .view { display: none; animation: fadeIn 0.2s ease; }
  .view.active { display: block; }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* ------------------------------------------------------------------ */
  /* Stats row                                                            */
  /* ------------------------------------------------------------------ */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
  }

  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    transition: border-color 0.15s;
  }

  .stat-card:hover { border-color: var(--terracotta); }

  .stat-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
    margin-bottom: 8px;
  }

  .stat-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--white);
    font-family: var(--mono);
    line-height: 1;
    margin-bottom: 4px;
  }

  .stat-sub {
    font-size: 12px;
    color: var(--muted);
  }

  .stat-card.accent-terracotta { border-left: 3px solid var(--terracotta); }
  .stat-card.accent-green      { border-left: 3px solid var(--green); }
  .stat-card.accent-gold       { border-left: 3px solid var(--gold); }
  .stat-card.accent-danger     { border-left: 3px solid var(--danger); }

  /* ------------------------------------------------------------------ */
  /* Section headers                                                      */
  /* ------------------------------------------------------------------ */
  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  .section-title {
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--white);
  }

  .section-count {
    font-size: 11px;
    color: var(--muted);
    font-family: var(--mono);
  }

  /* ------------------------------------------------------------------ */
  /* Cards                                                                */
  /* ------------------------------------------------------------------ */
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 20px;
  }

  /* ------------------------------------------------------------------ */
  /* Tables                                                               */
  /* ------------------------------------------------------------------ */
  .data-table {
    width: 100%;
    border-collapse: collapse;
  }

  .data-table th {
    padding: 10px 16px;
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.2);
  }

  .data-table td {
    padding: 12px 16px;
    border-bottom: 1px solid rgba(42,42,74,0.5);
    vertical-align: top;
    font-size: 13px;
    color: var(--beige);
  }

  .data-table tr:last-child td { border-bottom: none; }

  .data-table tr:hover td { background: rgba(255,255,255,0.02); }

  .data-table .mono { font-family: var(--mono); font-size: 12px; }

  /* ------------------------------------------------------------------ */
  /* Integration cards                                                    */
  /* ------------------------------------------------------------------ */
  .integ-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
    margin-top: 8px;
  }
  @media (max-width: 1100px) { .integ-grid { grid-template-columns: 1fr; } }

  .integ-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    min-height: 240px;
  }

  .integ-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }

  .integ-title {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .8px;
    color: var(--white);
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .integ-pill {
    font-family: var(--mono);
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    background: rgba(255,255,255,0.05);
    color: var(--beige);
  }

  .integ-pill.urgent { background: rgba(239,68,68,0.15); color: var(--danger); }
  .integ-pill.warn   { background: rgba(235,169,55,0.15); color: var(--gold); }
  .integ-pill.ok     { background: rgba(34,197,94,0.15); color: var(--success); }

  .integ-list { display: flex; flex-direction: column; gap: 8px; }

  .integ-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 8px;
    background: rgba(255,255,255,0.02);
    border: 1px solid transparent;
    transition: background .15s, border-color .15s;
  }
  .integ-row:hover { background: rgba(255,255,255,0.04); border-color: var(--border); }

  .integ-row .primary {
    color: var(--white);
    font-size: 13px;
    font-weight: 500;
    line-height: 1.35;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .integ-row .secondary {
    color: var(--muted);
    font-size: 11px;
    margin-top: 2px;
  }

  .integ-row .right {
    margin-left: auto;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    white-space: nowrap;
    padding-left: 8px;
  }

  .integ-row .body { flex: 1; min-width: 0; }

  .integ-row a { color: inherit; text-decoration: none; }
  .integ-row a:hover { color: var(--gold); }

  .integ-error {
    color: var(--muted);
    font-size: 12px;
    font-family: var(--mono);
    padding: 12px;
    border: 1px dashed var(--border);
    border-radius: 8px;
  }

  /* ------------------------------------------------------------------ */
  /* Badges / pills                                                       */
  /* ------------------------------------------------------------------ */
  .badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  .badge-green   { background: rgba(54,84,79,0.3);  color: #5fa896; }
  .badge-gold    { background: rgba(235,169,55,0.15); color: var(--gold); }
  .badge-red     { background: rgba(239,68,68,0.15); color: #f87171; }
  .badge-beige   { background: rgba(214,198,185,0.1); color: var(--beige); }
  .badge-terra   { background: rgba(198,94,44,0.2);  color: #e07a4a; }
  .badge-muted   { background: rgba(107,114,128,0.15); color: var(--muted); }

  /* ------------------------------------------------------------------ */
  /* Memory timeline                                                      */
  /* ------------------------------------------------------------------ */
  .memory-search {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
  }

  .search-input {
    flex: 1;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--white);
    font-size: 13px;
    padding: 9px 14px;
    outline: none;
    transition: border-color 0.15s;
  }

  .search-input:focus { border-color: var(--terracotta); }
  .search-input::placeholder { color: var(--muted); }

  .memory-list { display: flex; flex-direction: column; gap: 2px; }

  .memory-item {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .memory-item:hover { border-color: var(--terracotta); background: rgba(26,26,46,0.8); }

  .memory-item.expanded { border-color: var(--terracotta); }

  .memory-header { display: flex; align-items: flex-start; gap: 12px; }

  .memory-salience-bar {
    width: 4px;
    min-height: 36px;
    border-radius: 2px;
    flex-shrink: 0;
    align-self: stretch;
  }

  .memory-body { flex: 1; min-width: 0; }

  .memory-summary {
    font-size: 13px;
    color: var(--beige);
    margin-bottom: 6px;
    line-height: 1.4;
  }

  .memory-meta {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .memory-salience-text {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
  }

  .entity-tag {
    background: rgba(54,84,79,0.2);
    color: #5fa896;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 11px;
  }

  .memory-detail {
    display: none;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }

  .memory-item.expanded .memory-detail { display: block; }

  .memory-detail-row {
    display: flex;
    gap: 8px;
    margin-bottom: 6px;
    font-size: 12px;
  }

  .memory-detail-label {
    color: var(--muted);
    width: 80px;
    flex-shrink: 0;
  }

  .memory-detail-value {
    color: var(--beige);
    font-family: var(--mono);
    word-break: break-all;
  }

  /* ------------------------------------------------------------------ */
  /* Activity feed                                                        */
  /* ------------------------------------------------------------------ */
  .activity-feed { display: flex; flex-direction: column; gap: 1px; }

  .activity-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid rgba(42,42,74,0.4);
  }

  .activity-item:last-child { border-bottom: none; }

  .activity-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 5px;
  }

  .activity-text {
    flex: 1;
    font-size: 13px;
    color: var(--beige);
    line-height: 1.4;
  }

  .activity-time {
    font-size: 11px;
    color: var(--muted);
    font-family: var(--mono);
    flex-shrink: 0;
  }

  /* ------------------------------------------------------------------ */
  /* Tasks view                                                           */
  /* ------------------------------------------------------------------ */
  .tasks-section { margin-bottom: 28px; }

  .tasks-section-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
    padding: 0 16px 10px;
  }

  /* ------------------------------------------------------------------ */
  /* Priority view                                                        */
  /* ------------------------------------------------------------------ */
  .priority-group { margin-bottom: 24px; }

  .priority-group-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--gold);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .priority-group-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  .priority-item {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 8px;
    display: flex;
    align-items: flex-start;
    gap: 12px;
    transition: border-color 0.15s;
  }

  .priority-item:hover { border-color: var(--gold); }

  .priority-item.completed { opacity: 0.5; }

  .priority-check {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid var(--border);
    flex-shrink: 0;
    margin-top: 1px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .priority-item.completed .priority-check {
    background: var(--green);
    border-color: var(--green);
  }

  .priority-content { flex: 1; min-width: 0; }

  .priority-text {
    font-size: 13px;
    color: var(--beige);
    margin-bottom: 4px;
  }

  .priority-item.completed .priority-text {
    text-decoration: line-through;
    color: var(--muted);
  }

  .priority-meta {
    font-size: 11px;
    color: var(--muted);
    font-family: var(--mono);
  }

  .priority-item.overdue { border-left: 3px solid var(--terracotta, #C65E2C); }

  .priority-text a { color: inherit; text-decoration: none; }
  .priority-text a:hover { color: var(--gold); }

  .pri-rationale {
    font-size: 11px;
    color: var(--muted);
    font-style: italic;
    margin-bottom: 4px;
  }

  .pri-badges { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }

  .pri-badge {
    font-size: 10px;
    font-family: var(--mono);
    padding: 1px 6px;
    border-radius: 4px;
    border: 1px solid var(--border);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .pri-badge.brain { color: var(--gold); border-color: var(--gold); }
  .pri-badge.clickup { color: #8B7BEE; border-color: #8B7BEE; }
  .pri-badge.due { color: var(--beige); }
  .pri-badge.overdue {
    color: #fff;
    background: var(--terracotta, #C65E2C);
    border-color: var(--terracotta, #C65E2C);
  }

  .priority-banner {
    font-size: 11px;
    color: var(--muted);
    font-family: var(--mono);
    margin-bottom: 18px;
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
  }
  .priority-banner .warn { color: var(--terracotta, #C65E2C); }

  /* ------------------------------------------------------------------ */
  /* Audit log                                                            */
  /* ------------------------------------------------------------------ */
  .audit-filters {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }

  .filter-btn {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    padding: 5px 12px;
    transition: all 0.15s;
  }

  .filter-btn:hover { border-color: var(--beige); color: var(--beige); }
  .filter-btn.active { border-color: var(--terracotta); color: var(--terracotta); background: rgba(198,94,44,0.1); }

  .audit-exfil td { background: rgba(239,68,68,0.05) !important; }
  .audit-exfil td:first-child { border-left: 3px solid var(--danger); }

  .audit-blocked td { background: rgba(235,169,55,0.05) !important; }

  /* ------------------------------------------------------------------ */
  /* Empty state                                                          */
  /* ------------------------------------------------------------------ */
  .empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--muted);
  }

  .empty-icon { font-size: 40px; margin-bottom: 12px; opacity: 0.4; }
  .empty-text { font-size: 14px; }

  /* ------------------------------------------------------------------ */
  /* Loading skeleton                                                     */
  /* ------------------------------------------------------------------ */
  .skeleton {
    background: linear-gradient(90deg, var(--card) 25%, var(--border) 50%, var(--card) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;
    border-radius: 4px;
    height: 14px;
    margin: 6px 0;
  }

  @keyframes shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  /* ------------------------------------------------------------------ */
  /* Buttons                                                              */
  /* ------------------------------------------------------------------ */
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border-radius: 8px;
    border: none;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }

  .btn-primary {
    background: var(--terracotta);
    color: #fff;
  }

  .btn-primary:hover { background: #b05224; }

  .btn-ghost {
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
  }

  .btn-ghost:hover { color: var(--beige); border-color: var(--beige); }

  /* ------------------------------------------------------------------ */
  /* Grid helpers                                                         */
  /* ------------------------------------------------------------------ */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }

  @media (max-width: 900px) {
    .two-col { grid-template-columns: 1fr; }
  }

  /* ------------------------------------------------------------------ */
  /* Scrollable table wrapper                                             */
  /* ------------------------------------------------------------------ */
  .table-wrap { overflow-x: auto; }

  /* ------------------------------------------------------------------ */
  /* Uptime bar                                                           */
  /* ------------------------------------------------------------------ */
  .uptime-bar {
    height: 3px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    margin-top: 8px;
  }

  .uptime-fill {
    height: 100%;
    background: var(--green);
    border-radius: 2px;
    transition: width 0.5s ease;
  }

  /* ------------------------------------------------------------------ */
  /* Toast notifications                                                  */
  /* ------------------------------------------------------------------ */
  #toast-container {
    position: fixed;
    bottom: 24px;
    right: 24px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 1000;
  }

  .toast {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 13px;
    color: var(--beige);
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    animation: slideIn 0.2s ease;
    max-width: 320px;
  }

  .toast.success { border-left: 3px solid var(--success); }
  .toast.error   { border-left: 3px solid var(--danger); }

  @keyframes slideIn {
    from { opacity: 0; transform: translateX(20px); }
    to   { opacity: 1; transform: translateX(0); }
  }

  /* ------------------------------------------------------------------ */
  /* Responsive                                                           */
  /* ------------------------------------------------------------------ */
  @media (max-width: 640px) {
    :root { --nav-width: 56px; }
    #content { padding: 16px; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .topbar-time { display: none; }
  }
</style>
</head>
<body>

<!-- ------------------------------------------------------------------ -->
<!-- Login screen                                                         -->
<!-- ------------------------------------------------------------------ -->
<div id="login-screen">
  <div class="login-card">
    <div class="logo">Marcus<span>.</span></div>
    <div class="subtitle">v2 Operations Dashboard</div>
    <input type="password" id="token-input" placeholder="Enter dashboard token" autocomplete="off" />
    <div class="error" id="login-error"></div>
    <button class="btn btn-primary" style="width:100%;justify-content:center;" onclick="handleLogin()">
      Authenticate
    </button>
  </div>
</div>

<!-- ------------------------------------------------------------------ -->
<!-- App shell                                                            -->
<!-- ------------------------------------------------------------------ -->
<div id="app">

  <!-- Sidebar -->
  <nav id="sidebar">
    <div class="sidebar-brand">M</div>

    <button class="nav-btn active" id="nav-overview" onclick="switchView('overview')" title="Overview">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
        <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
      </svg>
      <span class="nav-label">Overview</span>
    </button>

    <button class="nav-btn" id="nav-today" onclick="switchView('today')" title="Today">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
      <span class="nav-label">Today</span>
    </button>

    <button class="nav-btn" id="nav-brain" onclick="switchView('brain')" title="Brain">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2a4 4 0 0 0-4 4 4 4 0 0 0-2 7 4 4 0 0 0 2 7 4 4 0 0 0 8 0 4 4 0 0 0 2-7 4 4 0 0 0-2-7 4 4 0 0 0-4-4z"/>
        <path d="M12 2v20"/>
      </svg>
      <span class="nav-label">Brain</span>
    </button>

    <button class="nav-btn" id="nav-fleet" onclick="switchView('fleet')" title="Fleet">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="2" y="3" width="20" height="6" rx="1"/><rect x="2" y="15" width="20" height="6" rx="1"/>
        <circle cx="6" cy="6" r="0.5" fill="currentColor"/><circle cx="6" cy="18" r="0.5" fill="currentColor"/>
      </svg>
      <span class="nav-label">Fleet</span>
    </button>

    <button class="nav-btn" id="nav-memories" onclick="switchView('memories')" title="Memories">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 12l3-3m0 0l3-3m-3 3l-3-3m3 3l3 3"/>
        <circle cx="19" cy="5" r="3" fill="currentColor" stroke="none"/>
      </svg>
      <span class="nav-label">Memory</span>
    </button>

    <button class="nav-btn" id="nav-conversations" onclick="switchView('conversations')" title="Conversations">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      <span class="nav-label">Calls</span>
    </button>

    <div class="nav-divider"></div>

    <button class="nav-btn" id="nav-tasks" onclick="switchView('tasks')" title="Tasks">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
      </svg>
      <span class="nav-label">Tasks</span>
    </button>

    <button class="nav-btn" id="nav-priorities" onclick="switchView('priorities')" title="Priorities">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>
        <line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>
        <line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>
      </svg>
      <span class="nav-label">Priority</span>
    </button>

    <div class="nav-divider"></div>

    <button class="nav-btn" id="nav-security" onclick="switchView('security')" title="Security">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      <span class="nav-label">Security</span>
    </button>

    <div class="nav-divider"></div>

    <button class="nav-btn" id="nav-gmail" onclick="switchView('gmail')" title="Gmail">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
        <polyline points="22,6 12,13 2,6"/>
      </svg>
      <span class="nav-label">Gmail</span>
    </button>

    <button class="nav-btn" id="nav-calendar" onclick="switchView('calendar')" title="Calendar">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
        <line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>
        <line x1="3" y1="10" x2="21" y2="10"/>
      </svg>
      <span class="nav-label">Calendar</span>
    </button>

    <button class="nav-btn" id="nav-slack" onclick="switchView('slack')" title="Slack">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="13" y="2" width="3" height="8" rx="1.5"/><rect x="8" y="14" width="3" height="8" rx="1.5"/>
        <rect x="2" y="13" width="8" height="3" rx="1.5"/><rect x="14" y="8" width="8" height="3" rx="1.5"/>
      </svg>
      <span class="nav-label">Slack</span>
    </button>

    <button class="nav-btn" id="nav-clickup" onclick="switchView('clickup')" title="ClickUp">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="4 14 12 8 20 14"/><polyline points="4 19 12 13 20 19"/>
      </svg>
      <span class="nav-label">ClickUp</span>
    </button>
  </nav>

  <!-- Main -->
  <div id="main">
    <!-- Top bar -->
    <div id="topbar">
      <div class="topbar-title" id="topbar-title">Overview</div>
      <div class="topbar-right">
        <div id="connection-status">
          <div id="status-dot"></div>
          <span id="status-text">Connecting…</span>
        </div>
        <div class="topbar-time" id="clock"></div>
      </div>
    </div>

    <!-- Content -->
    <div id="content">

      <!-- ====== OVERVIEW ====== -->
      <div id="view-overview" class="view active">
        <div class="stats-grid" id="stats-grid">
          <div class="stat-card accent-terracotta">
            <div class="stat-label">Memories</div>
            <div class="stat-value" id="stat-memories">—</div>
            <div class="stat-sub">total stored</div>
          </div>
          <div class="stat-card accent-green">
            <div class="stat-label">Calls Today</div>
            <div class="stat-value" id="stat-calls">—</div>
            <div class="stat-sub">conversations</div>
          </div>
          <div class="stat-card accent-gold">
            <div class="stat-label">Active Tasks</div>
            <div class="stat-value" id="stat-tasks">—</div>
            <div class="stat-sub">scheduled + queued</div>
          </div>
          <div class="stat-card accent-danger">
            <div class="stat-label">Blocked</div>
            <div class="stat-value" id="stat-blocked">—</div>
            <div class="stat-sub">security events</div>
          </div>
        </div>

        <div class="two-col">
          <div>
            <div class="section-header">
              <div class="section-title">System Health</div>
            </div>
            <div class="card" id="health-card" style="padding:20px;">
              <div class="skeleton" style="width:60%;"></div>
              <div class="skeleton" style="width:40%;"></div>
              <div class="skeleton" style="width:80%;"></div>
            </div>
          </div>

          <div>
            <div class="section-header">
              <div class="section-title">Recent Activity</div>
            </div>
            <div class="card" style="padding:16px 20px;">
              <div class="activity-feed" id="activity-feed">
                <div class="skeleton"></div>
                <div class="skeleton" style="width:80%;"></div>
                <div class="skeleton" style="width:70%;"></div>
                <div class="skeleton"></div>
                <div class="skeleton" style="width:85%;"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ====== MEMORIES ====== -->
      <div id="view-memories" class="view">
        <div class="memory-search">
          <input class="search-input" id="memory-search" placeholder="Search memories…" oninput="filterMemories()" />
          <button class="btn btn-ghost" onclick="loadMemories()">Refresh</button>
        </div>
        <div class="section-header">
          <div class="section-title">Memory Timeline</div>
          <div class="section-count" id="memory-count"></div>
        </div>
        <div class="memory-list" id="memory-list">
          <div class="skeleton"></div>
          <div class="skeleton" style="width:90%;"></div>
          <div class="skeleton" style="width:75%;"></div>
        </div>
      </div>

      <!-- ====== CONVERSATIONS ====== -->
      <div id="view-conversations" class="view">
        <div class="section-header">
          <div class="section-title">Call Log</div>
          <div class="section-count" id="conv-count"></div>
        </div>
        <div class="card">
          <div class="table-wrap">
            <table class="data-table" id="conv-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Caller</th>
                  <th>Duration</th>
                  <th>Summary</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody id="conv-body">
                <tr><td colspan="5"><div class="skeleton"></div></td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ====== TASKS ====== -->
      <div id="view-tasks" class="view">
        <div class="tasks-section">
          <div class="section-header">
            <div class="section-title">Scheduled Tasks</div>
            <div class="section-count" id="task-count"></div>
          </div>
          <div class="card">
            <div class="table-wrap">
              <table class="data-table" id="task-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Schedule</th>
                    <th>Next Run</th>
                    <th>Last Run</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody id="task-body">
                  <tr><td colspan="5"><div class="skeleton"></div></td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="tasks-section">
          <div class="section-header">
            <div class="section-title">Missions Queue</div>
            <div class="section-count" id="mission-count"></div>
          </div>
          <div class="card">
            <div class="table-wrap">
              <table class="data-table" id="mission-table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Priority</th>
                    <th>Agent</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody id="mission-body">
                  <tr><td colspan="5"><div class="skeleton"></div></td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- ====== PRIORITIES ====== -->
      <div id="view-priorities" class="view">
        <div class="section-header">
          <div class="section-title">Active Priorities</div>
          <div class="section-count" id="priority-count"></div>
        </div>
        <div id="priority-banner" class="priority-banner"></div>
        <div id="priority-groups"></div>
      </div>

      <!-- ====== SECURITY ====== -->
      <div id="view-security" class="view">
        <div class="audit-filters" id="audit-filters">
          <button class="filter-btn active" onclick="setAuditFilter(null, this)">All</button>
          <button class="filter-btn" onclick="setAuditFilter('message', this)">message</button>
          <button class="filter-btn" onclick="setAuditFilter('command', this)">command</button>
          <button class="filter-btn" onclick="setAuditFilter('tool_call', this)">tool_call</button>
          <button class="filter-btn" onclick="setAuditFilter('blocked', this)">blocked</button>
          <button class="filter-btn" onclick="setAuditFilter('exfil_attempt', this)">exfil</button>
        </div>
        <div class="section-header">
          <div class="section-title">Audit Log</div>
          <div class="section-count" id="audit-count"></div>
        </div>
        <div class="card">
          <div class="table-wrap">
            <table class="data-table" id="audit-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Agent</th>
                  <th>Action</th>
                  <th>Detail</th>
                  <th>Blocked</th>
                </tr>
              </thead>
              <tbody id="audit-body">
                <tr><td colspan="5"><div class="skeleton"></div></td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ====== TODAY ====== -->
      <div id="view-today" class="view">
        <div class="integ-grid">
          <div class="integ-card" id="today-gmail">
            <div class="integ-head">
              <div class="integ-title">Gmail <span class="integ-pill" id="today-gmail-pill">—</span></div>
              <a href="#" onclick="switchView('gmail');return false;" style="color:var(--muted);font-size:11px;text-decoration:none;">open →</a>
            </div>
            <div class="integ-list" id="today-gmail-list"><div class="skeleton"></div></div>
          </div>
          <div class="integ-card" id="today-calendar">
            <div class="integ-head">
              <div class="integ-title">Calendar <span class="integ-pill" id="today-cal-pill">—</span></div>
              <a href="#" onclick="switchView('calendar');return false;" style="color:var(--muted);font-size:11px;text-decoration:none;">open →</a>
            </div>
            <div class="integ-list" id="today-cal-list"><div class="skeleton"></div></div>
          </div>
          <div class="integ-card" id="today-slack">
            <div class="integ-head">
              <div class="integ-title">Slack <span class="integ-pill" id="today-slack-pill">—</span></div>
              <a href="#" onclick="switchView('slack');return false;" style="color:var(--muted);font-size:11px;text-decoration:none;">open →</a>
            </div>
            <div class="integ-list" id="today-slack-list"><div class="skeleton"></div></div>
          </div>
          <div class="integ-card" id="today-clickup">
            <div class="integ-head">
              <div class="integ-title">ClickUp <span class="integ-pill" id="today-cu-pill">—</span></div>
              <a href="#" onclick="switchView('clickup');return false;" style="color:var(--muted);font-size:11px;text-decoration:none;">open →</a>
            </div>
            <div class="integ-list" id="today-cu-list"><div class="skeleton"></div></div>
          </div>
        </div>
      </div>

      <!-- ====== BRAIN ====== -->
      <div id="view-brain" class="view">
        <div class="stats-grid" style="grid-template-columns:repeat(4,1fr);">
          <div class="stat-card accent-terracotta"><div class="stat-label">Pages</div><div class="stat-value" id="brain-pages">—</div><div class="stat-sub">in the brain</div></div>
          <div class="stat-card accent-green"><div class="stat-label">Embedded</div><div class="stat-value" id="brain-embed">—</div><div class="stat-sub">coverage</div></div>
          <div class="stat-card accent-gold"><div class="stat-label">Chunks</div><div class="stat-value" id="brain-chunks">—</div><div class="stat-sub">indexed</div></div>
          <div class="stat-card accent-beige"><div class="stat-label">Embedder</div><div class="stat-value" id="brain-provider" style="font-size:14px;">—</div><div class="stat-sub">local / free</div></div>
        </div>
        <div class="card" style="padding:18px;margin-top:8px;">
          <div style="display:flex;gap:10px;align-items:center;">
            <input id="brain-q" placeholder="Ask the brain… (e.g. what is open across active clients?)"
              style="flex:1;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--white);font-size:14px;padding:11px 14px;outline:none;"
              onkeydown="if(event.key==='Enter')brainThink()" />
            <button class="btn btn-primary" onclick="brainThink()" id="brain-think-btn">Think</button>
            <button class="btn" style="border:1px solid var(--border);background:var(--card);color:var(--beige);" onclick="brainSearch()">Search</button>
          </div>
          <div style="font-size:11px;color:var(--muted);margin-top:8px;">Think = synthesized answer + gap analysis (slower). Search = raw page hits (fast).</div>
        </div>
        <div id="brain-result" style="margin-top:16px;"></div>
      </div>

      <!-- ====== FLEET ====== -->
      <div id="view-fleet" class="view">
        <div class="section-header"><div class="section-title">Fleet Health</div><div class="section-count" id="fleet-count"></div></div>
        <div class="integ-grid" id="fleet-grid"><div class="skeleton"></div></div>
        <div class="callout" style="margin-top:18px;border-left:3px solid var(--green-lt);background:rgba(77,117,110,0.10);padding:14px 18px;border-radius:0 10px 10px 0;">
          <div style="color:var(--white);font-weight:600;margin-bottom:4px;">One brain, many clients</div>
          <div style="font-size:13px;color:var(--muted);">The brain lives only on the M4 hub. Every other machine is a thin client reading/writing it over Tailscale. "online" = reachable on the tailnet; "on brain" = holds a live DB connection right now.</div>
        </div>
      </div>

      <!-- ====== GMAIL ====== -->
      <div id="view-gmail" class="view">
        <div class="section-header">
          <div class="section-title">Unread Inbox</div>
          <div class="section-count" id="gmail-count"></div>
        </div>
        <div class="card" style="padding:16px;">
          <div class="integ-list" id="gmail-list"><div class="skeleton"></div></div>
        </div>
      </div>

      <!-- ====== CALENDAR ====== -->
      <div id="view-calendar" class="view">
        <div class="section-header">
          <div class="section-title">Today's Schedule</div>
          <div class="section-count" id="cal-count"></div>
        </div>
        <div class="card" style="padding:16px;">
          <div class="integ-list" id="cal-list"><div class="skeleton"></div></div>
        </div>
      </div>

      <!-- ====== SLACK ====== -->
      <div id="view-slack" class="view">
        <div class="section-header">
          <div class="section-title">Channels &amp; DMs</div>
          <div class="section-count" id="slack-count"></div>
        </div>
        <div class="card" style="padding:16px;">
          <div class="integ-list" id="slack-list"><div class="skeleton"></div></div>
        </div>
      </div>

      <!-- ====== CLICKUP ====== -->
      <div id="view-clickup" class="view">
        <div class="section-header">
          <div class="section-title">Open Tasks</div>
          <div class="section-count" id="cu-count"></div>
        </div>
        <div class="card" style="padding:16px;">
          <div class="integ-list" id="cu-list"><div class="skeleton"></div></div>
        </div>
      </div>

    </div><!-- /content -->
  </div><!-- /main -->
</div><!-- /app -->

<div id="toast-container"></div>

<script>
// ============================================================
// State
// ============================================================
let TOKEN = '';
let currentView = 'overview';
let refreshInterval = null;
let sseSource = null;
let allMemories = [];
let auditFilter = null;

// ============================================================
// Init
// ============================================================
(function init() {
  TOKEN = localStorage.getItem('marcus_dashboard_token') || '';
  if (TOKEN) {
    verifyToken().then(ok => {
      if (ok) showApp();
    });
  }

  // Allow Enter key on login input
  document.getElementById('token-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') handleLogin();
  });

  // Clock
  updateClock();
  setInterval(updateClock, 1000);
})();

function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent = now.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  });
}

// ============================================================
// Auth
// ============================================================
async function handleLogin() {
  const input = document.getElementById('token-input');
  const err = document.getElementById('login-error');
  const candidate = input.value.trim();

  if (!candidate) { err.textContent = 'Token required.'; return; }

  TOKEN = candidate;
  err.textContent = '';

  const ok = await verifyToken();
  if (ok) {
    localStorage.setItem('marcus_dashboard_token', TOKEN);
    showApp();
  } else {
    err.textContent = 'Invalid token.';
    TOKEN = '';
  }
}

async function verifyToken() {
  try {
    const res = await apiFetch('/api/health');
    return res.ok;
  } catch {
    return false;
  }
}

function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app').classList.add('visible');
  startRefresh();
  connectSSE();
  loadView(currentView);
}

// ============================================================
// API helpers
// ============================================================
async function apiFetch(path, params = {}) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set('token', TOKEN);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null) url.searchParams.set(k, v);
  });

  const res = await fetch(url.toString(), {
    headers: { 'Authorization': 'Bearer ' + TOKEN }
  });

  if (res.status === 401) {
    localStorage.removeItem('marcus_dashboard_token');
    location.reload();
    throw new Error('Unauthorized');
  }

  return res;
}

async function apiGet(path, params = {}) {
  const res = await apiFetch(path, params);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ============================================================
// SSE
// ============================================================
function connectSSE() {
  if (sseSource) sseSource.close();

  const url = new URL('/api/events', window.location.origin);
  url.searchParams.set('token', TOKEN);

  sseSource = new EventSource(url.toString());

  sseSource.onopen = () => setStatus('connected', 'Connected');

  sseSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'heartbeat') return;
      if (data.type === 'refresh') loadView(currentView);
    } catch {}
  };

  sseSource.onerror = () => {
    setStatus('error', 'Disconnected');
    // Retry after 5s
    setTimeout(() => connectSSE(), 5000);
  };
}

function setStatus(cls, text) {
  const dot = document.getElementById('status-dot');
  const label = document.getElementById('status-text');
  dot.className = cls;
  label.textContent = text;
}

// ============================================================
// Auto-refresh
// ============================================================
function startRefresh() {
  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(() => loadView(currentView), 30_000);
}

// ============================================================
// Navigation
// ============================================================
const VIEW_TITLES = {
  overview: 'Overview',
  today: 'Today',
  brain: 'Brain',
  fleet: 'Fleet Health',
  memories: 'Memories',
  conversations: 'Conversations',
  tasks: 'Tasks',
  priorities: 'Priorities',
  security: 'Security Audit',
  gmail: 'Gmail',
  calendar: 'Calendar',
  slack: 'Slack',
  clickup: 'ClickUp',
};

function switchView(name) {
  // Update nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
  document.getElementById('nav-' + name)?.classList.add('active');

  // Update views
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name)?.classList.add('active');

  // Update topbar
  document.getElementById('topbar-title').textContent = VIEW_TITLES[name] || name;

  currentView = name;
  loadView(name);
}

function loadView(name) {
  switch (name) {
    case 'overview':      loadOverview(); break;
    case 'today':         loadToday(); break;
    case 'brain':         loadBrain(); break;
    case 'fleet':         loadFleet(); break;
    case 'memories':      loadMemories(); break;
    case 'conversations': loadConversations(); break;
    case 'tasks':         loadTasks(); break;
    case 'priorities':    loadPriorities(); break;
    case 'security':      loadSecurity(); break;
    case 'gmail':         loadGmail(); break;
    case 'calendar':      loadCalendar(); break;
    case 'slack':         loadSlack(); break;
    case 'clickup':       loadClickup(); break;
  }
}

// ============================================================
// Overview
// ============================================================
async function loadOverview() {
  try {
    const [stats, health, audit] = await Promise.all([
      apiGet('/api/stats'),
      apiGet('/api/health'),
      apiGet('/api/audit', { limit: 8 }),
    ]);

    // Stats cards
    document.getElementById('stat-memories').textContent = (stats.totalMemories ?? '—').toLocaleString();
    document.getElementById('stat-calls').textContent = (stats.conversationsToday ?? '—').toLocaleString();
    document.getElementById('stat-tasks').textContent = (stats.activeTasks ?? '—').toLocaleString();
    document.getElementById('stat-blocked').textContent = (stats.blockedAttempts ?? '0').toLocaleString();

    // Health card
    const hc = document.getElementById('health-card');
    const uptimeH = Math.floor((health.uptimeSeconds || 0) / 3600);
    const uptimeM = Math.floor(((health.uptimeSeconds || 0) % 3600) / 60);
    const uptimePct = Math.min(100, ((health.uptimeSeconds || 0) / (24 * 3600)) * 100);

    hc.innerHTML = \`
      <div style="display:flex;justify-content:space-between;margin-bottom:16px;">
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:4px;">Version</div>
          <div style="font-size:18px;font-weight:700;color:var(--white);font-family:var(--mono);">v\${health.version || '2.0.0'}</div>
        </div>
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:4px;">Uptime</div>
          <div style="font-size:18px;font-weight:700;color:var(--white);font-family:var(--mono);">\${uptimeH}h \${uptimeM}m</div>
        </div>
        <div>
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:4px;">Sessions</div>
          <div style="font-size:18px;font-weight:700;color:var(--white);font-family:var(--mono);">\${health.activeSessions ?? 0}</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:6px;">24h uptime progress</div>
      <div class="uptime-bar">
        <div class="uptime-fill" style="width:\${uptimePct.toFixed(1)}%"></div>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:8px;">
        <span style="font-size:11px;color:var(--muted);">Memory: \${health.memoryStats?.totalMemories ?? stats.totalMemories ?? '—'}</span>
        <span style="font-size:11px;color:var(--success);">●&nbsp;Online</span>
      </div>
    \`;

    // Activity feed from audit log
    const feed = document.getElementById('activity-feed');
    if (!audit || audit.length === 0) {
      feed.innerHTML = '<div class="empty-state"><div class="empty-text">No recent activity</div></div>';
      return;
    }

    feed.innerHTML = audit.map(row => {
      const dotColor = row.blocked ? 'var(--danger)' : row.action === 'exfil_attempt' ? 'var(--gold)' : 'var(--green)';
      return \`
        <div class="activity-item">
          <div class="activity-dot" style="background:\${dotColor}"></div>
          <div class="activity-text">
            <strong style="color:var(--white)">\${row.action}</strong>
            \${row.detail ? \` — \${truncate(row.detail, 80)}\` : ''}
          </div>
          <div class="activity-time">\${timeAgo(row.created_at)}</div>
        </div>
      \`;
    }).join('');

    setStatus('connected', 'Connected');
  } catch (err) {
    setStatus('error', 'Error');
    showToast('Failed to load overview: ' + err.message, 'error');
  }
}

// ============================================================
// Memories
// ============================================================
async function loadMemories() {
  const list = document.getElementById('memory-list');
  const search = document.getElementById('memory-search').value.trim();

  try {
    const params = { limit: 100 };
    if (search) params.search = search;
    const data = await apiGet('/api/memories', params);
    allMemories = data || [];
    renderMemories(allMemories);
  } catch (err) {
    list.innerHTML = \`<div class="empty-state"><div class="empty-text">Failed to load memories</div></div>\`;
    showToast('Memories error: ' + err.message, 'error');
  }
}

function filterMemories() {
  const q = document.getElementById('memory-search').value.toLowerCase().trim();
  if (!q) { renderMemories(allMemories); return; }

  const filtered = allMemories.filter(m => {
    const summary = (m.summary || '').toLowerCase();
    const entities = (m.entities || []).join(' ').toLowerCase();
    const topics = (m.topics || []).join(' ').toLowerCase();
    return summary.includes(q) || entities.includes(q) || topics.includes(q);
  });
  renderMemories(filtered);
}

function renderMemories(memories) {
  const list = document.getElementById('memory-list');
  const count = document.getElementById('memory-count');
  count.textContent = memories.length + ' records';

  if (!memories.length) {
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">🧠</div><div class="empty-text">No memories found</div></div>';
    return;
  }

  list.innerHTML = memories.map((m, i) => {
    const salience = m.salience ?? m.importance ?? 0;
    const barColor = salientColor(salience);
    const entities = (m.entities || []).slice(0, 5);
    const topics = (m.topics || []).slice(0, 3);

    return \`
      <div class="memory-item" id="mem-\${i}" onclick="toggleMemory(\${i})">
        <div class="memory-header">
          <div class="memory-salience-bar" style="background:\${barColor}"></div>
          <div class="memory-body">
            <div class="memory-summary">\${esc(m.summary || '')}</div>
            <div class="memory-meta">
              <span class="memory-salience-text">salience \${salience.toFixed(2)}</span>
              \${entities.map(e => \`<span class="entity-tag">\${esc(e)}</span>\`).join('')}
              \${topics.map(t => \`<span class="badge badge-muted">\${esc(t)}</span>\`).join('')}
              <span style="font-size:11px;color:var(--muted);margin-left:auto;">\${timeAgo(m.created_at)}</span>
            </div>
            <div class="memory-detail">
              \${m.importance !== undefined ? \`<div class="memory-detail-row"><span class="memory-detail-label">Importance</span><span class="memory-detail-value">\${m.importance?.toFixed(3)}</span></div>\` : ''}
              \${m.id ? \`<div class="memory-detail-row"><span class="memory-detail-label">ID</span><span class="memory-detail-value">\${m.id}</span></div>\` : ''}
              \${m.agent_id ? \`<div class="memory-detail-row"><span class="memory-detail-label">Agent</span><span class="memory-detail-value">\${m.agent_id}</span></div>\` : ''}
              \${m.created_at ? \`<div class="memory-detail-row"><span class="memory-detail-label">Stored</span><span class="memory-detail-value">\${new Date(m.created_at).toLocaleString()}</span></div>\` : ''}
              \${m.superseded_by ? \`<div class="memory-detail-row"><span class="memory-detail-label">Superseded</span><span class="memory-detail-value">\${m.superseded_by}</span></div>\` : ''}
              \${(m.entities||[]).length ? \`<div class="memory-detail-row"><span class="memory-detail-label">Entities</span><span class="memory-detail-value">\${m.entities.join(', ')}</span></div>\` : ''}
            </div>
          </div>
        </div>
      </div>
    \`;
  }).join('');
}

function toggleMemory(i) {
  const el = document.getElementById('mem-' + i);
  el?.classList.toggle('expanded');
}

function salientColor(s) {
  if (s >= 0.8) return 'var(--terracotta)';
  if (s >= 0.6) return 'var(--gold)';
  if (s >= 0.4) return 'var(--green)';
  if (s >= 0.2) return 'var(--muted)';
  return 'var(--border)';
}

// ============================================================
// Conversations
// ============================================================
async function loadConversations() {
  const body = document.getElementById('conv-body');
  try {
    const data = await apiGet('/api/conversations', { limit: 50 });
    const rows = data || [];
    document.getElementById('conv-count').textContent = rows.length + ' records';

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">📞</div><div class="empty-text">No conversations yet</div></div></td></tr>';
      return;
    }

    body.innerHTML = rows.map(r => {
      const duration = r.duration_seconds
        ? \`\${Math.floor(r.duration_seconds / 60)}m \${r.duration_seconds % 60}s\`
        : '—';
      const hasEnded = r.ended_at || r.duration_seconds;
      const statusBadge = hasEnded
        ? '<span class="badge badge-green">ended</span>'
        : '<span class="badge badge-gold">active</span>';

      return \`
        <tr>
          <td class="mono">\${timeAgo(r.started_at || r.created_at)}</td>
          <td class="mono">\${esc(r.caller_number || '—')}</td>
          <td class="mono">\${duration}</td>
          <td style="max-width:320px;">\${esc(truncate(r.summary || '—', 100))}</td>
          <td>\${statusBadge}</td>
        </tr>
      \`;
    }).join('');
  } catch (err) {
    body.innerHTML = '<tr><td colspan="5" style="color:var(--danger)">Failed to load</td></tr>';
    showToast('Conversations error: ' + err.message, 'error');
  }
}

// ============================================================
// Tasks
// ============================================================
async function loadTasks() {
  try {
    const data = await apiGet('/api/tasks');
    const tasks = data.scheduledTasks || [];
    const missions = data.missions || [];

    document.getElementById('task-count').textContent = tasks.length + ' tasks';
    document.getElementById('mission-count').textContent = missions.length + ' missions';

    // Scheduled tasks
    const taskBody = document.getElementById('task-body');
    if (!tasks.length) {
      taskBody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="empty-text">No scheduled tasks</div></div></td></tr>';
    } else {
      taskBody.innerHTML = tasks.map(t => {
        const statusBadge = statusBadgeFor(t.status);
        return \`
          <tr>
            <td>\${esc(t.name || t.id || '—')}</td>
            <td class="mono">\${esc(t.schedule || '—')}</td>
            <td class="mono">\${t.next_run ? timeAgo(t.next_run) : '—'}</td>
            <td class="mono">\${t.last_run ? timeAgo(t.last_run) : 'never'}</td>
            <td>\${statusBadge}</td>
          </tr>
        \`;
      }).join('');
    }

    // Missions
    const missionBody = document.getElementById('mission-body');
    if (!missions.length) {
      missionBody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="empty-text">No missions queued</div></div></td></tr>';
    } else {
      missionBody.innerHTML = missions.map(m => {
        const pri = m.priority || 3;
        const priColor = pri <= 1 ? 'var(--danger)' : pri <= 2 ? 'var(--gold)' : 'var(--muted)';
        return \`
          <tr>
            <td>\${esc(m.title || '—')}</td>
            <td><span style="color:\${priColor};font-weight:700;font-family:var(--mono);">P\${pri}</span></td>
            <td class="mono">\${esc(m.assigned_agent || 'marcus')}</td>
            <td>\${statusBadgeFor(m.status)}</td>
            <td class="mono">\${timeAgo(m.created_at)}</td>
          </tr>
        \`;
      }).join('');
    }
  } catch (err) {
    showToast('Tasks error: ' + err.message, 'error');
  }
}

function statusBadgeFor(status) {
  const map = {
    active:    '<span class="badge badge-green">active</span>',
    running:   '<span class="badge badge-terra">running</span>',
    queued:    '<span class="badge badge-gold">queued</span>',
    completed: '<span class="badge badge-green">done</span>',
    failed:    '<span class="badge badge-red">failed</span>',
    disabled:  '<span class="badge badge-muted">disabled</span>',
    cancelled: '<span class="badge badge-muted">cancelled</span>',
  };
  return map[status] || \`<span class="badge badge-muted">\${esc(status || '—')}</span>\`;
}

// ============================================================
// Priorities
// ============================================================
// Buckets shown top-to-bottom. now = overdue/today, week = next 7 days,
// upcoming = later/undated, done = recently completed.
const PRIORITY_BUCKETS = [
  { key: 'now',      label: 'Now / Overdue' },
  { key: 'week',     label: 'This Week' },
  { key: 'upcoming', label: 'Upcoming' },
  { key: 'done',     label: 'Recently Done' },
];

function dueChip(dueMs) {
  if (dueMs == null) return '';
  const now = Date.now();
  const dayMs = 86400000;
  const diff = dueMs - now;
  if (diff < 0) {
    const d = Math.ceil(-diff / dayMs);
    return \`<span class="pri-badge overdue">overdue \${d}d</span>\`;
  }
  const todayEnd = new Date(); todayEnd.setHours(23, 59, 59, 999);
  if (dueMs <= todayEnd.getTime()) return '<span class="pri-badge due">due today</span>';
  const d = Math.ceil(diff / dayMs);
  return \`<span class="pri-badge due">due \${d}d</span>\`;
}

async function loadPriorities() {
  const container = document.getElementById('priority-groups');
  const banner = document.getElementById('priority-banner');
  try {
    const data = await apiGet('/api/priorities');
    const priorities = (data && data.priorities) || [];
    const open = priorities.filter(p => p.bucket !== 'done');
    document.getElementById('priority-count').textContent = open.length + ' open';

    // Banner: when Hermes last dreamed + live ClickUp health.
    const bits = [];
    if (data && data.lastDreamedAt) bits.push('🌙 dreamed ' + timeAgo(data.lastDreamedAt));
    else bits.push('🌙 no dream yet');
    if (data && data.clickupOk === false) bits.push('<span class="warn">⚠ ClickUp offline</span>');
    else bits.push('🔄 ClickUp live');
    banner.innerHTML = bits.join(' · ');

    if (!priorities.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">🎯</div><div class="empty-text">No active priorities. Hermes has not written a dream yet and ClickUp has no open tasks.</div></div>';
      return;
    }

    const grouped = {};
    for (const p of priorities) {
      const b = p.bucket || 'upcoming';
      (grouped[b] = grouped[b] || []).push(p);
    }

    container.innerHTML = PRIORITY_BUCKETS
      .filter(b => grouped[b.key]?.length)
      .map(b => {
        const items = grouped[b.key];
        return \`
          <div class="priority-group">
            <div class="priority-group-label">\${b.label} <span style="color:var(--muted);font-weight:400">(\${items.length})</span></div>
            \${items.map(p => {
              const isComplete = p.bucket === 'done';
              const isOverdue = !isComplete && p.due != null && p.due < Date.now();
              const text = esc(p.text || '—');
              const textHtml = p.url
                ? \`<a href="\${esc(p.url)}" target="_blank" rel="noopener">\${text}</a>\`
                : text;
              const badges = [];
              if (p.source === 'brain') badges.push('<span class="pri-badge brain">brain</span>');
              else if (p.source === 'clickup') badges.push('<span class="pri-badge clickup">clickup</span>');
              const due = dueChip(p.due);
              if (due) badges.push(due);
              return \`
                <div class="priority-item \${isComplete ? 'completed' : ''} \${isOverdue ? 'overdue' : ''}">
                  <div class="priority-check">
                    \${isComplete ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>' : ''}
                  </div>
                  <div class="priority-content">
                    <div class="priority-text">\${textHtml}</div>
                    \${p.rationale ? \`<div class="pri-rationale">\${esc(p.rationale)}</div>\` : ''}
                    <div class="pri-badges">
                      \${badges.join('')}
                      \${p.owner ? \`<span class="pri-badge">\${esc(p.owner)}</span>\` : ''}
                    </div>
                  </div>
                </div>
              \`;
            }).join('')}
          </div>
        \`;
      }).join('');
  } catch (err) {
    container.innerHTML = '<div class="empty-state"><div class="empty-text">Failed to load priorities</div></div>';
    showToast('Priorities error: ' + err.message, 'error');
  }
}

// ============================================================
// Security / Audit
// ============================================================
async function loadSecurity() {
  const body = document.getElementById('audit-body');
  try {
    const params = { limit: 100 };
    if (auditFilter === 'blocked') {
      params.blocked = 'true';
    } else if (auditFilter) {
      params.action = auditFilter;
    }

    const data = await apiGet('/api/audit', params);
    const rows = data || [];
    document.getElementById('audit-count').textContent = rows.length + ' events';

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">🔒</div><div class="empty-text">No audit events</div></div></td></tr>';
      return;
    }

    body.innerHTML = rows.map(r => {
      const isExfil = r.action === 'exfil_attempt';
      const rowClass = isExfil ? 'audit-exfil' : r.blocked ? 'audit-blocked' : '';
      return \`
        <tr class="\${rowClass}">
          <td class="mono">\${timeAgo(r.created_at)}</td>
          <td class="mono">\${esc(r.agent_id || 'marcus')}</td>
          <td>
            <span class="badge \${isExfil ? 'badge-red' : r.blocked ? 'badge-gold' : 'badge-beige'}">
              \${esc(r.action || '—')}
            </span>
          </td>
          <td style="max-width:400px;word-break:break-word;">\${esc(truncate(r.detail || '—', 120))}</td>
          <td>
            \${r.blocked
              ? '<span class="badge badge-red">yes</span>'
              : '<span class="badge badge-muted">no</span>'}
          </td>
        </tr>
      \`;
    }).join('');
  } catch (err) {
    body.innerHTML = '<tr><td colspan="5" style="color:var(--danger)">Failed to load audit log</td></tr>';
    showToast('Audit error: ' + err.message, 'error');
  }
}

function setAuditFilter(action, btn) {
  auditFilter = action;
  document.querySelectorAll('#audit-filters .filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  loadSecurity();
}

// ============================================================
// Integrations: Today / Gmail / Calendar / Slack / ClickUp
// ============================================================
function renderError(target, msg) {
  document.getElementById(target).innerHTML =
    \`<div class="integ-error">Not available: \${esc(msg || 'unknown error')}</div>\`;
}

function pillClass(n, { urgentAt = 1, warnAt = 1 } = {}) {
  if (!n) return '';
  if (n >= urgentAt && urgentAt <= warnAt) return 'urgent';
  if (n >= warnAt) return 'warn';
  return 'ok';
}

function fmtTime(ms) {
  if (!ms) return '';
  return new Date(ms).toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', hour12: true,
  });
}

function fmtEventRange(ev) {
  if (ev.allDay) return 'All day';
  const s = ev.start ? new Date(ev.start) : null;
  const e = ev.end ? new Date(ev.end) : null;
  if (!s) return '';
  const startStr = s.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  if (!e) return startStr;
  const endStr = e.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  return \`\${startStr} – \${endStr}\`;
}

function fmtDue(ms) {
  if (!ms) return 'no due date';
  const now = Date.now();
  const diff = ms - now;
  const days = Math.round(diff / (24 * 3600 * 1000));
  if (diff < 0) {
    const absDays = Math.abs(days);
    if (absDays === 0) return 'overdue today';
    return \`overdue \${absDays}d\`;
  }
  if (days === 0) return 'due today';
  if (days === 1) return 'due tomorrow';
  if (days < 7) return \`due in \${days}d\`;
  return 'due ' + new Date(ms).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// --------- Today (combined) ---------
async function loadToday() {
  try {
    const data = await apiGet('/api/integrations/today');
    renderTodayGmail(data.gmail);
    renderTodayCalendar(data.calendar);
    renderTodaySlack(data.slack);
    renderTodayClickup(data.clickup);
  } catch (err) {
    showToast('Today error: ' + err.message, 'error');
  }
}

function renderTodayGmail(res) {
  const pill = document.getElementById('today-gmail-pill');
  if (!res.ok) {
    pill.textContent = 'error';
    pill.className = 'integ-pill urgent';
    renderError('today-gmail-list', res.error);
    return;
  }
  const { unreadCount, recent } = res.data;
  pill.textContent = unreadCount + ' unread';
  pill.className = 'integ-pill ' + (unreadCount > 10 ? 'urgent' : unreadCount > 0 ? 'warn' : 'ok');

  const list = document.getElementById('today-gmail-list');
  if (!recent?.length) {
    list.innerHTML = '<div class="integ-error">Inbox zero ✓</div>';
    return;
  }
  list.innerHTML = recent.slice(0, 5).map(m => \`
    <div class="integ-row">
      <div class="body">
        <div class="primary">\${esc(m.subject || '(no subject)')}</div>
        <div class="secondary">\${esc(truncate(m.from, 50))}</div>
      </div>
      <div class="right">\${m.internalDate ? timeAgo(new Date(m.internalDate).toISOString()) : ''}</div>
    </div>
  \`).join('');
}

function renderTodayCalendar(res) {
  const pill = document.getElementById('today-cal-pill');
  if (!res.ok) {
    pill.textContent = 'error';
    pill.className = 'integ-pill urgent';
    renderError('today-cal-list', res.error);
    return;
  }
  const { events, count } = res.data;
  pill.textContent = count + ' today';
  pill.className = 'integ-pill ' + (count > 0 ? 'warn' : 'ok');

  const list = document.getElementById('today-cal-list');
  if (!events?.length) {
    list.innerHTML = '<div class="integ-error">No events today</div>';
    return;
  }
  const now = Date.now();
  list.innerHTML = events.slice(0, 5).map(ev => {
    const startMs = ev.start ? new Date(ev.start).getTime() : null;
    const isNext = startMs && startMs > now;
    return \`
      <div class="integ-row">
        <div class="body">
          <div class="primary">\${esc(ev.summary)}</div>
          <div class="secondary">\${fmtEventRange(ev)}\${ev.location ? ' · ' + esc(truncate(ev.location, 30)) : ''}</div>
        </div>
        <div class="right">\${isNext ? 'in ' + Math.round((startMs - now) / 60000) + 'm' : 'past'}</div>
      </div>
    \`;
  }).join('');
}

function renderTodaySlack(res) {
  const pill = document.getElementById('today-slack-pill');
  if (!res.ok) {
    pill.textContent = 'error';
    pill.className = 'integ-pill urgent';
    renderError('today-slack-list', res.error);
    return;
  }
  const { unreadCount, activeCount, channels } = res.data;
  const ac = activeCount ?? channels.length;
  pill.textContent = unreadCount > 0 ? unreadCount + ' unread' : ac + ' active';
  pill.className = 'integ-pill ' + (unreadCount > 0 ? 'warn' : 'ok');

  const list = document.getElementById('today-slack-list');
  const withUnread = channels.filter(c => c.unread > 0).slice(0, 5);
  const recent = withUnread.length ? withUnread : channels.slice(0, 5);

  if (!recent.length) {
    list.innerHTML = '<div class="integ-error">All caught up</div>';
    return;
  }
  list.innerHTML = recent.map(c => {
    const typeBadge = c.type === 'dm' ? '@' : c.type === 'private' ? '🔒' : '#';
    return \`
      <div class="integ-row">
        <div class="body">
          <div class="primary">\${typeBadge}\${esc(c.name)}</div>
          <div class="secondary">\${c.unread ? c.unread + ' unread · ' : ''}\${c.lastActivity ? timeAgo(new Date(c.lastActivity).toISOString()) : 'no recent activity'}</div>
        </div>
        <div class="right">\${c.unread || ''}</div>
      </div>
    \`;
  }).join('');
}

function renderTodayClickup(res) {
  const pill = document.getElementById('today-cu-pill');
  if (!res.ok) {
    pill.textContent = 'error';
    pill.className = 'integ-pill urgent';
    renderError('today-cu-list', res.error);
    return;
  }
  const { openCount, overdue, dueThisWeek, tasks } = res.data;
  pill.textContent = \`\${overdue} overdue · \${dueThisWeek} this week\`;
  pill.className = 'integ-pill ' + (overdue > 0 ? 'urgent' : dueThisWeek > 0 ? 'warn' : 'ok');

  const list = document.getElementById('today-cu-list');
  if (!tasks?.length) {
    list.innerHTML = '<div class="integ-error">No open tasks</div>';
    return;
  }
  list.innerHTML = tasks.slice(0, 5).map(t => \`
    <div class="integ-row">
      <div class="body">
        <div class="primary"><a href="\${esc(t.url)}" target="_blank" rel="noopener">\${esc(t.name)}</a></div>
        <div class="secondary">\${esc(t.list)}\${t.priority ? ' · ' + esc(t.priority) : ''}</div>
      </div>
      <div class="right" style="color:\${t.due && t.due < Date.now() ? 'var(--danger)' : 'var(--muted)'}">\${fmtDue(t.due)}</div>
    </div>
  \`).join('');
}

// --------- Brain (gBrain knowledge plane) ---------
async function loadBrain() {
  try {
    const res = await apiGet('/api/brain/stats');
    if (res.ok) {
      const d = res.data;
      document.getElementById('brain-pages').textContent = (d.pages ?? 0).toLocaleString();
      document.getElementById('brain-embed').textContent = d.embedCoverage != null ? d.embedCoverage + '%' : '—';
      document.getElementById('brain-chunks').textContent = (d.chunks ?? 0).toLocaleString();
      document.getElementById('brain-provider').textContent = d.provider || '—';
    }
  } catch (err) { showToast('Brain stats error: ' + err.message, 'error'); }
}

async function brainThink() {
  const q = document.getElementById('brain-q').value.trim();
  if (!q) return;
  const out = document.getElementById('brain-result');
  const btn = document.getElementById('brain-think-btn');
  btn.textContent = 'Thinking…'; btn.disabled = true;
  out.innerHTML = '<div class="card" style="padding:20px;"><div class="skeleton"></div><div class="skeleton" style="width:80%;"></div><div class="skeleton" style="width:60%;"></div></div>';
  try {
    const res = await apiGet('/api/brain/think', { q });
    if (!res.ok) { out.innerHTML = \`<div class="integ-error">\${esc(res.error)}</div>\`; return; }
    out.innerHTML = \`<div class="card" style="padding:22px;line-height:1.7;white-space:pre-wrap;color:var(--beige);">\${esc(res.data.answer || 'No answer.')}</div>\`;
  } catch (err) {
    out.innerHTML = \`<div class="integ-error">Think failed: \${esc(err.message)}</div>\`;
  } finally { btn.textContent = 'Think'; btn.disabled = false; }
}

async function brainSearch() {
  const q = document.getElementById('brain-q').value.trim();
  if (!q) return;
  const out = document.getElementById('brain-result');
  out.innerHTML = '<div class="card" style="padding:16px;"><div class="skeleton"></div></div>';
  try {
    const res = await apiGet('/api/brain/search', { q });
    if (!res.ok) { out.innerHTML = \`<div class="integ-error">\${esc(res.error)}</div>\`; return; }
    const rows = res.data.results || [];
    if (!rows.length) { out.innerHTML = '<div class="integ-error">No matching pages.</div>'; return; }
    out.innerHTML = '<div class="card" style="padding:16px;"><div class="integ-list">' + rows.map(r => \`
      <div class="integ-row">
        <div class="body">
          <div class="primary">\${esc(r.title)}</div>
          <div class="secondary">\${esc(r.slug)}</div>
        </div>
        <div class="right">\${r.score.toFixed(3)}</div>
      </div>\`).join('') + '</div></div>';
  } catch (err) {
    out.innerHTML = \`<div class="integ-error">Search failed: \${esc(err.message)}</div>\`;
  }
}

// --------- Fleet (operational plane) ---------
async function loadFleet() {
  const grid = document.getElementById('fleet-grid');
  try {
    const [fleet, brain] = await Promise.all([
      apiGet('/api/fleet'),
      apiGet('/api/brain/stats'),
    ]);
    if (!fleet.ok) { grid.innerHTML = \`<div class="integ-error">\${esc(fleet.error)}</div>\`; return; }
    const members = fleet.data.members || [];
    document.getElementById('fleet-count').textContent =
      fleet.data.onlineCount + ' / ' + fleet.data.total + ' online';

    grid.innerHTML = members.map(m => {
      const statusPill = m.role === 'hub'
        ? '<span class="integ-pill ok">hub</span>'
        : m.online ? '<span class="integ-pill ok">online</span>' : '<span class="integ-pill">offline</span>';
      const brainPill = m.onBrain ? '<span class="integ-pill warn">on brain</span>' : '';
      const hubExtra = (m.role === 'hub' && brain.ok)
        ? \`<div class="integ-row"><div class="body"><div class="primary">gBrain</div><div class="secondary">\${brain.data.pages.toLocaleString()} pages · \${brain.data.embedCoverage}% embedded · \${esc(brain.data.provider||'')}</div></div></div>\`
        : '';
      return \`
        <div class="integ-card">
          <div class="integ-head"><div class="integ-title">\${esc(m.name)} \${statusPill} \${brainPill}</div></div>
          <div class="integ-list">
            <div class="integ-row"><div class="body"><div class="primary">\${esc(m.role)}</div><div class="secondary">\${esc(m.note)}</div></div></div>
            \${hubExtra}
          </div>
        </div>\`;
    }).join('');
  } catch (err) {
    grid.innerHTML = \`<div class="integ-error">Fleet load failed: \${esc(err.message)}</div>\`;
  }
}

// --------- Gmail drill-in ---------
async function loadGmail() {
  const res = await apiGet('/api/integrations/gmail');
  const countEl = document.getElementById('gmail-count');
  const list = document.getElementById('gmail-list');
  if (!res.ok) {
    countEl.textContent = '';
    list.innerHTML = \`<div class="integ-error">Gmail unavailable: \${esc(res.error)}</div>\`;
    return;
  }
  const { unreadCount, recent } = res.data;
  countEl.textContent = unreadCount + ' unread';
  if (!recent?.length) {
    list.innerHTML = '<div class="integ-error">Inbox zero ✓</div>';
    return;
  }
  list.innerHTML = recent.map(m => \`
    <div class="integ-row">
      <div class="body">
        <div class="primary">\${esc(m.subject || '(no subject)')}</div>
        <div class="secondary">\${esc(m.from)}</div>
        <div class="secondary" style="margin-top:4px;color:var(--beige);opacity:.7;">\${esc(truncate(m.snippet, 140))}</div>
      </div>
      <div class="right">\${m.internalDate ? timeAgo(new Date(m.internalDate).toISOString()) : ''}</div>
    </div>
  \`).join('');
}

// --------- Calendar drill-in ---------
async function loadCalendar() {
  const res = await apiGet('/api/integrations/calendar');
  const countEl = document.getElementById('cal-count');
  const list = document.getElementById('cal-list');
  if (!res.ok) {
    countEl.textContent = '';
    list.innerHTML = \`<div class="integ-error">Calendar unavailable: \${esc(res.error)}</div>\`;
    return;
  }
  const { events, count } = res.data;
  countEl.textContent = count + ' events';
  if (!events?.length) {
    list.innerHTML = '<div class="integ-error">No events today</div>';
    return;
  }
  list.innerHTML = events.map(ev => {
    const link = ev.hangoutLink || ev.htmlLink;
    const title = link
      ? \`<a href="\${esc(link)}" target="_blank" rel="noopener">\${esc(ev.summary)}</a>\`
      : esc(ev.summary);
    return \`
      <div class="integ-row">
        <div class="body">
          <div class="primary">\${title}</div>
          <div class="secondary">\${fmtEventRange(ev)}\${ev.location ? ' · ' + esc(ev.location) : ''}\${ev.attendees ? ' · ' + ev.attendees + ' attendees' : ''}</div>
        </div>
      </div>
    \`;
  }).join('');
}

// --------- Slack drill-in ---------
async function loadSlack() {
  const res = await apiGet('/api/integrations/slack');
  const countEl = document.getElementById('slack-count');
  const list = document.getElementById('slack-list');
  if (!res.ok) {
    countEl.textContent = '';
    list.innerHTML = \`<div class="integ-error">Slack unavailable: \${esc(res.error)}</div>\`;
    return;
  }
  const { unreadCount, activeCount, channels } = res.data;
  countEl.textContent = (activeCount ?? channels.length) + ' active' + (unreadCount > 0 ? ' · ' + unreadCount + ' unread' : '');
  if (!channels?.length) {
    list.innerHTML = '<div class="integ-error">No active channels</div>';
    return;
  }
  list.innerHTML = channels.map(c => {
    const typeBadge = c.type === 'dm' ? '@' : c.type === 'private' ? '🔒' : c.type === 'group_dm' ? '👥' : '#';
    const link = c.link
      ? \`<a href="\${esc(c.link)}">\${typeBadge}\${esc(c.name)}</a>\`
      : typeBadge + esc(c.name);
    return \`
      <div class="integ-row">
        <div class="body">
          <div class="primary">\${link}</div>
          <div class="secondary">\${c.unread ? 'unread · ' : ''}\${c.lastActivity ? 'active ' + timeAgo(new Date(c.lastActivity).toISOString()) : 'no recent dated activity'}</div>
        </div>
        <div class="right">\${c.unread ? '●' : ''}</div>
      </div>
    \`;
  }).join('');
}

// --------- ClickUp drill-in ---------
async function loadClickup() {
  const res = await apiGet('/api/integrations/clickup');
  const countEl = document.getElementById('cu-count');
  const list = document.getElementById('cu-list');
  if (!res.ok) {
    countEl.textContent = '';
    list.innerHTML = \`<div class="integ-error">ClickUp unavailable: \${esc(res.error)}</div>\`;
    return;
  }
  const { openCount, overdue, dueThisWeek, tasks } = res.data;
  countEl.textContent = \`\${openCount} open · \${overdue} overdue · \${dueThisWeek} this week\`;
  if (!tasks?.length) {
    list.innerHTML = '<div class="integ-error">No open tasks</div>';
    return;
  }
  list.innerHTML = tasks.map(t => {
    const overdueRow = t.due && t.due < Date.now();
    return \`
      <div class="integ-row">
        <div class="body">
          <div class="primary"><a href="\${esc(t.url)}" target="_blank" rel="noopener">\${esc(t.name)}</a></div>
          <div class="secondary">\${esc(t.list)} · \${esc(t.status)}\${t.priority ? ' · priority ' + esc(t.priority) : ''}</div>
        </div>
        <div class="right" style="color:\${overdueRow ? 'var(--danger)' : 'var(--muted)'}">\${fmtDue(t.due)}</div>
      </div>
    \`;
  }).join('');
}

// ============================================================
// Utility
// ============================================================
function timeAgo(iso) {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 0) {
    // future date (next_run)
    const abs = Math.abs(s);
    if (abs < 60) return 'in ' + abs + 's';
    if (abs < 3600) return 'in ' + Math.floor(abs / 60) + 'm';
    if (abs < 86400) return 'in ' + Math.floor(abs / 3600) + 'h';
    return 'in ' + Math.floor(abs / 86400) + 'd';
  }
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function truncate(str, n) {
  if (!str || str.length <= n) return str;
  return str.slice(0, n) + '…';
}

function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function showToast(msg, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}
</script>
</body>
</html>`;
}
