#!/usr/bin/env python3
"""Render checkout QML using installed Omarchy components and an offline bridge."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]
READINESS_IPC_TIMEOUT = 5
READINESS_TIMEOUT = 15
SMOKE_IPC_TIMEOUT = 10
SHELL = r'''import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons

ShellRoot {
    id: preview
    function descendants() {
        var found = [], seen = []
        function visit(node) {
            if (!node || seen.indexOf(node) >= 0) return
            seen.push(node); found.push(node)
            for (var key of ["data", "children", "contentItem"]) {
                var value = node[key]
                if (!value) continue
                if (value.length !== undefined) {
                    for (var i = 0; i < value.length; i++) visit(value[i])
                } else visit(value)
            }
        }
        visit(widget)
        return found
    }
    QtObject {
        id: host
        property string position: "top"
        property bool vertical: false
        property int barSize: Style.bar.sizeHorizontal
        property color foreground: Color.foreground
        property color barForeground: Color.foreground
        property color urgent: Color.urgent
        property string fontFamily: Style.font.family
        property bool foregroundAnimationEnabled: true
        property var activePopout: null
        property var clickTargets: []
        property QtObject shell: QtObject {
            function updateEntryInline(name, settings) { console.log("Preview display setting changed") }
        }
        function requestPopout(item) { activePopout = item }
        function releasePopout(item) { if (activePopout === item) activePopout = null }
        function registerClickTarget(item) { clickTargets = clickTargets.concat([item]) }
        function unregisterClickTarget(item) { clickTargets = clickTargets.filter(function(v) { return v !== item }) }
        function showTooltip(item, text) {}
        function hideTooltip(item) {}
        function switchPanelFrom(item, direction) { return false }
    }
    PanelWindow {
        id: barWindow
        anchors { top: true; left: true; right: true }
        implicitHeight: host.barSize
        exclusiveZone: 0
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "omaproxy-isolated-preview"
        WlrLayershell.layer: WlrLayer.Overlay
        color: Color.background
        Text { anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: "OmaProxy offline preview"; color: Color.foreground }
        BarWidget { id: widget; bar: host; anchors.horizontalCenter: parent.horizontalCenter; anchors.verticalCenter: parent.verticalCenter }
    }
    IpcHandler {
        target: "omaproxy-preview"
        function state(): string {
            return JSON.stringify({opened: widget.opened, page: widget.page, busy: widget.busy,
                running: widget.snapshot.running, notice: widget.notice, noticeError: widget.noticeError,
                revealedEmails: Object.keys(widget.revealedEmails).length,
                updates: "updates" in widget ? widget.updates : {},
                routing: "routingSettings" in widget ? widget.routingSettings : {},
                diagnostics: "diagnostics" in widget ? widget.diagnostics : {},
                customProviders: "customProviders" in widget ? widget.customProviders : [],
                providerWeightsSupported: "providerWeightsSupported" in widget ? widget.providerWeightsSupported : false,
                clientKeys: "clientKeys" in widget ? widget.clientKeys : [],
                revokingClient: "revokingClient" in widget ? widget.revokingClient : "",
                quotaAlerts: "quotaAlerts" in widget ? widget.quotaAlerts : false,
                mode: widget.snapshot.mode, hasApiKey: widget.snapshot.has_api_key,
                editingProvider: "editingProvider" in widget ? widget.editingProvider : "",
                addingKey: widget.addingKey,
                pageRefreshPending: "pageRefreshPending" in widget ? widget.pageRefreshPending : false,
                removingProvider: "removingProvider" in widget ? widget.removingProvider : "",
                passwordFieldsCleared: preview.descendants().filter(function(item) {
                    return item.password === true && item.text !== undefined
                }).every(function(item) { return item.text === "" })})
        }
        function controls(): string {
            return JSON.stringify(preview.descendants().filter(function(item) {
                return item.text !== undefined && typeof item.clicked === "function"
            }).map(function(item) { return {text: item.text, visible: item.visible, enabled: item.enabled} }))
        }
        function hasText(text: string): bool {
            return preview.descendants().some(function(item) { return item.text === text && item.visible })
        }
        function containsText(text: string): bool {
            return preview.descendants().some(function(item) { return typeof item.text === "string" && item.text.indexOf(text) >= 0 && item.visible })
        }
        function activate(text: string): string {
            var matches = preview.descendants().filter(function(item) {
                return item.text === text && item.visible && item.enabled && typeof item.clicked === "function"
            })
            if (matches.length !== 1) return "Expected one enabled visible control; found " + matches.length
            matches[0].forceActiveFocus()
            matches[0].clicked()
            return "Activated " + text
        }
        function setField(placeholder: string, encodedText: string): string {
            var fields = preview.descendants().filter(function(item) {
                return item.placeholderText === placeholder && item.visible && item.enabled
            })
            if (fields.length !== 1) return "Expected one editable visible field; found " + fields.length
            fields[0].text = decodeURIComponent(encodedText)
            return "Field updated"
        }
        function setNumericField(previous: string, text: string): string {
            var fields = preview.descendants().filter(function(item) {
                return item.placeholderText !== undefined && item.text === previous && item.visible && item.enabled
            })
            if (!fields.length) return "Editable numeric field not found"
            fields[0].text = text
            return "Field updated"
        }
        function scrollTo(text: string): string {
            var items = preview.descendants().filter(function(item) { return item.text === text && item.visible && item.mapToItem })
            if (!items.length) return "Visible item not found"
            var item = items[0], ancestor = item.parent
            while (ancestor) {
                if (ancestor.contentY !== undefined && ancestor.contentHeight !== undefined && ancestor.contentItem) {
                    var point = item.mapToItem(ancestor.contentItem, 0, 0)
                    ancestor.contentY = Math.max(0, Math.min(point.y, ancestor.contentHeight - ancestor.height))
                    return "Scrolled to item"
                }
                ancestor = ancestor.parent
            }
            return "Item has no scroll ancestor"
        }
        function capture(path: string): string {
            var cards = preview.descendants().filter(function(item) {
                return item.borderSpec !== undefined && typeof item.grabToImage === "function" && item.width > 200
            })
            cards.sort(function(a, b) { return b.width * b.height - a.width * a.height })
            if (!cards.length || cards[0].height < 200) return "Popup card was not found"
            cards[0].grabToImage(function(result) {
                console.log("Preview capture saved: " + result.saveToFile(path))
            })
            return "Capturing popup card"
        }
        function quit(): void { Qt.quit() }
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", choices=("limits", "accounts", "settings"), default="limits")
    parser.add_argument("--duration", type=float, help="Stop automatically after this many seconds.")
    parser.add_argument("--keep", action="store_true", help="Keep private temporary fixture and log files after exit.")
    parser.add_argument("--smoke", action="store_true", help="Exercise detected native controls against fixtures and capture the concealed account card.")
    parser.add_argument("--repo", type=Path, default=REPO, help="Checkout to preview; its real helper is never copied or executed.")
    args = parser.parse_args()
    if args.smoke:
        args.page = "settings"
    runtime = shutil.which("quickshell")
    packaged = Path("/usr/share/omarchy/shell")
    if not runtime or not (packaged / "Ui" / "KeyboardPanel.qml").exists():
        parser.error("Requires installed Omarchy shell and Quickshell.")
    root = Path(tempfile.mkdtemp(prefix="omaproxy-preview-"))
    child = None
    try:
        for directory in ("Commons", "Ui"):
            (root / directory).symlink_to(packaged / directory, target_is_directory=True)
        for file in ("BarWidget.qml", "LimitModel.js"):
            shutil.copy2(args.repo / file, root / file)
        shutil.copytree(args.repo / "assets", root / "assets")
        (root / "scripts").mkdir()
        shutil.copy2(REPO / "tests/fixtures/preview_bridge.py", root / "scripts/omaproxy.py")
        (root / "shell.qml").write_text(SHELL)
        state = root / "fixture-state"
        state.mkdir(mode=0o700)
        env = os.environ.copy()
        env.update(OMAPROXY_PREVIEW_STATE=str(state), QT_LINUX_ACCESSIBILITY_ALWAYS_ON="1", QT_ACCESSIBILITY="1", OMAPROXY_PREVIEW_STATUS_DELAY="2" if args.smoke else "0")
        print(json.dumps({"preview_root": str(root), "log": str(root / "quickshell.log"), "action_trace": str(state / "actions.jsonl"), "ipc": [runtime, "ipc", "-p", str(root), "call", "soojy.omaproxy", "showPage", args.page]}), flush=True)
        with (root / "quickshell.log").open("w") as log:
            child = subprocess.Popen([runtime, "-p", str(root), "--no-color"], env=env, stdout=log, stderr=subprocess.STDOUT)
            # IPC is scoped by config path, so it never opens the installed plugin.
            deadline = time.monotonic() + READINESS_TIMEOUT
            ready = False
            for _ in range(50):
                if child.poll() is not None:
                    print((root / "quickshell.log").read_text(), flush=True)
                    return child.returncode or 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    ipc = subprocess.run([runtime, "ipc", "-p", str(root), "call", "soojy.omaproxy", "showPage", args.page], capture_output=True, text=True, timeout=min(READINESS_IPC_TIMEOUT, remaining))
                except subprocess.TimeoutExpired:
                    continue
                if ipc.returncode == 0:
                    ready = True
                    break
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            if not ready:
                raise RuntimeError("Preview IPC target did not become ready. See " + str(root / "quickshell.log"))
            if args.smoke:
                smoke(runtime, root)
                child.terminate()
                child.wait(timeout=5)
                return 0
            try:
                return child.wait(timeout=args.duration)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)
                return 0
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        finally:
            if args.keep:
                print("Retained private preview files: " + str(root), flush=True)
            else:
                shutil.rmtree(root)


def smoke(runtime, root):
    def ipc(target, function, *args):
        return subprocess.run([runtime, "ipc", "-p", str(root), "call", target, function, *args], check=True, capture_output=True, text=True, timeout=SMOKE_IPC_TIMEOUT).stdout.strip()

    def wait(predicate):
        for _ in range(100):
            result = json.loads(ipc("omaproxy-preview", "state"))
            if predicate(result):
                return result
            time.sleep(0.05)
        raise RuntimeError("Native preview state did not converge: " + json.dumps(result))

    def activate(text):
        wait(lambda state: not state["busy"] and not state["pageRefreshPending"])
        response = ipc("omaproxy-preview", "activate", text)
        if not response.startswith("Activated "):
            raise RuntimeError(response)
        wait(lambda state: not state["busy"] and not state["pageRefreshPending"])

    def controls():
        return json.loads(ipc("omaproxy-preview", "controls"))

    def has(text):
        return any(item["text"] == text and item["visible"] for item in controls())

    def field(placeholder, value):
        result = ipc("omaproxy-preview", "setField", placeholder, quote(value, safe=""))
        if result != "Field updated":
            raise RuntimeError(result + ": " + placeholder)

    captures = []
    def capture(name, scroll_text=None):
        ipc("soojy.omaproxy", "open")
        if scroll_text:
            result = ipc("omaproxy-preview", "scrollTo", scroll_text)
            if result != "Scrolled to item":
                raise RuntimeError(result)
        time.sleep(0.25)
        path = root / (name + ".png")
        response = ipc("omaproxy-preview", "capture", str(path))
        if response != "Capturing popup card":
            raise RuntimeError(response)
        for _ in range(40):
            if path.exists() and path.read_bytes().endswith(b"IEND\xaeB`\x82"):
                captures.append(str(path))
                return
            time.sleep(0.05)
        raise RuntimeError("Native card capture was not saved.")

    required = set()
    initial_state = json.loads(ipc("omaproxy-preview", "state"))
    cold_settings = "pageRefreshPending" in (root / "BarWidget.qml").read_text()
    if cold_settings and (initial_state["running"] or initial_state["page"] != 2):
        raise RuntimeError("Cold Settings preview was not observed before initial status")
    wait(lambda state: state["running"])
    if cold_settings:
        wait(lambda state: state["page"] == 2 and bool(state["routing"].get("values")) and '"command": "preferences"' in (root / "fixture-state/actions.jsonl").read_text())
    activate("Settings")
    if has("Check backend updates"):
        activate("Check backend updates")
        wait(lambda state: state["updates"].get("update_supported") is True and state["updates"].get("update_available") is True)
        activate("Install reviewed update")
        wait(lambda state: state["updates"].get("installed_version") == "v6.9.22")
        activate("Restore previous backend")
        wait(lambda state: state["updates"].get("installed_version") == "v6.9.20")
        required.update(("check-updates", "backend-update", "backend-rollback"))
        capture("updater", "Check backend updates")
    if has("Routing details"):
        wait(lambda state: bool(state["routing"].get("values")))
        activate("Weighted")
        wait(lambda state: state["routing"]["values"].get("strategy") == "weighted-round-robin")
        activate("Routing details")
        activate("Keep conversations on one account: On")
        wait(lambda state: state["routing"]["values"].get("session-affinity") is False)
        activate("Subagents inherit the conversation account: On")
        wait(lambda state: state["routing"]["values"].get("session-affinity-subagents") is False)
        activate("Disable cooldowns: Off")
        wait(lambda state: state["routing"]["values"].get("disable-cooling") is True)
        activate("Persist cooldown state: On")
        wait(lambda state: state["routing"]["values"].get("save-cooldown-status") is False)
        field("Conversation affinity duration, e.g. 1h", "2h")
        activate("Save affinity duration")
        wait(lambda state: state["routing"]["values"].get("session-affinity-ttl") == "2h")
        for previous, value in (("2", "3"), ("2", "4"), ("30", "45")):
            if ipc("omaproxy-preview", "setNumericField", previous, value) != "Field updated":
                raise RuntimeError("Retry field update failed")
        activate("Save retry limits")
        wait(lambda state: all(state["routing"]["values"].get(k) == v for k, v in (("request-retry", 3), ("max-retry-credentials", 4), ("max-retry-interval", 45))))
        for previous, invalid in (("3", ""), ("4", "1.5")):
            prior_trace = (root / "fixture-state/actions.jsonl").read_text().count('"command": "routing-save"')
            if ipc("omaproxy-preview", "setNumericField", previous, invalid) != "Field updated":
                raise RuntimeError("Retry invalid-input fixture failed")
            activate("Save retry limits")
            wait(lambda state: state["noticeError"])
            if (root / "fixture-state/actions.jsonl").read_text().count('"command": "routing-save"') != prior_trace:
                raise RuntimeError("Invalid retry input reached the fixture bridge")
            if ipc("omaproxy-preview", "setNumericField", invalid, previous) != "Field updated":
                raise RuntimeError("Retry field restore failed")
        activate("Save retry limits")
        wait(lambda state: not state["noticeError"])
        capture("routing", "Keep conversations on one account: Off")
        activate("Hide routing details")
        activate("Quota alerts: Off")
        wait(lambda state: state["quotaAlerts"])
        activate("Limits")
        activate("Refresh")
        wait(lambda state: state["noticeError"] and "Preview alert delivery failed" in state["notice"])
        capture("alert-error")
        activate("Settings")
        activate("Quota alerts: On")
        wait(lambda state: not state["quotaAlerts"])
        if has("Named client keys"):
            activate("Named client keys")
            field("Client name, e.g. t3-code or codex-cli", "preview-t3-code")
            activate("Create client key")
            wait(lambda state: len(state["clientKeys"]) == 1 and state["clientKeys"][0]["active"])
            activate("Refresh client keys")
            activate("Copy client key")
            wait(lambda state: state["notice"] == "Preview client key copy recorded; clipboard unchanged.")
            capture("client-keys", "Refresh client keys")
            required.update(("client-keys", "client-create", "client-copy", "client-revoke"))
        activate("Show diagnostics")
        wait(lambda state: bool(state["diagnostics"].get("accounts", {}).get("records")))
        activate("Refresh counters")
        activate("Capture pending activity")
        wait(lambda state: bool(state["diagnostics"].get("queue", {}).get("events")))
        for summary in ("Accounts: available · 1 shown · 2 unrecognized · 3 omitted",
                        "Upstream keys: available · 1 shown · 1 unrecognized · 2 omitted",
                        "Activity: available · 1 shown · 2 unrecognized · 4 omitted"):
            if ipc("omaproxy-preview", "hasText", summary) != "true":
                raise RuntimeError("Missing displayed diagnostic summary: " + summary)
        if has("Hide client keys"):
            wait(lambda state: state["diagnostics"]["queue"]["events"][0].get("client_name") == "preview-t3-code")
        if "diagnosticEventDetails" in (root / "BarWidget.qml").read_text():
            for detail in ("2026-10-03T18:00:00Z", "model-preview", "HTTP 200", "First token 40 ms", "input tokens: 100", "output tokens: 23", "cached tokens: 0", "total tokens: 123"):
                if ipc("omaproxy-preview", "containsText", detail) != "true":
                    raise RuntimeError("Captured activity metadata was not rendered: " + detail)
        capture("diagnostics", "Refresh counters")
        capture("activity-detail", "Activity: available · 1 shown · 2 unrecognized · 4 omitted")
        if has("Hide client keys"):
            activate("Revoke")
            wait(lambda state: state["revokingClient"] == "preview-t3-code")
            prior_trace = (root / "fixture-state/actions.jsonl").read_text().count('"command": "client-revoke"')
            activate("Accounts")
            wait(lambda state: not state["revokingClient"])
            if (root / "fixture-state/actions.jsonl").read_text().count('"command": "client-revoke"') != prior_trace:
                raise RuntimeError("Staged revocation reached the fixture bridge")
            activate("Settings")
            activate("Revoke")
            activate("Confirm revocation")
            wait(lambda state: not state["clientKeys"])
            capture("client-keys-revoked", "Refresh client keys")
            activate("Hide client keys")
        required.update(("routing", "routing-save", "diagnostics", "capture-activity"))
    if has("Remote"):
        activate("Remote")
        field("Server URL, e.g. https://proxy.example.com", "https://proxy.example.invalid")
        field("Management key", "preview-management-only")
        field("Client API key (optional, for models)", "preview-client-only")
        activate("Test and save connection")
        wait(lambda state: state["mode"] == "remote" and state["hasApiKey"])
        capture("remote-connected", "Remote")
        activate("Remove saved client API key")
        activate("Test and save connection")
        wait(lambda state: state["mode"] == "remote" and state["hasApiKey"] is False)
        capture("remote-management-only", "Remote")
        activate("Local")
        wait(lambda state: state["mode"] == "local")
        required.update(("connection-save", "connection-local"))
    activate("Accounts")
    if has("Refresh providers"):
        wait(lambda state: bool(state["customProviders"]))
        wait(lambda state: state["providerWeightsSupported"])
        activate("Test models")
        activate("Edit")
        wait(lambda state: state["editingProvider"] == "preview-provider")
        field("Base URL, e.g. https://provider.example/v1", "https://provider.example.invalid/v2")
        activate("Save provider")
        wait(lambda state: state["customProviders"][0]["url"] == "https://provider.example.invalid/v2")
        saves = [json.loads(line) for line in (root / "fixture-state/actions.jsonl").read_text().splitlines() if json.loads(line)["command"] == "custom-save"]
        if "models" in saves[-1]["payload_fields"] or "url" not in saves[-1]["payload_fields"]:
            raise RuntimeError("URL-only provider edit did not omit models")
        if json.loads(ipc("omaproxy-preview", "state"))["customProviders"][0]["models"][0]["alias"] != "preview-model":
            raise RuntimeError("URL-only provider edit changed aliases")
        wait(lambda state: not state["addingKey"] and not state["editingProvider"])
        activate("Edit")
        capture("provider-url-only", "Save provider")
        field("Model IDs, or JSON with name and alias", '[{"name":"preview-upstream","alias":"preview-edited"}]')
        field("Optional weight (0 excludes this credential)", "2")
        activate("Save provider")
        wait(lambda state: state["customProviders"][0]["models"][0].get("alias") == "preview-edited")
        wait(lambda state: state["customProviders"][0]["credential_count"] == 2 and state["customProviders"][0]["credentials"][0]["weight"] == 2)
        wait(lambda state: not state["addingKey"] and not state["editingProvider"])
        activate("Edit")
        capture("provider-edit", "Save provider")
        activate("Hide API provider form")
        activate("Remove")
        wait(lambda state: state["removingProvider"] == "preview-provider")
        # A page change must cancel the staged destructive confirmation.
        activate("Settings")
        wait(lambda state: not state["removingProvider"])
        activate("Accounts")
        activate("Remove")
        activate("Confirm removal")
        wait(lambda state: not state["customProviders"])
        activate("+ API-key provider")
        field("Name, e.g. zai", "preview-new-provider")
        field("Base URL, e.g. https://provider.example/v1", "https://provider.example.invalid/v1")
        field("API key", "preview-key-only")
        field("Model IDs, or JSON with name and alias", '[{"name":"preview-upstream","alias":"preview-new"}]')
        activate("Save provider")
        wait(lambda state: len(state["customProviders"]) == 1 and state["customProviders"][0]["name"] == "preview-new-provider")
        wait(lambda state: not state["addingKey"])
        required.update(("custom-list", "custom-test", "custom-save", "custom-remove"))
    prior_refreshes = (root / "fixture-state/actions.jsonl").read_text().count('"command": "custom-list"')
    ipc("soojy.omaproxy", "close")
    ipc("soojy.omaproxy", "showPage", "accounts")
    wait(lambda state: state["opened"] and state["revealedEmails"] == 0 and state["passwordFieldsCleared"])
    if "custom-list" in required:
        wait(lambda state: not state["busy"] and (root / "fixture-state/actions.jsonl").read_text().count('"command": "custom-list"') > prior_refreshes)
    capture("accounts")
    trace = [json.loads(line)["command"] for line in (root / "fixture-state/actions.jsonl").read_text().splitlines()]
    if "routing-save" in required and not any(json.loads(line).get("notification_requested") for line in (root / "fixture-state/actions.jsonl").read_text().splitlines()):
        raise RuntimeError("Native quota refresh did not pass the alert opt-in flag")
    if not required.issubset(trace):
        raise RuntimeError("Missing fixture actions: " + repr(required - set(trace)))
    log = (root / "quickshell.log").read_text()
    if any(marker in log for marker in ("ReferenceError:", "TypeError:", "Unable to load configuration", "failed to load component")):
        raise RuntimeError("Native runtime errors in " + str(root / "quickshell.log"))
    print(json.dumps({"native_smoke": "passed", "verified_actions": sorted(required), "cold_settings_preferences_before_navigation": cold_settings, "concealed_email_reopen": True, "popup_captures": captures}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
