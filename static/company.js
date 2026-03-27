// ── Helpers (duplicated from dashboard.js for standalone use) ──

function formatPrice(price, currency) {
    if (price == null) return "\u2014";
    const symbols = { USD: "$", EUR: "\u20ac", GBP: "\u00a3", JPY: "\u00a5" };
    const symbol = symbols[currency] || "$";
    if (currency === "JPY") return symbol + Math.round(price).toLocaleString("en-US");
    return symbol + price.toFixed(2);
}

function formatShortDate(dateStr) {
    if (!dateStr) return null;
    const d = new Date(dateStr);
    if (isNaN(d)) return dateStr;
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return months[d.getMonth()] + " " + d.getDate();
}

function formatFullDate(dateStr) {
    if (!dateStr) return "\u2014";
    const d = new Date(dateStr);
    if (isNaN(d)) return dateStr;
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return months[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
}

function daysSince(dateStr) {
    if (!dateStr) return Infinity;
    const d = new Date(dateStr);
    if (isNaN(d)) return Infinity;
    return Math.floor((Date.now() - d.getTime()) / (1000 * 60 * 60 * 24));
}

function daysUntil(dateStr) {
    if (!dateStr) return Infinity;
    const d = new Date(dateStr);
    if (isNaN(d)) return Infinity;
    return Math.ceil((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

function ratingBadgeClass(rating) {
    if (!rating) return "badge-inline";
    const r = rating.toLowerCase().replace(/\s+/g, "-");
    if (r === "strong-buy" || r === "outperform") return "badge-" + r;
    if (r === "inline") return "badge-inline";
    if (r === "underperform") return "badge-underperform";
    if (r === "sell") return "badge-sell";
    return "badge-inline";
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function showToast(message, type) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = "px-4 py-3 rounded-lg shadow-lg text-white text-sm max-w-sm transition-opacity duration-300 " +
        (type === "error" ? "bg-red-600" : "bg-green-600");
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 300); }, 3000);
}

function safeParse(jsonStr) {
    if (!jsonStr) return null;
    if (typeof jsonStr === "object") return jsonStr;
    try { return JSON.parse(jsonStr); } catch { return null; }
}

// ── Global state ──
let DATA = null;
const TICKER = document.getElementById("company-page").dataset.ticker;

// ── Main load ──
async function loadCompany() {
    try {
        const res = await fetch(`/api/companies/${encodeURIComponent(TICKER)}`);
        if (!res.ok) {
            document.getElementById("loading").textContent = "Company not found.";
            return;
        }
        DATA = await res.json();
        document.getElementById("loading").classList.add("hidden");
        document.getElementById("company-content").classList.remove("hidden");
        renderAll();
    } catch {
        document.getElementById("loading").textContent = "Failed to load company data.";
    }
}

function renderAll() {
    renderHeader();
    renderPriceCards();
    renderAlerts();
    renderScenarios();
    renderIndicators();
    renderKeyEvents();
    renderDiscoveries();
    renderChangeLog();
}

// ── Header ──
function renderHeader() {
    const c = DATA.company;
    const suggestedDiffers = c.suggested_rating && c.suggested_rating !== c.current_rating;

    const materialsDate = formatShortDate(c.materials_as_of) || "N/A";
    const materialsStale = daysSince(c.materials_as_of) > 90;
    const sweepDate = c.last_sweep_at ? formatShortDate(c.last_sweep_at) : "Never";
    const sweepStale = c.last_sweep_at ? daysSince(c.last_sweep_at) > 7 : true;

    document.getElementById("header-section").innerHTML = `
        <div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div>
                <h1 class="text-2xl font-bold text-gray-900">${escapeHtml(c.name)}</h1>
                <p class="text-sm text-gray-500">${escapeHtml(c.ticker)}${c.exchange ? "." + escapeHtml(c.exchange) : ""} &middot; ${escapeHtml(c.currency)}</p>
            </div>
            <div class="flex items-center gap-3">
                <span class="inline-block px-3 py-1 rounded text-sm font-medium ${ratingBadgeClass(c.current_rating)}">${escapeHtml(c.current_rating)}</span>
                ${suggestedDiffers ? `<span class="text-sm text-yellow-600 font-medium">&#9888; Suggested: ${escapeHtml(c.suggested_rating)}</span>` : ""}
                <button id="import-btn" class="bg-blue-600 text-white text-sm px-3 py-1.5 rounded hover:bg-blue-700">Import</button>
            </div>
        </div>
        <div class="mt-2 text-xs text-gray-500">
            Materials: <span class="${materialsStale ? "text-red-600 font-medium" : ""}">${materialsDate}</span>
            &middot; Last Sweep: <span class="${sweepStale ? "text-yellow-600 font-medium" : ""}">${sweepDate}</span>
        </div>
    `;
    document.getElementById("import-btn").addEventListener("click", () => document.getElementById("file-input").click());
}

// ── Price Cards ──
function renderPriceCards() {
    const c = DATA.company;
    const upside = c.upside_pct;
    const upsideColor = upside != null ? (upside >= 0 ? "text-green-600" : "text-red-600") : "";
    const upsideText = upside != null ? (upside >= 0 ? "+" : "") + upside.toFixed(1) + "%" : "\u2014";

    document.getElementById("price-cards").innerHTML = `
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <p class="text-xs text-gray-500 uppercase tracking-wide mb-1">Price</p>
            <p class="text-xl font-semibold text-gray-900">${formatPrice(c.current_price, c.currency)}</p>
        </div>
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <p class="text-xs text-gray-500 uppercase tracking-wide mb-1">Blended Target</p>
            <p class="text-xl font-semibold text-gray-900">${formatPrice(c.blended_price_target, c.currency)}</p>
        </div>
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <p class="text-xs text-gray-500 uppercase tracking-wide mb-1">Upside</p>
            <p class="text-xl font-semibold ${upsideColor}">${upsideText}</p>
        </div>
    `;
}

// ── Alerts ──
function renderAlerts() {
    const alerts = DATA.alerts;
    const section = document.getElementById("alerts-section");
    if (!alerts || alerts.length === 0) { section.classList.add("hidden"); return; }
    section.classList.remove("hidden");

    let html = `<h2 class="text-lg font-semibold text-gray-900 mb-3">Active Alerts</h2>`;
    for (const a of alerts) {
        const tierClass = a.tier === "action_required" ? "border-l-red-500" : "border-l-yellow-400";
        const tierBadge = a.tier === "action_required"
            ? '<span class="inline-block bg-red-100 text-red-700 text-xs font-medium px-2 py-0.5 rounded">Action Required</span>'
            : '<span class="inline-block bg-yellow-100 text-yellow-700 text-xs font-medium px-2 py-0.5 rounded">Watch</span>';

        const sources = safeParse(a.sources);
        let sourcesHtml = "";
        if (sources && Array.isArray(sources)) {
            sourcesHtml = '<ul class="mt-1 text-xs text-blue-600">' +
                sources.map(s => {
                    if (typeof s === "object" && s.url) return `<li><a href="${escapeHtml(s.url)}" target="_blank" class="hover:underline">${escapeHtml(s.name || s.url)}</a></li>`;
                    if (typeof s === "string") return `<li>${escapeHtml(s)}</li>`;
                    return "";
                }).join("") + "</ul>";
        }

        html += `
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 border-l-4 ${tierClass} p-4 mb-3 flex items-start justify-between gap-4">
            <div class="flex-1">
                <div class="flex items-center gap-2 mb-1">${tierBadge} <span class="font-medium text-sm text-gray-900">${escapeHtml(a.title)}</span></div>
                <p class="text-sm text-gray-600">${escapeHtml(a.description)}</p>
                ${a.change_rationale ? `<p class="text-xs text-gray-500 mt-1">${escapeHtml(a.change_rationale)}</p>` : ""}
                ${sourcesHtml}
            </div>
            <button onclick="dismissAlert(${a.id})" class="text-gray-400 hover:text-gray-600 text-sm flex-shrink-0">Dismiss</button>
        </div>`;
    }
    section.innerHTML = html;
}

async function dismissAlert(alertId) {
    try {
        const res = await fetch(`/api/alerts/${alertId}/acknowledge`, { method: "PUT" });
        if (res.ok) { await loadCompany(); } else { showToast("Failed to dismiss alert", "error"); }
    } catch { showToast("Failed to dismiss alert", "error"); }
}

// ── Scenarios ──
function renderScenarios() {
    const scenarios = DATA.scenarios;
    const c = DATA.company;
    if (!scenarios || scenarios.length === 0) return;

    let rows = scenarios.map(s => `
        <tr class="hover:bg-gray-50">
            <td class="px-4 py-2 text-sm font-medium text-gray-900">${escapeHtml(s.name)}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${s.raw_weight != null ? (s.raw_weight * 100).toFixed(0) + "%" : "\u2014"}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${s.effective_weight != null ? (s.effective_weight * 100).toFixed(0) + "%" : "\u2014"}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${formatPrice(s.implied_price, c.currency)}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${escapeHtml(s.summary)}</td>
        </tr>`).join("");

    document.getElementById("scenarios-section").innerHTML = `
        <h2 class="text-lg font-semibold text-gray-900 mb-3">Scenarios</h2>
        <div class="overflow-x-auto">
            <table class="w-full bg-white rounded-lg border border-gray-200">
                <thead>
                    <tr class="border-b border-gray-200 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        <th class="px-4 py-3">Scenario</th>
                        <th class="px-4 py-3">Raw Weight</th>
                        <th class="px-4 py-3">Effective Weight</th>
                        <th class="px-4 py-3">Implied Price</th>
                        <th class="px-4 py-3">Summary</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-100">${rows}</tbody>
            </table>
        </div>`;
}

// ── Indicators ──
function renderIndicators() {
    const indicators = DATA.indicators;
    if (!indicators || indicators.length === 0) return;

    let rows = indicators.map((ind, idx) => {
        const statusDot = ind.status === "action_required" ? "bg-red-500"
            : ind.status === "watch" ? "bg-yellow-400" : "bg-green-500";
        const lastChecked = ind.last_checked_at ? formatFullDate(ind.last_checked_at) : "Never";

        return `
        <tr class="hover:bg-gray-50 cursor-pointer" onclick="toggleReadings(${idx}, ${ind.id})">
            <td class="px-4 py-2 text-sm font-medium text-gray-900">${escapeHtml(ind.name)}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${escapeHtml(ind.current_value) || "\u2014"}</td>
            <td class="px-4 py-2 text-sm text-red-600">${escapeHtml(ind.bear_threshold) || "\u2014"}</td>
            <td class="px-4 py-2 text-sm text-green-600">${escapeHtml(ind.bull_threshold) || "\u2014"}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${escapeHtml(ind.check_frequency)}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${escapeHtml(ind.data_source)}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${lastChecked}</td>
            <td class="px-4 py-2"><span class="inline-block w-3 h-3 rounded-full ${statusDot}"></span></td>
        </tr>
        <tr id="readings-row-${idx}" class="hidden">
            <td colspan="8" class="px-4 py-3 bg-gray-50">
                <div id="readings-content-${idx}" class="text-sm text-gray-500">Loading readings...</div>
            </td>
        </tr>`;
    }).join("");

    document.getElementById("indicators-section").innerHTML = `
        <h2 class="text-lg font-semibold text-gray-900 mb-3">Indicators</h2>
        <div class="overflow-x-auto">
            <table class="w-full bg-white rounded-lg border border-gray-200">
                <thead>
                    <tr class="border-b border-gray-200 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        <th class="px-4 py-3">Indicator</th>
                        <th class="px-4 py-3">Current Value</th>
                        <th class="px-4 py-3">Bear Threshold</th>
                        <th class="px-4 py-3">Bull Threshold</th>
                        <th class="px-4 py-3">Frequency</th>
                        <th class="px-4 py-3">Source</th>
                        <th class="px-4 py-3">Last Checked</th>
                        <th class="px-4 py-3">Status</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-100">${rows}</tbody>
            </table>
        </div>`;
}

const loadedReadings = {};

async function toggleReadings(idx, indicatorId) {
    const row = document.getElementById(`readings-row-${idx}`);
    if (!row.classList.contains("hidden")) { row.classList.add("hidden"); return; }
    row.classList.remove("hidden");

    if (loadedReadings[indicatorId]) {
        renderReadingsContent(idx, loadedReadings[indicatorId]);
        return;
    }

    try {
        const res = await fetch(`/api/indicators/${indicatorId}/readings`);
        if (res.ok) {
            const readings = await res.json();
            loadedReadings[indicatorId] = readings;
            renderReadingsContent(idx, readings);
        } else {
            document.getElementById(`readings-content-${idx}`).textContent = "Failed to load readings.";
        }
    } catch {
        document.getElementById(`readings-content-${idx}`).textContent = "Failed to load readings.";
    }
}

function renderReadingsContent(idx, readings) {
    const el = document.getElementById(`readings-content-${idx}`);
    if (!readings || readings.length === 0) { el.textContent = "No readings recorded."; return; }

    let html = `<table class="w-full text-sm">
        <thead><tr class="text-xs text-gray-500 uppercase">
            <th class="text-left py-1 pr-3">Date</th>
            <th class="text-left py-1 pr-3">Value</th>
            <th class="text-left py-1 pr-3">Material Change</th>
            <th class="text-left py-1 pr-3">Context</th>
            <th class="text-left py-1 pr-3">Confidence</th>
        </tr></thead><tbody>`;

    for (const r of readings) {
        const mc = r.material_change ? '<span class="text-red-600 font-medium">Yes</span>' : '<span class="text-gray-400">No</span>';
        html += `<tr class="border-t border-gray-100">
            <td class="py-1 pr-3">${formatFullDate(r.sweep_date)}</td>
            <td class="py-1 pr-3">${escapeHtml(r.value_text)}</td>
            <td class="py-1 pr-3">${mc}</td>
            <td class="py-1 pr-3">${escapeHtml(r.context) || "\u2014"}</td>
            <td class="py-1 pr-3">${escapeHtml(r.confidence) || "\u2014"}</td>
        </tr>`;
    }
    html += "</tbody></table>";
    el.innerHTML = html;
}

// ── Key Events ──
function renderKeyEvents() {
    const events = DATA.key_events;
    if (!events || events.length === 0) return;

    let rows = events.map(e => {
        let statusHtml;
        if (e.occurred) {
            statusHtml = `<span class="text-green-600">&#10003; ${formatFullDate(e.occurred_date)}</span>`;
        } else if (e.expected_date && daysUntil(e.expected_date) < 0) {
            statusHtml = '<span class="inline-block bg-red-100 text-red-700 text-xs font-medium px-2 py-0.5 rounded">Overdue</span>';
        } else {
            const days = daysUntil(e.expected_date);
            const label = days === Infinity ? "Upcoming" : `${days}d away`;
            statusHtml = `<span class="inline-block bg-yellow-100 text-yellow-700 text-xs font-medium px-2 py-0.5 rounded">${label}</span>`;
        }

        const details = e.outcome_summary || e.why_it_matters || "";
        const affected = safeParse(e.indicators_affected);
        const affectedHtml = affected && Array.isArray(affected) ? `<div class="text-xs text-gray-400 mt-1">Indicators: ${affected.map(a => escapeHtml(a)).join(", ")}</div>` : "";

        return `<tr class="hover:bg-gray-50">
            <td class="px-4 py-2 text-sm font-medium text-gray-900">${escapeHtml(e.event)}</td>
            <td class="px-4 py-2 text-sm text-gray-700">${formatFullDate(e.expected_date)}</td>
            <td class="px-4 py-2 text-sm">${statusHtml}</td>
            <td class="px-4 py-2 text-sm text-gray-600">${escapeHtml(details)}${affectedHtml}</td>
        </tr>`;
    }).join("");

    document.getElementById("events-section").innerHTML = `
        <h2 class="text-lg font-semibold text-gray-900 mb-3">Key Events</h2>
        <div class="overflow-x-auto">
            <table class="w-full bg-white rounded-lg border border-gray-200">
                <thead>
                    <tr class="border-b border-gray-200 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        <th class="px-4 py-3">Event</th>
                        <th class="px-4 py-3">Expected Date</th>
                        <th class="px-4 py-3">Status</th>
                        <th class="px-4 py-3">Details</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-100">${rows}</tbody>
            </table>
        </div>`;
}

