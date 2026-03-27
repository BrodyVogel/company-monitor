// Currency formatting helper
function formatPrice(price, currency) {
    if (price == null) return "—";
    const symbols = { USD: "$", EUR: "€", GBP: "£", JPY: "¥" };
    const symbol = symbols[currency] || "$";
    if (currency === "JPY") {
        return symbol + Math.round(price).toLocaleString("en-US");
    }
    return symbol + price.toFixed(2);
}

// Date formatting helper — returns "Mar 19" style
function formatShortDate(dateStr) {
    if (!dateStr) return null;
    const d = new Date(dateStr);
    if (isNaN(d)) return dateStr;
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return months[d.getMonth()] + " " + d.getDate();
}

// Days since a date
function daysSince(dateStr) {
    if (!dateStr) return Infinity;
    const d = new Date(dateStr);
    if (isNaN(d)) return Infinity;
    return Math.floor((Date.now() - d.getTime()) / (1000 * 60 * 60 * 24));
}

// Rating badge class
function ratingBadgeClass(rating) {
    if (!rating) return "badge-inline";
    const r = rating.toLowerCase().replace(/\s+/g, "-");
    if (r === "strong-buy" || r === "outperform") return "badge-" + r;
    if (r === "inline") return "badge-inline";
    if (r === "underperform") return "badge-underperform";
    if (r === "sell") return "badge-sell";
    return "badge-inline";
}

// Toast notification
function showToast(message, type) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = "px-4 py-3 rounded-lg shadow-lg text-white text-sm max-w-sm transition-opacity duration-300 " +
        (type === "error" ? "bg-red-600" : "bg-green-600");
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Dismiss an alert
async function dismissAlert(alertId, bannerEl) {
    try {
        const res = await fetch(`/api/alerts/${alertId}/acknowledge`, { method: "PUT" });
        if (res.ok) {
            bannerEl.remove();
        } else {
            showToast("Failed to dismiss alert", "error");
        }
    } catch {
        showToast("Failed to dismiss alert", "error");
    }
}

// Render alert banners
function renderAlertBanners(companies) {
    const container = document.getElementById("alert-banners");
    container.innerHTML = "";

    for (const c of companies) {
        if (!c._alerts) continue;
        for (const alert of c._alerts) {
            if (alert.tier !== "action_required" || !alert.is_active) continue;
            const banner = document.createElement("div");
            banner.className = "alert-action-required border rounded-lg px-4 py-3 mb-3 flex items-center justify-between";
            banner.innerHTML = `
                <div>
                    <span class="font-semibold">${escapeHtml(c.name)}</span>
                    <span class="mx-2">—</span>
                    <span>${escapeHtml(alert.title)}</span>
                </div>
                <button class="ml-4 text-red-800 hover:text-red-950 font-medium text-sm flex-shrink-0">Dismiss</button>
            `;
            banner.querySelector("button").addEventListener("click", () => dismissAlert(alert.id, banner));
            container.appendChild(banner);
        }
    }
}

// Render company table
function renderCompanyTable(companies) {
    const container = document.getElementById("company-table-container");
    const emptyState = document.getElementById("empty-state");

    if (companies.length === 0) {
        container.innerHTML = "";
        emptyState.classList.remove("hidden");
        return;
    }
    emptyState.classList.add("hidden");

    const html = `
    <div class="overflow-x-auto">
        <table class="w-full bg-white rounded-lg border border-gray-200">
            <thead>
                <tr class="border-b border-gray-200 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <th class="px-4 py-3">Company</th>
                    <th class="px-4 py-3">Ticker</th>
                    <th class="px-4 py-3">Rating</th>
                    <th class="px-4 py-3">Price</th>
                    <th class="px-4 py-3">Target</th>
                    <th class="px-4 py-3">Upside</th>
                    <th class="px-4 py-3">Suggested</th>
                    <th class="px-4 py-3">Materials</th>
                    <th class="px-4 py-3">Last Sweep</th>
                    <th class="px-4 py-3">Alerts</th>
                    <th class="px-4 py-3">Signal</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
                ${companies.map(c => renderCompanyRow(c)).join("")}
            </tbody>
        </table>
    </div>`;
    container.innerHTML = html;
}

