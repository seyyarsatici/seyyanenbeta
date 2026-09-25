#include "web_server.h"

// ==============================================================================
// SEYYANEN MINI - PHASE M-6 WEB APPLICATION (INLINED PROGMEM)
// ==============================================================================

static const char M6_INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Seyyanen Mini | Live Telemetry & Session Manager</title>
    <style>
        :root {
            --bg-primary: #0b0f19;
            --bg-card: #151e2e;
            --bg-card-hover: #1c273c;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --accent-cyan: #06b6d4;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-amber: #f59e0b;
            --accent-red: #ef4444;
            --border: #243247;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; -webkit-tap-highlight-color: transparent; }
        body { background: var(--bg-primary); color: var(--text-main); min-height: 100vh; display: flex; flex-direction: column; }
        header { background: #0f172a; border-bottom: 1px solid var(--border); padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .logo-wrap { display: flex; align-items: center; gap: 10px; }
        .badge-tag { background: linear-gradient(135deg, #06b6d4, #2563eb); color: #fff; font-weight: 800; font-size: 13px; padding: 5px 9px; border-radius: 6px; letter-spacing: 0.5px; }
        .title h1 { font-size: 16px; font-weight: 700; letter-spacing: 0.2px; }
        .title span { font-size: 11px; color: var(--text-sub); }
        .header-badges { display: flex; gap: 6px; flex-wrap: wrap; }
        .status-badge { padding: 4px 10px; border-radius: 9999px; font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid transparent; }
        .badge-ready, .badge-connected, .badge-running { background: #064e3b; color: #34d399; border-color: #065f46; }
        .badge-disconnected, .badge-error, .badge-stopped { background: #450a0a; color: #f87171; border-color: #7f1d1d; }
        .badge-paused, .badge-connecting, .badge-idle { background: #451a03; color: #fbbf24; border-color: #78350f; }
        nav { background: #0f172a; border-bottom: 1px solid var(--border); display: flex; overflow-x: auto; padding: 0 16px; }
        .nav-btn { background: none; border: none; color: var(--text-sub); font-size: 13px; font-weight: 700; padding: 12px 16px; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; transition: 0.15s; }
        .nav-btn.active { color: var(--accent-cyan); border-bottom-color: var(--accent-cyan); }
        main { max-width: 1200px; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; flex: 1; width: 100%; }
        .tab-content { display: none; flex-direction: column; gap: 16px; }
        .tab-content.active { display: flex; }
        .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px; }
        .card-header h2 { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-main); }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
        .metric-box { background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
        .metric-box .lbl { font-size: 10px; text-transform: uppercase; color: var(--text-sub); font-weight: 600; }
        .metric-box .val { font-size: 18px; font-weight: 700; font-family: monospace; color: var(--text-main); margin-top: 3px; }
        .val-cyan { color: var(--accent-cyan) !important; }
        .actions-row { display: flex; gap: 8px; flex-wrap: wrap; }
        .btn { min-height: 40px; padding: 8px 14px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; border: none; transition: 0.15s; display: inline-flex; align-items: center; justify-content: center; }
        .btn-green { background: #059669; color: #fff; }
        .btn-green:hover { background: #10b981; }
        .btn-red { background: #dc2626; color: #fff; }
        .btn-red:hover { background: #ef4444; }
        .btn-amber { background: #d97706; color: #fff; }
        .btn-amber:hover { background: #f59e0b; }
        .btn-cyan { background: #0891b2; color: #fff; }
        .btn-cyan:hover { background: #06b6d4; }
        .btn-secondary { background: #334155; color: #e2e8f0; }
        .btn-secondary:hover { background: #475569; }
        .btn:disabled { opacity: 0.35; cursor: not-allowed; }
        .telemetry-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
        .signal-card { background: rgba(0,0,0,0.2); border: 1px solid var(--border); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 6px; }
        .signal-card.stale { border-color: #f59e0b; }
        .signal-card.error { border-color: #ef4444; }
        .signal-top { display: flex; justify-content: space-between; align-items: baseline; }
        .signal-pid { font-size: 11px; font-family: monospace; color: var(--text-sub); }
        .signal-name { font-size: 13px; font-weight: 700; color: var(--text-main); }
        .signal-mid { display: flex; align-items: baseline; gap: 6px; margin: 2px 0; }
        .signal-val { font-size: 24px; font-weight: 800; font-family: monospace; color: var(--accent-cyan); }
        .signal-unit { font-size: 12px; color: var(--text-sub); font-weight: 600; }
        .signal-footer { display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 6px; margin-top: auto; }
        .pill { padding: 2px 6px; border-radius: 9999px; font-size: 10px; font-weight: 700; text-transform: uppercase; }
        .pill-fresh { background: #064e3b; color: #34d399; }
        .pill-aging { background: #451a03; color: #fbbf24; }
        .pill-stale { background: #4c0519; color: #fda4af; }
        .pill-never { background: #1f2937; color: #9ca3af; }
        .pill-good { background: #065f46; color: #6ee7b7; }
        .pill-timeout { background: #7f1d1d; color: #fca5a5; }
        .signal-age { font-size: 11px; font-family: monospace; color: var(--text-sub); }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
        .data-table th { text-align: left; padding: 8px 10px; color: var(--text-sub); border-bottom: 1px solid var(--border); font-size: 10px; text-transform: uppercase; }
        .data-table td { padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); }
        .alert-box { padding: 10px 14px; border-radius: 8px; font-size: 12px; display: none; margin-bottom: 10px; border: 1px solid transparent; }
        .alert-error { background: #450a0a; border-color: #7f1d1d; color: #fca5a5; }
        .alert-warning { background: #451a03; border-color: #78350f; color: #fde68a; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 100; justify-content: center; align-items: center; padding: 16px; }
        .modal-body { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; max-width: 600px; width: 100%; max-height: 80vh; overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 12px; }
        footer { text-align: center; padding: 10px; font-size: 11px; color: var(--text-sub); border-top: 1px solid var(--border); background: #0f172a; }
    </style>
</head>
<body>
    <header>
        <div class="logo-wrap">
            <span class="badge-tag">M-6</span>
            <div class="title">
                <h1>SEYYANEN MINI</h1>
                <span>Live Acquisition & Session Manager</span>
            </div>
        </div>
        <div class="header-badges">
            <div id="badge-bt" class="status-badge badge-disconnected">BT: DISCONNECTED</div>
            <div id="badge-obd" class="status-badge badge-disconnected">OBD: NOT READY</div>
            <div id="badge-acq" class="status-badge badge-stopped">ACQ: IDLE</div>
            <div id="badge-sd" class="status-badge badge-disconnected">SD: INITIALIZING</div>
        </div>
    </header>

    <nav>
        <button class="nav-btn active" onclick="switchTab('dashboard')">Dashboard</button>
        <button class="nav-btn" onclick="switchTab('live')">Live Telemetry</button>
        <button class="nav-btn" onclick="switchTab('sessions')">Sessions</button>
        <button class="nav-btn" onclick="switchTab('pids')">PIDs</button>
        <button class="nav-btn" onclick="switchTab('system')">System</button>
    </nav>

    <main>
        <div id="error-banner" class="alert-box alert-error"></div>

        <!-- TAB 1: DASHBOARD -->
        <div id="tab-dashboard" class="tab-content active">
            <!-- Health & Subsystem Overview Cards -->
            <section class="card">
                <div class="card-header">
                    <h2>Subsystem Health Summary</h2>
                    <span id="session-tag" style="font-size:12px; font-family:monospace; color:var(--accent-cyan);">SESSION: NONE</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric-box">
                        <div class="lbl">Transport Link</div>
                        <div id="dash-bt-state" class="val">DISCONNECTED</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Adapter Model</div>
                        <div id="dash-adapter" class="val" style="font-size:14px;">UNKNOWN</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Vehicle Protocol</div>
                        <div id="dash-proto" class="val" style="font-size:14px;">UNKNOWN</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Acquisition</div>
                        <div id="dash-acq-state" class="val">IDLE</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Storage Health</div>
                        <div id="dash-sd-state" class="val">IDLE</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Free Storage</div>
                        <div id="dash-sd-free" class="val">-- MB</div>
                    </div>
                </div>
            </section>

            <!-- Quick Controls -->
            <section class="card">
                <div class="card-header">
                    <h2>Quick Controls</h2>
                </div>
                <div class="actions-row">
                    <button id="btn-quick-acq-start" class="btn btn-green" onclick="actionAcqStart()">[ START ACQUISITION ]</button>
                    <button id="btn-quick-acq-pause" class="btn btn-amber" onclick="actionAcqPause()">[ PAUSE ]</button>
                    <button id="btn-quick-acq-resume" class="btn btn-cyan" onclick="actionAcqResume()">[ RESUME ]</button>
                    <button id="btn-quick-acq-stop" class="btn btn-red" onclick="actionAcqStop()">[ STOP ]</button>
                    <div style="flex:1;"></div>
                    <button id="btn-quick-rec-start" class="btn btn-green" onclick="actionRecStart()">[ START RECORDING ]</button>
                    <button id="btn-quick-rec-stop" class="btn btn-red" onclick="actionRecStop()">[ STOP RECORDING ]</button>
                </div>
            </section>

            <!-- Key Powertrain Telemetry Overview -->
            <section class="card">
                <div class="card-header">
                    <h2>Primary Engine Telemetry</h2>
                    <button class="btn btn-secondary" onclick="switchTab('live')" style="min-height:30px; padding:4px 8px; font-size:11px;">View All Signals &rarr;</button>
                </div>
                <div id="primary-signals-container" class="telemetry-grid">
                    <div style="color:var(--text-sub); font-size:12px; grid-column:1/-1;">Awaiting acquisition start...</div>
                </div>
            </section>
        </div>

        <!-- TAB 2: LIVE TELEMETRY -->
        <div id="tab-live" class="tab-content">
            <section class="card">
                <div class="card-header">
                    <h2>Live Monitored Signals (Non-Simultaneous Timestamps)</h2>
                    <span id="live-rate-tag" style="font-size:12px; font-family:monospace; color:var(--accent-cyan);">0.0 req/s</span>
                </div>
                <div id="all-signals-container" class="telemetry-grid">
                    <div style="color:var(--text-sub); font-size:12px; grid-column:1/-1;">Awaiting acquisition start...</div>
                </div>
            </section>
        </div>

        <!-- TAB 3: SESSIONS -->
        <div id="tab-sessions" class="tab-content">
            <section class="card">
                <div class="card-header">
                    <h2>Recorded Sessions (/SEYYANEN/SESSIONS/)</h2>
                    <div class="actions-row">
                        <button class="btn btn-secondary" onclick="fetchSessions()">[ REFRESH ]</button>
                    </div>
                </div>
                <div style="overflow-x: auto;">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Session ID</th>
                                <th>Status</th>
                                <th>Samples</th>
                                <th>Size</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="sessions-table-body">
                            <tr><td colspan="5" style="color:var(--text-sub);">No recorded sessions found.</td></tr>
                        </tbody>
                    </table>
                </div>
            </section>
        </div>

        <!-- TAB 4: PIDS -->
        <div id="tab-pids" class="tab-content">
            <section class="card">
                <div class="card-header">
                    <h2>Discovered Mode 01 Standard PIDs</h2>
                    <button id="btn-pid-rescan" class="btn btn-cyan" onclick="actionObdScan()">[ RESCAN PIDS ]</button>
                </div>
                <div style="overflow-x: auto;">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>PID</th>
                                <th>Name</th>
                                <th>Unit</th>
                                <th>Supported</th>
                                <th>Interval</th>
                                <th>Decoder Formula</th>
                            </tr>
                        </thead>
                        <tbody id="pids-table-body">
                            <tr><td colspan="6" style="color:var(--text-sub);">No PIDs discovered yet. Click [RESCAN PIDS].</td></tr>
                        </tbody>
                    </table>
                </div>
            </section>
        </div>

        <!-- TAB 5: SYSTEM -->
        <div id="tab-system" class="tab-content">
            <section class="card">
                <div class="card-header">
                    <h2>System Diagnostics & Hardware Identity</h2>
                    <button class="btn btn-secondary" onclick="fetchStatus()">[ REFRESH ]</button>
                </div>
                <div class="metrics-grid">
                    <div class="metric-box">
                        <div class="lbl">Firmware Version</div>
                        <div class="val" style="font-size:14px;">1.0.0 (Mini)</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">API Phase</div>
                        <div class="val val-cyan" style="font-size:14px;">M-6 Web UI</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Free Heap</div>
                        <div id="sys-heap" class="val">-- KB</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">System Uptime</div>
                        <div id="sys-uptime" class="val">0s</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Bluetooth Adapter</div>
                        <div id="sys-bt-name" class="val" style="font-size:13px;">--</div>
                    </div>
                    <div class="metric-box">
                        <div class="lbl">Adapter Firmware</div>
                        <div id="sys-bt-fw" class="val" style="font-size:13px;">--</div>
                    </div>
                </div>
            </section>

            <section class="card">
                <div class="card-header">
                    <h2>Transport Lifecycle Controls</h2>
                </div>
                <div class="actions-row">
                    <button id="btn-sys-conn" class="btn btn-cyan" onclick="actionConnect()">[ CONNECT BT ]</button>
                    <button id="btn-sys-reconn" class="btn btn-amber" onclick="actionReconnect()">[ RECONNECT ]</button>
                    <button id="btn-sys-disconn" class="btn btn-red" onclick="actionDisconnect()">[ DISCONNECT ]</button>
                </div>
            </section>
        </div>
    </main>

    <!-- Session Detail Modal -->
    <div id="session-modal" class="modal" onclick="if(event.target===this)closeModal()">
        <div class="modal-body">
            <div class="card-header" style="margin-bottom:0;">
                <h2 id="modal-title">Session Details</h2>
                <button class="btn btn-secondary" onclick="closeModal()" style="min-height:28px; padding:2px 8px;">&times;</button>
            </div>
            <div id="modal-content" style="font-size:12px; font-family:monospace; line-height:1.6; white-space:pre-wrap; background:rgba(0,0,0,0.3); padding:12px; border-radius:8px;"></div>
            <div class="actions-row">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>
        </div>
    </div>

    <footer>
        Seyyanen Mini &bull; Phase M-6 Web Management &bull; 100% Offline AP &bull; Zero Direct I/O in HTTP
    </footer>

    <script>
        let liveTimer = null;
        let statusTimer = null;
        let activeTab = "dashboard";

        document.addEventListener("DOMContentLoaded", () => {
            fetchStatus();
            fetchLive();
            fetchSessions();
            fetchPids();
            liveTimer = setInterval(fetchLive, 250);
            statusTimer = setInterval(fetchStatus, 1000);
        });

        function switchTab(tabId) {
            activeTab = tabId;
            document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            
            const btn = Array.from(document.querySelectorAll(".nav-btn")).find(b => b.textContent.toLowerCase().includes(tabId));
            if (btn) btn.classList.add("active");
            
            const tab = document.getElementById("tab-" + tabId);
            if (tab) tab.classList.add("active");

            if (tabId === "sessions") fetchSessions();
            if (tabId === "pids") fetchPids();
        }

        async function fetchStatus() {
            try {
                const res = await fetch("/api/status");
                if (!res.ok) return;
                const d = await res.json();
                renderStatus(d);
            } catch (e) {}
        }

        function renderStatus(d) {
            // Badges
            updateBadge("badge-bt", "BT: " + (d.bt_state || "DISCONNECTED"), d.bt_state === "CONNECTED" ? "badge-connected" : (d.bt_state === "CONNECTING" ? "badge-connecting" : "badge-disconnected"));
            updateBadge("badge-obd", "OBD: " + (d.obd_state || "NOT READY"), d.obd_state === "READY" ? "badge-ready" : "badge-disconnected");
            updateBadge("badge-acq", "ACQ: " + (d.acq_state || "STOPPED"), d.acq_state === "RUNNING" ? "badge-running" : (d.acq_state === "PAUSED" ? "badge-paused" : "badge-stopped"));
            updateBadge("badge-sd", "SD: " + (d.sd_status || "NO_CARD"), d.sd_status === "READY" ? "badge-ready" : "badge-disconnected");

            // Overview
            document.getElementById("session-tag").textContent = "SESSION: " + (d.session_id || "NONE");
            document.getElementById("dash-bt-state").textContent = d.bt_state || "DISCONNECTED";
            document.getElementById("dash-adapter").textContent = d.adapter_name || "UNKNOWN";
            document.getElementById("dash-proto").textContent = d.protocol || "UNKNOWN";
            document.getElementById("dash-acq-state").textContent = d.acq_state || "IDLE";
            document.getElementById("dash-sd-state").textContent = d.sd_status || "IDLE";

            // System
            document.getElementById("sys-heap").textContent = Math.round((d.free_heap || 0) / 1024) + " KB";
            document.getElementById("sys-uptime").textContent = (d.uptime_sec || 0) + "s";
            document.getElementById("sys-bt-name").textContent = d.adapter_name || "vLinker MC";
            document.getElementById("sys-bt-fw").textContent = d.firmware || "v?.?";

            // Actionable Alerts
            const alertBox = document.getElementById("error-banner");
            if (d.bt_state === "DISCONNECTED") {
                alertBox.textContent = "vLinker Bluetooth link disconnected. Check adapter power or click [CONNECT BT].";
                alertBox.style.display = "block";
            } else if (d.obd_state !== "READY" && d.bt_state === "CONNECTED") {
                alertBox.textContent = "Vehicle ignition not detected or OBD initializing. Turn ignition to ON/RUN.";
                alertBox.style.display = "block";
            } else if (d.sd_status === "NO_CARD") {
                alertBox.textContent = "MicroSD card not detected. Sessions will not be persisted.";
                alertBox.style.display = "block";
            } else {
                alertBox.style.display = "none";
            }
        }

        function updateBadge(id, text, cls) {
            const b = document.getElementById(id);
            if (b) {
                b.textContent = text;
                b.className = "status-badge " + cls;
            }
        }

        async function fetchLive() {
            try {
                const res = await fetch("/api/live");
                if (!res.ok) return;
                const d = await res.json();
                renderLive(d);
            } catch (e) {}
        }

        function renderLive(d) {
            if (d.metrics && document.getElementById("live-rate-tag")) {
                document.getElementById("live-rate-tag").textContent = (d.metrics.requests_per_sec || 0).toFixed(1) + " req/s";
            }

            const allContainer = document.getElementById("all-signals-container");
            const primContainer = document.getElementById("primary-signals-container");
            if (!allContainer) return;

            if (!d.signals || d.signals.length === 0) {
                allContainer.innerHTML = `<div style="color:var(--text-sub); font-size:12px; grid-column:1/-1;">Awaiting acquisition start...</div>`;
                if (primContainer) primContainer.innerHTML = `<div style="color:var(--text-sub); font-size:12px; grid-column:1/-1;">Awaiting acquisition start...</div>`;
                return;
            }

            let allHtml = "";
            let primHtml = "";

            d.signals.forEach(s => {
                let fClass = "pill-fresh";
                if (s.freshness === "AGING") fClass = "pill-aging";
                else if (s.freshness === "STALE") fClass = "pill-stale";
                else if (s.freshness === "NEVER_VALID") fClass = "pill-never";

                let qClass = (s.quality === "GOOD") ? "pill-good" : "pill-timeout";
                let cardClass = "signal-card";
                if (s.freshness === "STALE") cardClass += " stale";
                if (s.quality !== "GOOD" && s.quality !== "NO_DATA") cardClass += " error";

                let valDisplay = (s.value !== undefined && s.quality !== "NO_DATA") ? s.value.toFixed(1) : "--";
                let ageDisplay = s.age_ms !== undefined ? (s.age_ms < 1000 ? s.age_ms + " ms" : (s.age_ms / 1000).toFixed(1) + " s") : "--";

                const cardHtml = `
                    <div class="${cardClass}">
                        <div class="signal-top">
                            <span class="signal-name">${s.name}</span>
                            <span class="signal-pid">01${s.pid_hex}</span>
                        </div>
                        <div class="signal-mid">
                            <span class="signal-val">${valDisplay}</span>
                            <span class="signal-unit">${s.unit}</span>
                        </div>
                        <div class="signal-footer">
                            <div style="display:flex; gap:4px;">
                                <span class="pill ${qClass}">${s.quality}</span>
                                <span class="pill ${fClass}">${s.freshness}</span>
                            </div>
                            <span class="signal-age">${ageDisplay}</span>
                        </div>
                    </div>
                `;

                allHtml += cardHtml;
                if (["RPM", "ECT", "MAP", "TPS", "Speed"].includes(s.name)) {
                    primHtml += cardHtml;
                }
            });

            allContainer.innerHTML = allHtml;
            if (primContainer) primContainer.innerHTML = primHtml || allHtml;
        }

        async function fetchSessions() {
            try {
                const res = await fetch("/api/sessions");
                if (!res.ok) return;
                const d = await res.json();
                renderSessions(d.sessions || []);
            } catch (e) {}
        }

        function renderSessions(sessions) {
            const tbody = document.getElementById("sessions-table-body");
            if (!tbody) return;

            if (sessions.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-sub);">No recorded sessions found.</td></tr>`;
                return;
            }

            let html = "";
            sessions.forEach(s => {
                const sizeKb = (s.size_bytes / 1024).toFixed(1);
                const isAct = (s.state === "ACTIVE");
                const dlBtn = isAct 
                    ? `<button class="btn btn-secondary" disabled style="min-height:28px; padding:3px 8px; font-size:11px;">[ RECORDING ACTIVE ]</button>`
                    : `<a href="/api/sessions/download?id=${encodeURIComponent(s.session_id)}" class="btn btn-cyan" style="min-height:28px; padding:3px 8px; font-size:11px; text-decoration:none;">[ DOWNLOAD CSV ]</a>`;

                html += `
                    <tr>
                        <td><strong>${s.session_id}</strong></td>
                        <td><span class="pill pill-fresh">${s.state}</span></td>
                        <td>${s.sample_count || 0}</td>
                        <td>${sizeKb} KB</td>
                        <td>
                            <div style="display:flex; gap:6px;">
                                <button class="btn btn-secondary" onclick="viewSession('${s.session_id}')" style="min-height:28px; padding:3px 8px; font-size:11px;">[ VIEW ]</button>
                                ${dlBtn}
                            </div>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        }

        async function viewSession(id) {
            try {
                const res = await fetch("/api/sessions/metadata?id=" + encodeURIComponent(id));
                if (!res.ok) throw new Error("Metadata unavailable");
                const meta = await res.json();
                document.getElementById("modal-title").textContent = "Session: " + id;
                document.getElementById("modal-content").textContent = JSON.stringify(meta, null, 2);
                document.getElementById("session-modal").style.display = "flex";
            } catch (e) { alert("Error: " + e.message); }
        }

        function closeModal() {
            document.getElementById("session-modal").style.display = "none";
        }

        async function fetchPids() {
            try {
                const res = await fetch("/api/pids");
                if (!res.ok) return;
                const d = await res.json();
                renderPids(d.pids || []);
            } catch (e) {}
        }

        function renderPids(pids) {
            const tbody = document.getElementById("pids-table-body");
            if (!tbody) return;

            if (pids.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" style="color:var(--text-sub);">No PIDs registered.</td></tr>`;
                return;
            }

            let html = "";
            pids.forEach(p => {
                const isSupp = p.supported;
                const pillCls = isSupp ? "pill pill-fresh" : "pill pill-never";
                html += `
                    <tr>
                        <td><code>01${p.pid_hex}</code></td>
                        <td><strong>${p.name}</strong></td>
                        <td>${p.unit}</td>
                        <td><span class="${pillCls}">${isSupp ? "YES" : "NO"}</span></td>
                        <td>${p.poll_interval_ms} ms</td>
                        <td><code>${p.formula}</code></td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        }

        // Action Handlers
        async function actionConnect() {
            await fetch("/api/connect", { method: "POST" });
            fetchStatus();
        }
        async function actionDisconnect() {
            await fetch("/api/disconnect", { method: "POST" });
            fetchStatus();
        }
        async function actionReconnect() {
            await fetch("/api/reconnect", { method: "POST" });
            fetchStatus();
        }
        async function actionObdScan() {
            await fetch("/api/obd/scan", { method: "POST" });
            fetchPids();
            fetchStatus();
        }
        async function actionAcqStart() {
            await fetch("/api/acquisition/start", { method: "POST" });
            fetchLive();
            fetchStatus();
        }
        async function actionAcqStop() {
            await fetch("/api/acquisition/stop", { method: "POST" });
            fetchLive();
            fetchStatus();
        }
        async function actionAcqPause() {
            await fetch("/api/acquisition/pause", { method: "POST" });
            fetchLive();
            fetchStatus();
        }
        async function actionAcqResume() {
            await fetch("/api/acquisition/resume", { method: "POST" });
            fetchLive();
            fetchStatus();
        }
        async function actionRecStart() {
            await fetch("/api/recording/start", { method: "POST" });
            fetchStatus();
            fetchSessions();
        }
        async function actionRecStop() {
            await fetch("/api/recording/stop", { method: "POST" });
            fetchStatus();
            fetchSessions();
        }
    </script>
</body>
</html>
)rawliteral";

// ==============================================================================
// MiniWebServer Implementation (Phase M-6)
// ==============================================================================

MiniWebServer::MiniWebServer(VLinkerBluetoothTransport& bt,
                             Elm327Client& elm,
                             PidScanner& scanner,
                             AcquisitionScheduler& scheduler,
                             SdLogger& logger)
    : _server(SEYYANEN_HTTP_PORT),
      _bt(bt),
      _elm(elm),
      _scanner(scanner),
      _scheduler(scheduler),
      _logger(logger),
      _diagOpRequester(nullptr),
      _diagOpGetter(nullptr) {}

MiniWebServer::~MiniWebServer() {}

void MiniWebServer::setDiagOpCallbacks(DiagOpRequester req, DiagOpGetter get) {
    _diagOpRequester = req;
    _diagOpGetter = get;
}

bool MiniWebServer::begin() {
    Serial.println("[WEB] Starting Wi-Fi SoftAP for Phase M-6 Management...");
    WiFi.mode(WIFI_AP);

    IPAddress local_ip(SEYYANEN_AP_IP);
    IPAddress gateway(SEYYANEN_AP_GATEWAY);
    IPAddress subnet(SEYYANEN_AP_SUBNET);
    WiFi.softAPConfig(local_ip, gateway, subnet);

    bool ok = WiFi.softAP(SEYYANEN_AP_SSID, SEYYANEN_AP_PASS, SEYYANEN_AP_CHANNEL, 0, SEYYANEN_AP_MAX_CONN);
    if (!ok) {
        Serial.println("[WEB] Failed to start SoftAP!");
        return false;
    }

    Serial.printf("[WEB] Access Point active. Open: http://%s\n", WiFi.softAPIP().toString().c_str());

    setupRoutes();
    _server.begin();
    Serial.println("[WEB] Phase M-6 Web Application & REST APIs ready.");
    return true;
}

void MiniWebServer::update() {
    _server.handleClient();
}

void MiniWebServer::setupRoutes() {
    _server.enableCORS(true);
    _server.on("/", HTTP_GET, [this]() { handleRoot(); });
    _server.on("/index.html", HTTP_GET, [this]() { handleRoot(); });
    _server.on("/favicon.ico", HTTP_GET, [this]() { _server.send(204); });
    _server.on("/api/status", HTTP_GET, [this]() { handleApiStatus(); });
    _server.on("/api/live", HTTP_GET, [this]() { handleApiLive(); });
    _server.on("/api/metrics", HTTP_GET, [this]() { handleApiMetrics(); });
    _server.on("/api/pids", HTTP_GET, [this]() { handleApiPids(); });
    _server.on("/api/connect", HTTP_POST, [this]() { handleApiConnect(); });
    _server.on("/api/disconnect", HTTP_POST, [this]() { handleApiDisconnect(); });
    _server.on("/api/reconnect", HTTP_POST, [this]() { handleApiReconnect(); });
    _server.on("/api/obd/init", HTTP_POST, [this]() { handleApiObdInit(); });
    _server.on("/api/obd/scan", HTTP_POST, [this]() { handleApiObdScan(); });
    _server.on("/api/acquisition/start", HTTP_POST, [this]() { handleApiAcqStart(); });
    _server.on("/api/acquisition/stop", HTTP_POST, [this]() { handleApiAcqStop(); });
    _server.on("/api/acquisition/pause", HTTP_POST, [this]() { handleApiAcqPause(); });
    _server.on("/api/acquisition/resume", HTTP_POST, [this]() { handleApiAcqResume(); });

    // Phase M-6 Storage & Session Management Endpoints
    _server.on("/api/storage/status", HTTP_GET, [this]() { handleApiStorageStatus(); });
    _server.on("/api/sessions", HTTP_GET, [this]() { handleApiSessions(); });
    _server.on("/api/sessions/metadata", HTTP_GET, [this]() { handleApiSessionMetadata(); });
    _server.on("/api/sessions/download", HTTP_GET, [this]() { handleApiSessionDownload(); });
    _server.on("/api/recording/start", HTTP_POST, [this]() { handleApiRecordingStart(); });
    _server.on("/api/recording/stop", HTTP_POST, [this]() { handleApiRecordingStop(); });

    _server.onNotFound([this]() { handleNotFound(); });
}

void MiniWebServer::handleRoot() {
    _server.send_P(200, "text/html", M6_INDEX_HTML);
}

void MiniWebServer::handleApiStatus() {
    const AdapterIdentityInfo& id = _bt.getAdapterIdentity();
    StorageInfo sInfo;
    StorageMetrics sMetrics;
    _logger.getStorageInfo(sInfo);
    _logger.getStorageMetrics(sMetrics);

    char json[768];
    snprintf(json, sizeof(json),
        "{"
        "\"bt_state\":\"%s\","
        "\"adapter_name\":\"%s\","
        "\"firmware\":\"%s\","
        "\"obd_state\":\"%s\","
        "\"protocol\":\"%s\","
        "\"scanner_state\":\"%s\","
        "\"acq_state\":\"%s\","
        "\"diag_op_state\":\"%s\","
        "\"session_id\":\"%s\","
        "\"sd_status\":\"%s\","
        "\"sd_health\":\"%s\","
        "\"sd_queue_depth\":%u,"
        "\"sd_high_water_mark\":%u,"
        "\"free_heap\":%u,"
        "\"uptime_sec\":%u,"
        "\"supported_count\":%u"
        "}",
        _bt.getStateString(),
        id.adapter_name,
        id.firmware,
        _elm.getStateString(),
        _elm.getProtocol(),
        _scanner.getStateString(),
        _scheduler.getStateString(),
        _diagOpGetter ? diagnosticOpStateToString(_diagOpGetter()) : "IDLE",
        _scheduler.getSessionId(),
        storageStatusToString(sInfo.status),
        storageHealthToString(sMetrics.health_state),
        (unsigned int)sMetrics.queue_depth,
        (unsigned int)sMetrics.queue_high_water_mark,
        (unsigned int)ESP.getFreeHeap(),
        (unsigned int)(esp_timer_get_time() / 1000000ULL),
        (unsigned int)_scanner.getSupportedCount()
    );

    _server.send(200, "application/json", json);
}

void MiniWebServer::handleApiLive() {
    LiveSnapshot snap;
    _scheduler.getSnapshot(snap);

    String json = "{\"bt_state\":\"";
    json += _bt.getStateString();
    json += "\",\"obd_state\":\"";
    json += _elm.getStateString();
    json += "\",\"state\":\"";
    json += acquisitionStateToString(snap.state);
    json += "\",\"session_id\":\"";
    json += snap.session_id;
    json += "\",\"uptime_sec\":";
    json += snap.uptime_sec;
    json += ",\"metrics\":{";
    json += "\"total_requests\":";
    json += snap.metrics.total_requests;
    json += ",\"successful_requests\":";
    json += snap.metrics.successful_requests;
    json += ",\"timeouts\":";
    json += snap.metrics.timeouts;
    json += ",\"malformed_count\":";
    json += snap.metrics.malformed_count;
    json += ",\"transport_errors\":";
    json += snap.metrics.transport_errors;
    json += ",\"average_latency_ms\":";
    json += String(snap.metrics.average_latency_ms, 1);
    json += ",\"requests_per_sec\":";
    json += String(snap.metrics.requests_per_sec, 1);
    json += ",\"active_pid_count\":";
    json += snap.metrics.active_pid_count;
    json += "},\"signals\":[";

    for (size_t i = 0; i < snap.signal_count; ++i) {
        if (i > 0) json += ",";
        const LiveSignal& s = snap.signals[i];
        char pidHex[5];
        snprintf(pidHex, sizeof(pidHex), "%02X", (uint8_t)(s.pid & 0xFF));

        json += "{\"pid\":";
        json += s.pid;
        json += ",\"pid_hex\":\"";
        json += pidHex;
        json += "\",\"name\":\"";
        json += s.name;
        json += "\",\"unit\":\"";
        json += s.unit;
        json += "\",\"value\":";
        json += String(s.value, 1);
        json += ",\"quality\":\"";
        json += qualityGradeToString(s.quality);
        json += "\",\"freshness\":\"";
        json += freshnessStateToString(s.freshness);
        json += "\",\"age_ms\":";
        json += s.age_ms;
        json += ",\"latency_ms\":";
        json += s.latency_ms;
        json += ",\"target_interval_ms\":";
        json += s.target_interval_ms;
        json += ",\"observed_interval_ms\":";
        json += s.observed_interval_ms;
        json += ",\"scheduler_delay_ms\":";
        json += s.scheduler_delay_ms;
        json += ",\"deadline_misses\":";
        json += s.deadline_misses;
        json += "}";
    }

    json += "]}";
    _server.send(200, "application/json", json);
}

void MiniWebServer::handleApiMetrics() {
    AcquisitionMetrics m;
    StorageMetrics sm;
    _scheduler.getMetrics(m);
    _logger.getStorageMetrics(sm);

    char json[768];
    snprintf(json, sizeof(json),
        "{"
        "\"total_requests\":%u,"
        "\"successful_requests\":%u,"
        "\"timeouts\":%u,"
        "\"no_data_count\":%u,"
        "\"malformed_count\":%u,"
        "\"transport_errors\":%u,"
        "\"average_latency_ms\":%.2f,"
        "\"last_latency_ms\":%u,"
        "\"requests_per_sec\":%.2f,"
        "\"active_pid_count\":%u,"
        "\"samples_written\":%u,"
        "\"samples_dropped\":%u,"
        "\"write_errors\":%u,"
        "\"queue_depth\":%u,"
        "\"queue_high_water_mark\":%u,"
        "\"backpressure_events\":%u,"
        "\"last_write_latency_us\":%u,"
        "\"last_flush_latency_us\":%u,"
        "\"storage_health\":\"%s\""
        "}",
        (unsigned int)m.total_requests,
        (unsigned int)m.successful_requests,
        (unsigned int)m.timeouts,
        (unsigned int)m.no_data_count,
        (unsigned int)m.malformed_count,
        (unsigned int)m.transport_errors,
        m.average_latency_ms,
        (unsigned int)m.last_latency_ms,
        m.requests_per_sec,
        (unsigned int)m.active_pid_count,
        (unsigned int)sm.samples_written,
        (unsigned int)sm.samples_dropped,
        (unsigned int)sm.write_errors,
        (unsigned int)sm.queue_depth,
        (unsigned int)sm.queue_high_water_mark,
        (unsigned int)sm.backpressure_events,
        (unsigned int)sm.last_write_latency_us,
        (unsigned int)sm.last_flush_latency_us,
        storageHealthToString(sm.health_state)
    );

    _server.send(200, "application/json", json);
}

void MiniWebServer::handleApiPids() {
    size_t count = _scanner.getRegisteredCount();
    String json = "{\"supported_count\":";
    json += _scanner.getSupportedCount();
    json += ",\"registered_count\":";
    json += count;
    json += ",\"registry_overflow\":";
    json += _scanner.getRegistryOverflowCount();
    json += ",\"pids\":[";

    for (size_t i = 0; i < count; ++i) {
        if (i > 0) json += ",";
        const PidMetadata* m = _scanner.getPidMetadata(i);
        if (!m) continue;

        char pidHex[5];
        snprintf(pidHex, sizeof(pidHex), "%02X", (uint8_t)(m->pid & 0xFF));

        json += "{\"pid_hex\":\"";
        json += pidHex;
        json += "\",\"name\":\"";
        json += m->name;
        json += "\",\"unit\":\"";
        json += m->unit;
        json += "\",\"supported\":";
        json += m->supported ? "true" : "false";
        json += ",\"priority\":";
        json += m->priority;
        json += ",\"poll_interval_ms\":";
        json += m->poll_interval_ms;
        json += ",\"formula\":\"";
        json += m->raw_formula;
        json += "\"}";
    }

    json += "],\"unscheduled_pids\":[";
    size_t uCount = _scheduler.getUnscheduledPidCount();
    for (size_t u = 0; u < uCount; ++u) {
        if (u > 0) json += ",";
        const UnscheduledPidInfo* un = _scheduler.getUnscheduledPid(u);
        if (!un) continue;
        char uHex[5];
        snprintf(uHex, sizeof(uHex), "%02X", (uint8_t)(un->pid & 0xFF));

        json += "{\"pid_hex\":\"";
        json += uHex;
        json += "\",\"name\":\"";
        json += un->name;
        json += "\",\"reason\":\"";
        json += unscheduledReasonToString(un->reason);
        json += "\"}";
    }

    json += "]}";
    _server.send(200, "application/json", json);
}

void MiniWebServer::handleApiConnect() {
    bool ok = _bt.connect();
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
    _server.send(ok ? 200 : 500, "application/json", buf);
}

void MiniWebServer::handleApiDisconnect() {
    _bt.disconnect();
    _server.send(200, "application/json", "{\"status\":\"ok\"}");
}

void MiniWebServer::handleApiReconnect() {
    bool ok = _bt.reconnect();
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
    _server.send(ok ? 200 : 500, "application/json", buf);
}

void MiniWebServer::handleApiObdInit() {
    if (_diagOpGetter && _diagOpGetter() != DIAG_OP_IDLE) {
        char buf[96];
        snprintf(buf, sizeof(buf), "{\"status\":\"busy\",\"operation\":\"%s\"}",
                 diagnosticOpStateToString(_diagOpGetter()));
        _server.send(409, "application/json", buf);
        return;
    }
    if (!_bt.isConnected()) {
        _server.send(400, "application/json", "{\"status\":\"error\",\"reason\":\"NOT_CONNECTED\"}");
        return;
    }
    if (_diagOpRequester) {
        if (_diagOpRequester(DIAG_OP_MANUAL_INIT)) {
            _server.send(202, "application/json", "{\"status\":\"accepted\",\"operation\":\"MANUAL_INIT\"}");
        } else {
            _server.send(500, "application/json", "{\"status\":\"error\",\"reason\":\"FAILED_TO_START_TASK\"}");
        }
    } else {
        bool ok = _elm.initialize();
        char buf[64];
        snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
        _server.send(ok ? 200 : 500, "application/json", buf);
    }
}

void MiniWebServer::handleApiObdScan() {
    if (_diagOpGetter && _diagOpGetter() != DIAG_OP_IDLE) {
        char buf[96];
        snprintf(buf, sizeof(buf), "{\"status\":\"busy\",\"operation\":\"%s\"}",
                 diagnosticOpStateToString(_diagOpGetter()));
        _server.send(409, "application/json", buf);
        return;
    }
    if (!_elm.isReady()) {
        _server.send(400, "application/json", "{\"status\":\"error\",\"reason\":\"ELM_NOT_READY\"}");
        return;
    }
    if (_diagOpRequester) {
        if (_diagOpRequester(DIAG_OP_MANUAL_SCAN)) {
            _server.send(202, "application/json", "{\"status\":\"accepted\",\"operation\":\"MANUAL_SCAN\"}");
        } else {
            _server.send(500, "application/json", "{\"status\":\"error\",\"reason\":\"FAILED_TO_START_TASK\"}");
        }
    } else {
        bool ok = _scanner.scanSupportedPids();
        char buf[64];
        snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
        _server.send(ok ? 200 : 500, "application/json", buf);
    }
}

void MiniWebServer::handleApiAcqStart() {
    bool ok = _scheduler.start();
    char buf[96];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\",\"session_id\":\"%s\"}", 
             ok ? "ok" : "failed", _scheduler.getSessionId());
    _server.send(ok ? 200 : 400, "application/json", buf);
}

void MiniWebServer::handleApiAcqStop() {
    bool ok = _scheduler.stop();
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
    _server.send(ok ? 200 : 400, "application/json", buf);
}

void MiniWebServer::handleApiAcqPause() {
    bool ok = _scheduler.pause();
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
    _server.send(ok ? 200 : 400, "application/json", buf);
}

void MiniWebServer::handleApiAcqResume() {
    bool ok = _scheduler.resume();
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
    _server.send(ok ? 200 : 400, "application/json", buf);
}

void MiniWebServer::handleApiStorageStatus() {
    StorageInfo info;
    StorageMetrics metrics;
    _logger.getStorageInfo(info);
    _logger.getStorageMetrics(metrics);

    uint64_t freeMB = info.free_bytes / (1024ULL * 1024ULL);
    uint64_t totalMB = info.total_bytes / (1024ULL * 1024ULL);

    char json[512];
    snprintf(json, sizeof(json),
        "{"
        "\"status\":\"%s\","
        "\"card_present\":%s,"
        "\"card_type\":\"%s\","
        "\"total_mb\":%llu,"
        "\"free_mb\":%llu,"
        "\"recording\":%s,"
        "\"current_session\":\"%s\","
        "\"samples_written\":%u,"
        "\"samples_dropped\":%u,"
        "\"write_errors\":%u"
        "}",
        storageStatusToString(info.status),
        info.card_present ? "true" : "false",
        info.card_type,
        (unsigned long long)totalMB,
        (unsigned long long)freeMB,
        _logger.isSessionActive() ? "true" : "false",
        _logger.getCurrentSessionId(),
        (unsigned int)metrics.samples_written,
        (unsigned int)metrics.samples_dropped,
        (unsigned int)metrics.write_errors
    );

    _server.send(200, "application/json", json);
}

void MiniWebServer::handleApiSessions() {
    SessionSummary summaries[SEYYANEN_MAX_SESSIONS_LIST];
    size_t count = _logger.listSessions(summaries, SEYYANEN_MAX_SESSIONS_LIST);

    String json = "{\"count\":";
    json += count;
    json += ",\"sessions\":[";

    for (size_t i = 0; i < count; ++i) {
        if (i > 0) json += ",";
        json += "{\"session_id\":\"";
        json += summaries[i].session_id;
        json += "\",\"state\":\"";
        json += sessionStateToString(summaries[i].state);
        json += "\",\"sample_count\":";
        json += summaries[i].sample_count;
        json += ",\"size_bytes\":";
        json += String((unsigned long long)summaries[i].size_bytes);
        json += "}";
    }

    json += "]}";
    _server.send(200, "application/json", json);
}

void MiniWebServer::handleApiSessionMetadata() {
    if (!_server.hasArg("id")) {
        _server.send(400, "application/json", "{\"error\":\"Missing session id parameter\"}");
        return;
    }

    String id = _server.arg("id");
    if (!SdLogger::isValidSessionId(id.c_str())) {
        _server.send(400, "application/json", "{\"error\":\"Invalid session id format\"}");
        return;
    }

    String metaJson;
    if (_logger.readSessionMetadata(id.c_str(), metaJson)) {
        _server.send(200, "application/json", metaJson);
    } else {
        _server.send(404, "application/json", "{\"error\":\"Session metadata not found\"}");
    }
}

void MiniWebServer::handleApiSessionDownload() {
    if (!_server.hasArg("id")) {
        _server.send(400, "text/plain", "Missing id parameter");
        return;
    }

    String id = _server.arg("id");
    // Security Gate: Strict session ID sanitization
    if (!SdLogger::isValidSessionId(id.c_str())) {
        _server.send(400, "text/plain", "Security error: invalid session ID path");
        return;
    }

    // Active session download protection: In M-6, active recording sessions cannot be downloaded
    if (_logger.isSessionActive() && strcmp(_logger.getCurrentSessionId(), id.c_str()) == 0) {
        _server.send(400, "text/plain", "Active recording session cannot be downloaded while writing. Stop recording first.");
        return;
    }

    File f = _logger.openSessionFileForRead(id.c_str(), "session.csv");
    if (!f) {
        _server.send(404, "text/plain", "Session CSV file not found");
        return;
    }

    String disposition = "attachment; filename=\"" + id + "_session.csv\"";
    _server.sendHeader("Content-Disposition", disposition);
    _server.streamFile(f, "text/csv");
    f.close();
}

void MiniWebServer::handleApiRecordingStart() {
    if (!_logger.isReady()) {
        _server.send(400, "application/json", "{\"error\":\"MicroSD not ready or card missing\"}");
        return;
    }

    const char* sessId = _scheduler.getSessionId();
    if (!sessId || strlen(sessId) == 0) {
        sessId = "MINI-SESSION-MANUAL";
    }

    bool ok = _logger.startSession(sessId, _bt.getAdapterIdentity(), _elm.getProtocol(), _scanner);
    char buf[96];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\",\"session_id\":\"%s\"}", 
             ok ? "ok" : "failed", sessId);
    _server.send(ok ? 200 : 500, "application/json", buf);
}

void MiniWebServer::handleApiRecordingStop() {
    bool ok = _logger.stopSession();
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"status\":\"%s\"}", ok ? "ok" : "failed");
    _server.send(ok ? 200 : 500, "application/json", buf);
}

void MiniWebServer::handleNotFound() {
    _server.send(404, "text/plain", "404: Endpoint Not Found");
}