// ── Pending Discoveries ──
function renderDiscoveries() {
    const section = document.getElementById("discoveries-section");
    // Find the most recent sweep change_log entry
    const sweepEntry = DATA.change_log.find(e => e.action === "sweep" && !e.is_undone);
    if (!sweepEntry) { section.classList.add("hidden"); return; }

    const details = safeParse(sweepEntry.details);
    if (!details) { section.classList.add("hidden"); return; }

    const discovered = (details.events && details.events.discovered) || [];
    const pending = details.pending_discoveries || {};
    const pendingEvents = pending.pending_events || [];
    const suggestedIndicators = pending.suggested_indicators || [];

    const allItems = [...discovered];
    if (allItems.length === 0 && pendingEvents.length === 0 && suggestedIndicators.length === 0) {
        section.classList.add("hidden");
        return;
    }

    // Merge: use discovered list, but also include pending_events/suggested_indicators if not already there
    const itemMap = new Map();
    for (const item of allItems) {
        itemMap.set((item.event || item.name || "").toLowerCase(), item);
    }
    for (const item of pendingEvents) {
        const key = (item.event || item.name || "").toLowerCase();
        if (!itemMap.has(key)) { itemMap.set(key, item); allItems.push(item); }
    }
    for (const item of suggestedIndicators) {
        const key = (item.event || item.name || "").toLowerCase();
        if (!itemMap.has(key)) { itemMap.set(key, item); allItems.push(item); }
    }

    if (allItems.length === 0) { section.classList.add("hidden"); return; }
    section.classList.remove("hidden");

    let html = '<h2 class="text-lg font-semibold text-gray-900 mb-3">Pending Discoveries</h2>';

    for (let i = 0; i < allItems.length; i++) {
        const item = allItems[i];
        const eventName = escapeHtml(item.event || item.name || "Unknown");
        const date = item.date ? formatFullDate(item.date) : "\u2014";
        const relevance = escapeHtml(item.relevance || "");
        const materialFlag = item.material_change
            ? '<span class="inline-block bg-red-100 text-red-700 text-xs font-medium px-2 py-0.5 rounded ml-2">Material Change</span>'
            : '';

        let buttons = '';
        if (item.add_to_tracked_events) {
            const evData = item.add_to_tracked_events;
            buttons += `<button onclick='addDiscoveredEvent(${JSON.stringify(evData).replace(/'/g, "&#39;")})' class="bg-blue-600 text-white text-xs px-3 py-1 rounded hover:bg-blue-700 mr-2">Add to Tracked Events</button>`;
        }
        if (item.suggested_indicator) {
            const indData = item.suggested_indicator;
            buttons += `<button onclick='addDiscoveredIndicator(${JSON.stringify(indData).replace(/'/g, "&#39;")})' class="bg-green-600 text-white text-xs px-3 py-1 rounded hover:bg-green-700">Add Indicator</button>`;
        }

        html += `
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 border-l-4 border-l-purple-400 p-4 mb-3">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <div class="flex items-center mb-1">
                        <span class="font-medium text-sm text-gray-900">${eventName}</span>
                        ${materialFlag}
                    </div>
                    <p class="text-xs text-gray-500">Date: ${date}</p>
                    ${relevance ? `<p class="text-sm text-gray-600 mt-1">${relevance}</p>` : ""}
                </div>
                <div class="flex items-center gap-2 flex-shrink-0 ml-4">${buttons}</div>
            </div>
        </div>`;
    }

    section.innerHTML = html;
}

