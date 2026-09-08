function quotaAccounts(cached, snapshot) {
    if (!snapshot.configured) return []
    if (!snapshot.running) return cached || []
    return (cached || []).filter(function(q) {
        return (snapshot.accounts || []).some(function(a) { return a.name === q.name })
    })
}

function primaryWindows(windows) {
    var rows = windows || []
    var overall = rows.filter(function(row) { return /^weekly$/i.test(row.label || "") })
    if (overall.length) return overall
    var weekly = rows.filter(function(row) { return /weekly/i.test(row.label || "") })
    if (weekly.length) return weekly
    // Some plans have a monthly overall allowance instead of a weekly one.
    return rows.filter(function(row) { return /^monthly$/i.test(row.label || "") })
}

function visibleWindows(windows, expanded) {
    return expanded ? (windows || []) : primaryWindows(windows)
}

function planLabel(provider, plan) {
    var raw = String(plan || "").trim()
    if (!raw) return ""
    if (provider === "codex") {
        var normalized = raw.toLowerCase().replace(/[-_ ]/g, "")
        // Codex's wire identifiers distinguish Pro Lite (5x) from Pro (20x).
        if (normalized === "prolite" || normalized === "pro5x") return "PRO · 5×"
        if (normalized === "pro" || normalized === "pro20x") return "PRO · 20×"
    }
    return raw.replace(/[_-]/g, " ").toUpperCase()
}

function maskEmails(text, enabled) {
    var value = String(text || "")
    return enabled ? value.replace(/[^\s<>"']+@[^\s<>"']+/g, "[email hidden]") : value
}