function renderCompanyRow(c) {
    const upside = c.upside_pct;
    const upsideColor = upside != null ? (upside >= 0 ? "text-green-600" : "text-red-600") : "";
    const upsideText = upside != null ? (upside >= 0 ? "+" : "") + upside.toFixed(1) + "%" : "—";

    const materialsFormatted = formatShortDate(c.materials_as_of) || "—";
    const materialsStale = daysSince(c.materials_as_of) > 90;

    const sweepFormatted = c.last_sweep_at ? formatShortDate(c.last_sweep_at) : "Never";
    const sweepStale = c.last_sweep_at ? daysSince(c.last_sweep_at) > 7 : true;

    const alertCounts = c.alert_counts || {};
    const redCount = alertCounts["action_required"] || 0;
    const yellowCount = alertCounts["watch"] || 0;

    const suggested = c.suggested_rating || "";
    const suggestedDiffers = suggested && suggested !== c.current_rating;

    // Signal dot
    let signalColor = "bg-green-500";
    if (redCount > 0) signalColor = "bg-red-500";
    else if (yellowCount > 0) signalColor = "bg-yellow-400";

    return `
    <tr class="hover:bg-gray-50">
        <td class="px-4 py-3 text-sm">
            <a href="/company/${encodeURIComponent(c.ticker)}" class="text-blue-600 hover:underline font-medium">${escapeHtml(c.name)}</a>
        </td>
        <td class="px-4 py-3 text-sm text-gray-700">${escapeHtml(c.ticker)}</td>
        <td class="px-4 py-3 text-sm">
            <span class="inline-block px-2 py-0.5 rounded text-xs font-medium ${ratingBadgeClass(c.current_rating)}">${escapeHtml(c.current_rating)}</span>
        </td>
        <td class="px-4 py-3 text-sm text-gray-700">${formatPrice(c.current_price, c.currency)}</td>
        <td class="px-4 py-3 text-sm text-gray-700">${formatPrice(c.blended_price_target, c.currency)}</td>
        <td class="px-4 py-3 text-sm ${upsideColor} font-medium">${upsideText}</td>
        <td class="px-4 py-3 text-sm">
            <span class="inline-block px-2 py-0.5 rounded text-xs font-medium ${ratingBadgeClass(suggested)}">${escapeHtml(suggested)}</span>
            ${suggestedDiffers ? '<span class="ml-1 text-yellow-500" title="Differs from current rating">&#9888;</span>' : ""}
        </td>
        <td class="px-4 py-3 text-sm ${materialsStale ? 'text-red-600 font-medium' : 'text-gray-700'}">${materialsFormatted}</td>
        <td class="px-4 py-3 text-sm ${sweepStale ? 'text-yellow-600 font-medium' : 'text-gray-700'}">${sweepFormatted}</td>
        <td class="px-4 py-3 text-sm">
            ${redCount > 0 ? `<span class="inline-block bg-red-100 text-red-700 text-xs font-medium px-1.5 py-0.5 rounded mr-1">${redCount}</span>` : ""}
            ${yellowCount > 0 ? `<span class="inline-block bg-yellow-100 text-yellow-700 text-xs font-medium px-1.5 py-0.5 rounded">${yellowCount}</span>` : ""}
            ${redCount === 0 && yellowCount === 0 ? '<span class="text-gray-400 text-xs">—</span>' : ""}
        </td>
        <td class="px-4 py-3">
            <span class="inline-block w-3 h-3 rounded-full ${signalColor}"></span>
        </td>
    </tr>`;
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// Import flow
function setupImport() {
    const fileInput = document.getElementById("file-input");
    const importBtn = document.getElementById("import-btn");
    const emptyImportBtn = document.getElementById("empty-import-btn");

    function triggerImport() {
        fileInput.click();
    }

    importBtn.addEventListener("click", triggerImport);
    emptyImportBtn.addEventListener("click", triggerImport);

    fileInput.addEventListener("change", async () => {
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch("/api/import", {
                method: "POST",
                body: formData,
            });
            let data;
            try {
                data = await res.json();
            } catch (parseErr) {
                console.error("Failed to parse import response:", parseErr);
                showToast(res.ok ? "Import successful" : `Import failed (status ${res.status})`, res.ok ? "success" : "error");
                fileInput.value = "";
                setTimeout(loadDashboard, 2000);
                return;
            }
            if (res.ok) {
                const summary = data.summary || "Import successful";
                showToast(summary, "success");
            } else {
                showToast(data.detail || "Import failed", "error");
            }
        } catch (err) {
            console.error("Import network error:", err);
            showToast("Import failed — network error", "error");
        }

        fileInput.value = "";
        setTimeout(loadDashboard, 2000);
    });
}

// Fetch alerts for banner display
async function fetchAlertsForCompanies(companies) {
    const withAlerts = await Promise.all(companies.map(async (c) => {
        try {
            const res = await fetch(`/api/companies/${encodeURIComponent(c.ticker)}`);
            if (res.ok) {
                const detail = await res.json();
                c._alerts = detail.alerts || [];
            }
        } catch {
            c._alerts = [];
        }
        return c;
    }));
    return withAlerts;
}

// Main load
async function loadDashboard() {
    try {
        const res = await fetch("/api/companies");
        if (!res.ok) {
            showToast("Failed to load companies", "error");
            return;
        }
        let companies = await res.json();

        // Check if any company has action_required alerts
        const hasActionRequired = companies.some(c => (c.alert_counts || {})["action_required"] > 0);

        if (hasActionRequired) {
            companies = await fetchAlertsForCompanies(companies);
        }

        renderAlertBanners(companies);
        renderCompanyTable(companies);
    } catch {
        showToast("Failed to load dashboard", "error");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    setupImport();
    loadDashboard();
});