async function addDiscoveredEvent(evData) {
    try {
        const body = {
            event: evData.event || evData.name,
            expected_date: evData.expected_date || null,
            why_it_matters: evData.why_it_matters || null,
            indicators_affected: evData.indicators_affected || [],
        };
        const res = await fetch(`/api/companies/${encodeURIComponent(TICKER)}/key-events`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            showToast("Event added", "success");
            await loadCompany();
        } else {
            showToast("Failed to add event", "error");
        }
    } catch { showToast("Failed to add event", "error"); }
}

async function addDiscoveredIndicator(indData) {
    try {
        const body = {
            name: indData.name,
            current_value: indData.current_value || null,
            bear_threshold: indData.bear_threshold || null,
            bull_threshold: indData.bull_threshold || null,
            check_frequency: indData.check_frequency || "Weekly",
            data_source: indData.data_source || "",
        };
        const res = await fetch(`/api/companies/${encodeURIComponent(TICKER)}/indicators`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            showToast("Indicator added", "success");
            await loadCompany();
        } else {
            showToast("Failed to add indicator", "error");
        }
    } catch { showToast("Failed to add indicator", "error"); }
}

// ── Change Log ──
function renderChangeLog() {
    const log = DATA.change_log;
    if (!log || log.length === 0) return;

    // Find most recent non-undone entry (excluding undo entries themselves)
    const latestActive = log.find(e => !e.is_undone && e.action !== "undo");

    let html = '<h2 class="text-lg font-semibold text-gray-900 mb-3">Change Log</h2>';
    for (const entry of log) {
        const isUndone = entry.is_undone;
        const opacity = isUndone ? "opacity-50" : "";
        const actionColors = { onboard: "bg-blue-100 text-blue-700", sweep: "bg-green-100 text-green-700", update: "bg-orange-100 text-orange-700" };
        const badgeClass = actionColors[entry.action] || "bg-gray-100 text-gray-700";

        const isLatest = latestActive && entry.id === latestActive.id;
        const strikethrough = isUndone ? "line-through" : "";

        html += `
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-3 ${opacity}">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="text-xs text-gray-400">${formatFullDate(entry.created_at)}</span>
                    <span class="inline-block px-2 py-0.5 rounded text-xs font-medium ${badgeClass}">${escapeHtml(entry.action)}</span>
                    ${isUndone ? '<span class="inline-block px-2 py-0.5 rounded text-xs font-medium bg-gray-200 text-gray-500">Undone</span>' : ""}
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="toggleDetails(${entry.id})" class="text-xs text-blue-600 hover:underline">Expand</button>
                    ${isLatest && !isUndone && entry.action !== "undo" ? `<button onclick="undoChange(${entry.id})" class="text-xs text-red-500 hover:underline">Undo</button>` : ""}
                </div>
            </div>
            <p class="text-sm text-gray-700 mt-1" style="text-decoration: ${strikethrough}">${escapeHtml(entry.summary)}</p>
            <div id="details-${entry.id}" class="hidden mt-2">
                <pre class="text-xs bg-gray-50 p-3 rounded overflow-x-auto text-gray-600">${escapeHtml(formatDetails(entry.details))}</pre>
            </div>
        </div>`;
    }
    document.getElementById("changelog-section").innerHTML = html;
}

