let pollingTimer = null;
let pidsTimer = null;
let isRecording = false;

document.addEventListener("DOMContentLoaded", () => {
    fetchStatus();
    fetchPids();
    pollingTimer = setInterval(fetchStatus, 600);
    pidsTimer = setInterval(fetchPids, 2500);
});

async function fetchStatus() {
    try {
        const res = await fetch("/api/status");
        if (!res.ok) throw new Error("Network response not ok");
        const data = await res.json();
        updateUIStatus(data);
    } catch (err) {
        // Fallback UI indication
        const btBadge = document.getElementById("bt-badge");
        if (btBadge) {
            btBadge.className = "badge badge-disconnected";
            btBadge.textContent = "ESP32: OFFLINE";
        }
    }
}

function updateUIStatus(data) {
    // 1. Adapter Connection & Identity
    const btBadge = document.getElementById("bt-badge");
    const adapterState = document.getElementById("adapter-state");
    const adapterId = document.getElementById("adapter-identity");
    const protocol = document.getElementById("vehicle-protocol");
    const scanStatus = document.getElementById("scan-status");

    if (adapterState) adapterState.textContent = data.adapter_state || "UNKNOWN";
    if (adapterId) adapterId.textContent = data.adapter_identity || "UNKNOWN";
    if (protocol) protocol.textContent = data.protocol || "AUTO SEARCHING";
    if (scanStatus) scanStatus.textContent = data.scan_status || "PENDING";

    if (btBadge) {
        if (data.adapter_state === "CONNECTED") {
            btBadge.className = "badge badge-connected";
            btBadge.textContent = "BT: CONNECTED";
        } else if (data.adapter_state === "CONNECTING" || data.adapter_state === "RECONNECTING") {
            btBadge.className = "badge badge-warning";
            btBadge.textContent = "BT: " + data.adapter_state;
        } else {
            btBadge.className = "badge badge-disconnected";
            btBadge.textContent = "BT: DISCONNECTED";
        }
    }

    // 2. SD Card State
    const sdBadge = document.getElementById("sd-badge");
    if (sdBadge) {
        if (data.sd_available) {
            sdBadge.className = "badge badge-connected";
            sdBadge.textContent = "SD: READY";
        } else {
            sdBadge.className = "badge badge-warning";
            sdBadge.textContent = "SD: NOT DETECTED";
        }
    }

    // 3. Recording State & Controls
    isRecording = data.is_recording || false;
    const recBadge = document.getElementById("rec-badge");
    const btnStart = document.getElementById("btn-start");
    const btnStop = document.getElementById("btn-stop");
    const sessionLabel = document.getElementById("session-label");
    const fileLabel = document.getElementById("rec-file-label");

    if (sessionLabel) sessionLabel.textContent = "SESSION: " + (data.session_id || "--");
    if (fileLabel) fileLabel.textContent = data.current_file || "No active file";

    if (recBadge) {
        if (isRecording) {
            recBadge.className = "badge badge-recording";
            recBadge.textContent = "RECORDING";
        } else {
            recBadge.className = "badge badge-idle";
            recBadge.textContent = "IDLE";
        }
    }

    if (btnStart) btnStart.disabled = isRecording || !data.sd_available;
    if (btnStop) btnStop.disabled = !isRecording;

    // 4. Metrics
    const sampleCount = document.getElementById("sample-count");
    const sampleRate = document.getElementById("sample-rate");
    const avgLatency = document.getElementById("avg-latency");

    if (sampleCount) sampleCount.textContent = data.samples_logged || 0;
    if (sampleRate) sampleRate.textContent = (data.sample_rate_hz || 0).toFixed(1);
    if (avgLatency) avgLatency.textContent = data.last_latency_ms || 0;

    // 5. Update Live Gauge Values
    if (data.live_values) {
        updateGauge("rpm", data.live_values.rpm, 0);
        updateGauge("tps", data.live_values.tps, 1);
        updateGauge("speed", data.live_values.speed, 0);
        updateGauge("ect", data.live_values.ect, 0);
        updateGauge("map", data.live_values.map, 0);
        updateGauge("maf", data.live_values.maf, 2);
        updateGauge("stft", data.live_values.stft, 1);
        updateGauge("ltft", data.live_values.ltft, 1);
    }
}

function updateGauge(id, item, decimals) {
    const valEl = document.getElementById("val-" + id);
    const qualEl = document.getElementById("qual-" + id);
    if (!valEl || !qualEl) return;

    if (!item || item.status !== "VALID") {
        valEl.textContent = "--";
        qualEl.className = "status-pill status-invalid";
        qualEl.textContent = item ? item.status : "NO DATA";
        return;
    }

    valEl.textContent = Number(item.value).toFixed(decimals);
    qualEl.textContent = item.quality || "GOOD";

    switch (item.quality) {
        case "GOOD":
            qualEl.className = "status-pill status-good";
            break;
        case "DEGRADED":
            qualEl.className = "status-pill status-degraded";
            break;
        case "STALE":
            qualEl.className = "status-pill status-stale";
            break;
        default:
            qualEl.className = "status-pill status-invalid";
            break;
    }
}

async function fetchPids() {
    try {
        const res = await fetch("/api/pids");
        if (!res.ok) return;
        const data = await res.json();
        renderPidsTable(data);
    } catch (e) {
        // Ignore background polling errors
    }
}

function renderPidsTable(data) {
    const tbody = document.getElementById("pids-table-body");
    const countBadge = document.getElementById("supported-count");
    if (!tbody) return;

    if (!data.pids || data.pids.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-muted">No supported PIDs discovered yet.</td></tr>`;
        return;
    }

    if (countBadge) {
        countBadge.textContent = `${data.supported_count} Supported / ${data.pids.length} Registered`;
    }

    let html = "";
    data.pids.forEach(p => {
        const suppClass = p.supported ? "text-success" : "text-muted";
        const suppText = p.supported ? "SUPPORTED" : "UNSUPPORTED";
        const valStr = (p.supported && p.has_value) ? `${Number(p.value).toFixed(1)} ${p.unit}` : "--";
        const qualClass = p.quality === "GOOD" ? "status-good" : (p.quality === "STALE" ? "status-stale" : "status-invalid");

        html += `
            <tr>
                <td><code>01${p.pid_hex}</code></td>
                <td><strong>${p.name}</strong></td>
                <td>${p.interval_ms} ms</td>
                <td class="${suppClass}">${suppText}</td>
                <td><strong>${valStr}</strong></td>
                <td><span class="status-pill ${qualClass}">${p.quality || '--'}</span></td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
}

async function startRecording() {
    try {
        const btn = document.getElementById("btn-start");
        if (btn) btn.disabled = true;
        const res = await fetch("/api/record/start", { method: "POST" });
        await fetchStatus();
    } catch (err) {
        alert("Failed to start recording: " + err.message);
    }
}

async function stopRecording() {
    try {
        const btn = document.getElementById("btn-stop");
        if (btn) btn.disabled = true;
        const res = await fetch("/api/record/stop", { method: "POST" });
        await fetchStatus();
    } catch (err) {
        alert("Failed to stop recording: " + err.message);
    }
}
