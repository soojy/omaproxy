"""Normalize provider quota responses without exposing provider credentials."""
from datetime import datetime, timezone
import math
import time


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def reset_time(value):
    numeric = number(value)
    if numeric is not None:
        return numeric / 1000 if numeric > 100000000000 else numeric
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    return None


def window(label, used=None, reset=None, limit=None, consumed=None):
    used = number(used)
    return {"label": label, "used_percent": used,
            "remaining_percent": None if used is None else max(0, min(100, 100 - used)),
            "reset_at": reset_time(reset), "limit": number(limit), "used": number(consumed)}


def duration_label(seconds, fallback):
    value = number(seconds)
    if value is None:
        return fallback
    if value == 604800:
        return "Weekly"
    if 2419200 <= value <= 2678400:
        return "Monthly"
    if value >= 3600:
        return f"{value / 3600:g}-hour"
    return f"{value / 60:g}-minute"


def codex(payload, now=None):
    now = time.time() if now is None else now
    windows = []
    groups = [("", payload.get("rate_limit") or payload.get("rateLimit")),
              ("Code review · ", payload.get("code_review_rate_limit") or payload.get("codeReviewRateLimit"))]
    for extra in payload.get("additional_rate_limits", payload.get("additionalRateLimits", [])) or []:
        groups.append((str(extra.get("limit_name") or extra.get("metered_feature") or "Additional") + " · ",
                       extra.get("rate_limit") or extra.get("rateLimit")))
    for prefix, group in groups:
        if not isinstance(group, dict):
            continue
        for snake, camel, fallback in (("primary_window", "primaryWindow", "Primary window"),
                                        ("secondary_window", "secondaryWindow", "Secondary window")):
            item = group.get(snake) or group.get(camel)
            if not isinstance(item, dict):
                continue
            used = item.get("used_percent", item.get("usedPercent"))
            reset = item.get("reset_at", item.get("resetAt"))
            if reset is None:
                offset = number(item.get("reset_after_seconds", item.get("resetAfterSeconds")))
                reset = now + offset if offset is not None else None
            label = prefix + duration_label(item.get("limit_window_seconds", item.get("limitWindowSeconds")), fallback)
            windows.append(window(label, used, reset))
    return {"plan": str(payload.get("plan_type") or payload.get("planType") or ""), "windows": windows}


def claude(payload):
    windows = []
    labels = {"five_hour": "5-hour", "seven_day": "Weekly", "seven_day_opus": "Opus · weekly",
              "seven_day_sonnet": "Sonnet · weekly", "seven_day_oauth_apps": "OAuth apps · weekly",
              "seven_day_cowork": "Cowork · weekly", "iguana_necktie": "Fable · weekly"}
    for key, label in labels.items():
        item = payload.get(key)
        if isinstance(item, dict):
            windows.append(window(label, item.get("utilization"), item.get("resets_at")))
    for limit in payload.get("limits", []) or []:
        if isinstance(limit, dict) and "percent" in limit:
            model = ((limit.get("scope") or {}).get("model") or {}).get("display_name")
            windows.append(window(str(model or limit.get("kind") or "Additional"), limit["percent"], limit.get("resets_at")))
    return {"plan": "", "windows": windows}


def kimi(payload, now=None):
    now = time.time() if now is None else now
    windows = []
    items = list(payload.get("limits") or [])
    if isinstance(payload.get("usage"), dict):
        items.append({"detail": payload["usage"], "name": "Weekly"})
    for i, item in enumerate(items):
        detail = item.get("detail") or item
        limit, used = number(detail.get("limit")), number(detail.get("used"))
        if used is None and limit is not None and number(detail.get("remaining")) is not None:
            used = limit - number(detail["remaining"])
        percent = 100 * used / limit if used is not None and limit and limit > 0 else None
        period = item.get("window") or {}
        label = detail.get("name") or detail.get("title") or item.get("name")
        if not label:
            label = f'{period["duration"]} {period.get("timeUnit", "minutes").lower()}' if "duration" in period else f"Limit {i + 1}"
        reset = detail.get("resetTime", detail.get("reset_at", detail.get("resetAt", detail.get("reset_time"))))
        if reset is None:
            offset = number(detail.get("reset_in", detail.get("resetIn", detail.get("ttl"))))
            reset = now + offset if offset is not None else None
        windows.append(window(str(label), percent, reset, limit, used))
    return {"plan": "", "windows": windows}


def antigravity(payload):
    windows = []
    for group in payload.get("groups", []) or []:
        name = group.get("displayName") or group.get("display_name") or "Models"
        for bucket in group.get("buckets", []) or []:
            remaining = number(bucket.get("remainingFraction", bucket.get("remaining_fraction")))
            label = bucket.get("window") or bucket.get("displayName") or "Quota"
            windows.append(window(f"{name} · {label}", None if remaining is None else 100 * (1 - remaining),
                                  bucket.get("resetTime", bucket.get("reset_time"))))
    return {"plan": "", "windows": windows}


def xai(payload):
    # Billing payloads with explicit utilization can be displayed without inferring currency limits.
    windows = []
    for key in ("weekly", "monthly"):
        item = payload.get(key)
        if isinstance(item, dict):
            percent = item.get("usagePercent", item.get("usage_percent"))
            if percent is not None:
                windows.append(window(key.title(), percent, item.get("periodEnd")))
    return {"plan": "", "windows": windows}


def fetch(account, call_api):
    provider = account.get("provider") or account.get("type")
    header = {"Authorization": "Bearer $TOKEN$", "Content-Type": "application/json"}
    body = None
    if provider == "codex":
        url = "https://chatgpt.com/backend-api/wham/usage"
        header["User-Agent"] = "codex-tui/0.149.1 (Linux; x86_64)"
        token_info = account.get("id_token")
        if isinstance(token_info, dict) and token_info.get("chatgpt_account_id"):
            header["Chatgpt-Account-Id"] = token_info["chatgpt_account_id"]
        parser = codex
    elif provider == "claude":
        url = "https://api.anthropic.com/api/oauth/usage"
        header["anthropic-beta"] = "oauth-2025-04-20"
        parser = claude
    elif provider == "kimi":
        url = "https://api.kimi.com/coding/v1/usages"
        parser = kimi
    elif provider == "antigravity":
        if not account.get("project_id"):
            return {"windows": [], "error": "Quota lookup needs this account's project ID."}
        url = "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
        header["User-Agent"] = "antigravity/cli/1.0.13 (aidev_client; os_type=linux; arch=amd64)"
        body = {"project": account["project_id"]}
        parser = antigravity
    else:
        return {"windows": [], "error": "This provider does not expose a supported quota lookup yet."}
    if not account.get("auth_index"):
        return {"windows": [], "error": "Backend did not provide an account reference."}
    import json
    payload = {"auth_index": account["auth_index"], "method": "POST" if body else "GET", "url": url, "header": header}
    if body:
        payload["data"] = json.dumps(body)
    result = call_api("api-call", "POST", payload, timeout=65)
    code = result.get("status_code", result.get("statusCode", 0))
    if not 200 <= code < 300:
        message = {401: "Sign in again to refresh this account's quota access.",
                   403: "Provider did not allow this quota lookup.",
                   429: "Quota check rate-limited. Try again shortly."}.get(code, f"Quota lookup failed (HTTP {code}).")
        return {"windows": [], "error": message}
    data = result.get("body")
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        return {"windows": [], "error": "Provider returned an unreadable quota response."}
    parsed = parser(data)
    parsed["error"] = "" if parsed["windows"] else "Provider returned no quota windows."
    return parsed