function formatDetails(details) {
    if (!details) return "No details";
    if (typeof details === "string") {
        try { return JSON.stringify(JSON.parse(details), null, 2); } catch { return details; }
    }
    return JSON.stringify(details, null, 2);
}

function toggleDetails(id) {
    document.getElementById(`details-${id}`).classList.toggle("hidden");
}

async function undoChange(changeLogId) {
    try {
        const res = await fetch(`/api/undo/${changeLogId}`, { method: "POST" });
        const data = await res.json();
        if (res.ok) {
            showToast(data.summary || "Undo successful", "success");
            await loadCompany();
        } else {
            showToast(data.detail || "Undo failed", "error");
        }
    } catch { showToast("Undo failed", "error"); }
}

// ── Delete Company ──
function setupDelete() {
    document.getElementById("delete-btn").addEventListener("click", async () => {
        if (!confirm(`Delete ${DATA.company.name} (${DATA.company.ticker})? This cannot be undone.`)) return;
        try {
            const res = await fetch(`/api/companies/${encodeURIComponent(TICKER)}`, { method: "DELETE" });
            if (res.ok) { window.location.href = "/"; }
            else { showToast("Delete failed", "error"); }
        } catch { showToast("Delete failed", "error"); }
    });
}

// ── Import ──
function setupImport() {
    document.getElementById("file-input").addEventListener("change", async () => {
        const file = document.getElementById("file-input").files[0];
        if (!file) return;
        const formData = new FormData();
        formData.append("file", file);
        try {
            const res = await fetch("/api/import", { method: "POST", body: formData });
            const data = await res.json();
            if (res.ok) { showToast(data.summary || "Import successful", "success"); }
            else { showToast(data.detail || "Import failed", "error"); }
        } catch { showToast("Import failed \u2014 network error", "error"); }
        document.getElementById("file-input").value = "";
        setTimeout(loadCompany, 2000);
    });
}

// ── Init ──
document.addEventListener("DOMContentLoaded", () => {
    setupImport();
    loadCompany().then(() => { if (DATA) setupDelete(); });
});
