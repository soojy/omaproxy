import QtQuick
import Qt5Compat.GraphicalEffects
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "LimitModel.js" as Limits

Panel {
    id: root
    moduleName: "soojy.omaproxy"
    ipcTarget: "soojy.omaproxy"
    manageIpc: false
    readonly property string helper: decodeURIComponent(Qt.resolvedUrl("scripts/omaproxy.py").toString().replace(/^file:\/\//, ""))
    readonly property color foreground: bar ? bar.foreground : Color.foreground
    property var snapshot: ({configured: false, running: false, accounts: [], models: [], providers: []})
    property var quotaData: ({accounts: []})
    property var auth: ({})
    property var preferences: ({})
    readonly property bool showExtraLimits: setting("showExtraLimits", false) === true
    property var revealedEmails: ({})
    property string notice: ""
    property bool noticeError: false
    property int page: 0
    property bool addingAccount: false
    property bool addingKey: false
    property bool showingModels: false
    property bool showingLogs: false
    property string logText: ""
    property double now: Date.now() / 1000
    readonly property bool busy: action.running
    readonly property bool signingIn: auth.status === "wait"
    readonly property var quotaAccounts: (quotaData.accounts || []).filter(function(q) {
        return (root.snapshot.accounts || []).some(function(a) { return a.name === q.name })
    })
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function refresh() { if (!poll.running) poll.running = true }
    function refreshQuotas(force) {
        if (!quotaPoll.running && snapshot.running) {
            quotaPoll.command = ["python3", "-B", helper, "quotas"].concat(force ? ["--force"] : [])
            quotaPoll.running = true
        }
    }
    function perform(args, payload) {
        if (busy) return
        noticeError = false
        notice = args[0] === "setup" ? "Downloading and verifying CLIProxyAPI…" : ""
        action.payload = payload === undefined ? "" : JSON.stringify(payload) + "\n"
        action.stdinEnabled = action.payload !== ""
        action.command = ["python3", "-B", helper].concat(args)
        action.running = true
    }
    function receive(result) {
        if (result.error) { noticeError = true; notice = result.error; return }
        if (result.auth !== undefined) {
            var wasWaiting = signingIn
            auth = result.auth
            if (auth.status === "ok" && wasWaiting) {
                notice = "Account connected. Updating limits…"
                addingAccount = false
                refresh()
                refreshQuotas(true)
            }
        }
        if (result.preferences) preferences = result.preferences
        if (result.logs !== undefined) logText = result.logs
        if (result.message) notice = result.message
    }
    function setDisplaySetting(name, value) {
        var next = Object.assign({}, settings)
        next[name] = value
        root.settings = next
        if (bar && bar.shell) bar.shell.updateEntryInline(moduleName, next)
    }
    function accountLabel(a) { return a.email || a.label || a.name || "Account" }
    function toggleEmail(name) {
        var next = Object.assign({}, revealedEmails)
        next[name] = !next[name]
        revealedEmails = next
    }
    function accountHeading(account) {
        var provider = account.provider || account.type
        var quota = (quotaData.accounts || []).find(function(item) { return item.name === account.name })
        var plan = account.plan || (quota ? quota.plan : "")
        var label = Limits.planLabel(provider, plan)
        return providerLabel(provider) + (label ? " · " + label : "")
    }
    function providerLabel(id) {
        var match = (snapshot.providers || []).find(function(p) { return p.id === id })
        return match ? match.name : id || "Provider"
    }
    function accountDisabled(a) {
        var live = (snapshot.accounts || []).find(function(item) { return item.name === a.name })
        return live ? !!live.disabled : !!a.disabled
    }
    function toggleAccount(a) {
        perform(["account", a.name, accountDisabled(a) ? "enable" : "disable", "--auth-index", a.auth_index || ""])
    }
    function resetLabel(timestamp) {
        if (!timestamp) return "Reset time unavailable"
        var seconds = timestamp - now
        if (seconds <= 0) return "Reset time passed · refresh to update"
        var minutes = Math.ceil(seconds / 60)
        var days = Math.floor(minutes / 1440)
        var hours = Math.floor((minutes % 1440) / 60)
        var left = days > 0 ? days + "d " + hours + "h" : hours > 0 ? hours + "h " + (minutes % 60) + "m" : minutes + "m"
        return "Resets in " + left + " · " + Qt.formatDateTime(new Date(timestamp * 1000), "ddd d MMM, hh:mm")
    }

    onOpenedChanged: {
        if (opened) { refresh(); refreshQuotas(false); if (snapshot.configured && !authPoll.running) authPoll.running = true }
        else revealedEmails = ({})
    }
    onPageChanged: { scroll.contentY = 0; if (page === 2 && snapshot.running) perform(["preferences"]) }
    Component.onCompleted: refresh()

    IpcHandler {
        target: "soojy.omaproxy"
        function open(): void { root.open() }
        function close(): void { root.close() }
        function toggle(): void { root.toggle() }
        function showPage(name: string): void {
            var index = ["limits", "accounts", "settings"].indexOf(name)
            if (index >= 0) { root.page = index; root.open() }
        }
        function previewGeometry(): string {
            return JSON.stringify({screen: popup.screen ? popup.screen.name : "", x: popup.cardOrigin.x,
                y: popup.cardOrigin.y, width: popup.contentWidth, height: popup.contentHeight})
        }
    }
    Process {
        id: poll
        command: ["python3", "-B", root.helper, "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var result = JSON.parse(text)
                    if (result.configured !== undefined) {
                        var wasRunning = root.snapshot.running
                        var oldNames = (root.snapshot.accounts || []).map(function(a) { return a.name }).join("|")
                        root.snapshot = result
                        var newNames = (result.accounts || []).map(function(a) { return a.name }).join("|")
                        if (root.opened && result.running && (!wasRunning || oldNames !== newNames)) root.refreshQuotas(false)
                    } else root.receive(result)
                } catch (e) { root.notice = "Unable to read proxy status."; root.noticeError = true }
            }
        }
    }
    Process {
        id: quotaPoll
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var result = JSON.parse(text)
                    if (result.quotas) root.quotaData = result.quotas
                    else root.receive(result)
                } catch (e) { root.notice = "Unable to read account limits."; root.noticeError = true }
            }
        }
    }
    Process {
        id: authPoll
        command: ["python3", "-B", root.helper, "auth-status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.receive(JSON.parse(text)) } catch (e) {}
            }
        }
    }
    Process {
        id: action
        property string payload: ""
        onStarted: if (payload !== "") { write(payload); payload = "" }
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.receive(JSON.parse(text)) }
                catch (e) { root.notice = "The action returned no result."; root.noticeError = true }
                root.refresh()
            }
        }
    }
    Timer { interval: root.opened ? 5000 : 20000; running: true; repeat: true; onTriggered: root.refresh() }
    Timer { interval: 60000; running: root.opened && root.snapshot.running; repeat: true; onTriggered: root.refreshQuotas(false) }
    Timer { interval: 2000; running: root.signingIn; repeat: true; onTriggered: if (!authPoll.running && !root.busy) authPoll.running = true }
    Timer { interval: 10000; running: root.opened; repeat: true; onTriggered: root.now = Date.now() / 1000 }

    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "󰚩"
        active: root.snapshot.running
        tooltipText: "OmaProxy · " + (root.snapshot.running ? "Account limits" : "Proxy stopped")
        onPressed: root.toggle()
        Rectangle {
            width: Style.space(5); height: width; radius: width / 2
            anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: Style.space(3)
            color: root.snapshot.running ? Color.accent : root.foreground
            opacity: root.snapshot.running ? 1 : 0.35
        }
    }
    KeyboardPanel {
        id: popup
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: content
        contentWidth: fittedContentWidth(Style.space(500))
        contentHeight: fittedContentHeight(Math.min(Style.space(640), Math.max(Style.space(280), heading.implicitHeight + body.implicitHeight + feedback.implicitHeight + Style.space(32))))
        FocusScope {
            id: content
            anchors.fill: parent
            Keys.onEscapePressed: root.close()
            Column {
                id: heading
                width: parent.width
                spacing: Style.space(14)
                Row {
                    width: parent.width
                    spacing: Style.space(12)
                    Column {
                        width: parent.width - statusButton.width - parent.spacing
                        spacing: Style.space(4)
                        Label { text: "OmaProxy"; font.pixelSize: Style.font.title; font.bold: true }
                        Label { text: "ACCOUNT LIMITS"; opacity: 0.45; font.pixelSize: Style.font.caption; font.letterSpacing: 1.4 }
                    }
                    ActionButton {
                        id: statusButton
                        visible: root.snapshot.configured
                        text: root.snapshot.running ? "● Running" : "○ Stopped"
                        active: root.snapshot.running
                        enabled: !root.busy
                        onClicked: root.perform([root.snapshot.running ? "stop" : "start"])
                    }
                }
                Row {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                        model: ["Limits", "Accounts", "Settings"]
                        ActionButton {
                            required property string modelData
                            required property int index
                            width: (heading.width - Style.space(10)) / 3
                            text: modelData
                            active: root.page === index
                            onClicked: root.page = index
                        }
                    }
                }
                PanelSeparator { foreground: root.foreground }
            }
            Flickable {
                id: scroll
                anchors.top: heading.bottom; anchors.topMargin: Style.space(16)
                anchors.bottom: feedback.top; anchors.bottomMargin: Style.space(12)
                width: parent.width
                clip: true
                contentHeight: body.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar {}
                Column {
                    id: body
                    width: scroll.width
                    spacing: Style.space(16)

                    Column {
                        visible: !root.snapshot.configured
                        width: parent.width
                        spacing: Style.space(16)
                        Label { text: "Your accounts. Your remaining capacity."; font.bold: true; width: parent.width; wrapMode: Text.WordWrap }
                        Hint { text: "Set up the local proxy to see account limits and reset times here." }
                        ActionButton { text: root.busy ? "Installing…" : "Set up proxy"; enabled: !root.busy; onClicked: root.perform(["setup"]) }
                        Hint { text: "Downloads and verifies CLIProxyAPI, then creates your user service. Progress stays here." }
                    }

                    Column {
                        visible: root.snapshot.configured && root.page === 0
                        width: parent.width
                        spacing: Style.space(14)
                        Row {
                            width: parent.width
                            spacing: Style.space(8)
                            Column {
                                width: parent.width - limitActions.width - parent.spacing
                                Label { text: (root.snapshot.accounts || []).length + " connected account(s)"; font.bold: true }
                                Label { text: "Remaining allowance & reset times"; opacity: 0.5; font.pixelSize: Style.font.caption }
                            }
                            Row {
                                id: limitActions
                                spacing: Style.space(6)
                                ActionButton {
                                    text: quotaPoll.running ? "Checking…" : "Refresh"
                                    enabled: root.snapshot.running && !quotaPoll.running
                                    onClicked: root.refreshQuotas(true)
                                }
                            }
                        }
                        Hint {
                            visible: !root.snapshot.running
                            text: "Start the proxy to refresh limits. Previous readings stay visible."
                        }
                        Column {
                            visible: !(root.snapshot.accounts || []).length
                            width: parent.width
                            spacing: Style.space(12)
                            Label { text: "No accounts yet"; font.pixelSize: Style.font.title; font.bold: true }
                            Hint { text: "Once you add an account, its available allowance and next reset will appear here." }
                            ActionButton { text: "Go to Accounts"; onClicked: { root.page = 1; root.addingAccount = true } }
                        }
                        Hint {
                            visible: (root.snapshot.accounts || []).length > 0 && root.quotaAccounts.length === 0
                            text: quotaPoll.running ? "Checking your account limits…" : "Refresh to load your account limits."
                        }
                        Repeater {
                            model: root.quotaAccounts
                            Rectangle {
                                id: card
                                required property var modelData
                                width: body.width
                                implicitHeight: cardBody.implicitHeight + Style.space(28)
                                color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
                                border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
                                radius: Style.cornerRadius
                                Column {
                                    id: cardBody
                                    x: Style.space(14); y: Style.space(14)
                                    width: parent.width - Style.space(28)
                                    spacing: Style.space(14)
                                    Row {
                                        width: parent.width
                                        spacing: Style.space(8)
                                        ProviderIcon {
                                            id: accountIcon
                                            provider: card.modelData.provider
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Column {
                                            width: parent.width - pause.width - accountIcon.width - parent.spacing * 2
                                            spacing: Style.space(3)
                                            Label {
                                                text: root.providerLabel(card.modelData.provider) + (card.modelData.plan ? " · " + Limits.planLabel(card.modelData.provider, card.modelData.plan) : "")
                                                font.bold: true
                                            }
                                            EmailLabel { width: parent.width; accountKey: card.modelData.name; emailText: root.accountLabel(card.modelData); opacity: 0.55 }
                                        }
                                        ActionButton {
                                            id: pause
                                            text: root.accountDisabled(card.modelData) ? "Paused" : "Active"
                                            active: !root.accountDisabled(card.modelData)
                                            enabled: !root.busy && root.snapshot.running
                                            onClicked: root.toggleAccount(card.modelData)
                                        }
                                    }
                                    Repeater {
                                        model: Limits.visibleWindows(card.modelData.windows, root.showExtraLimits)
                                        Column {
                                            required property var modelData
                                            width: cardBody.width
                                            spacing: Style.space(6)
                                            Row {
                                                width: parent.width
                                                Label {
                                                    width: parent.width - amount.width
                                                    text: modelData.label
                                                    font.pixelSize: Style.font.bodySmall
                                                    wrapMode: Text.WordWrap
                                                }
                                                Label {
                                                    id: amount
                                                    text: modelData.remaining_percent === null ? "Unknown" : Math.round(modelData.remaining_percent) + "% left"
                                                    color: Color.accent; font.bold: true
                                                }
                                            }
                                            Rectangle {
                                                width: parent.width; height: Style.space(6); radius: height / 2
                                                color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.1)
                                                Rectangle {
                                                    height: parent.height; radius: height / 2
                                                    width: modelData.remaining_percent === null ? 0 : parent.width * Math.max(0, Math.min(100, modelData.remaining_percent)) / 100
                                                    color: Color.accent
                                                    opacity: card.modelData.stale || root.accountDisabled(card.modelData) ? 0.4 : 0.85
                                                    Behavior on width { NumberAnimation { duration: 180 } }
                                                }
                                            }
                                            Label { width: parent.width; text: root.resetLabel(modelData.reset_at); wrapMode: Text.WordWrap; opacity: 0.5; font.pixelSize: Style.font.caption }
                                            Label {
                                                visible: modelData.limit !== null && modelData.used !== null
                                                text: modelData.used + " / " + modelData.limit + " used"
                                                opacity: 0.5; font.pixelSize: Style.font.caption
                                            }
                                        }
                                    }
                                    Hint { visible: !!card.modelData.error; text: (card.modelData.stale && (card.modelData.windows || []).length ? "Previous reading · " : "") + (card.modelData.error || "") }
                                }
                            }
                        }
                    }

                    Column {
                        visible: root.snapshot.configured && root.page === 1
                        width: parent.width
                        spacing: Style.space(14)
                        Row {
                            width: parent.width
                            Label { text: "Connected accounts"; font.bold: true; width: parent.width - addAccount.width }
                            ActionButton { id: addAccount; text: root.addingAccount ? "Done" : "+ Add account"; onClicked: root.addingAccount = !root.addingAccount }
                        }
                        Hint { visible: !(root.snapshot.accounts || []).length; text: "Add a subscription account. Browser sign-in returns to this plugin automatically." }
                        Repeater {
                            model: root.snapshot.accounts || []
                            Row {
                                required property var modelData
                                width: body.width
                                spacing: Style.space(8)
                                ProviderIcon {
                                    id: connectedIcon
                                    provider: modelData.provider || modelData.type
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Column {
                                    width: parent.width - accountToggle.width - connectedIcon.width - parent.spacing * 2
                                    Label { width: parent.width; text: root.accountHeading(modelData); wrapMode: Text.WordWrap; font.bold: true }
                                    EmailLabel { width: parent.width; accountKey: modelData.name; emailText: root.accountLabel(modelData); opacity: 0.6 }
                                }
                                ActionButton {
                                    id: accountToggle
                                    text: modelData.disabled ? "Enable" : "Pause"
                                    enabled: !root.busy && root.snapshot.running
                                    onClicked: root.toggleAccount(modelData)
                                }
                            }
                        }
                        Column {
                            visible: root.signingIn || root.auth.status === "error"
                            width: parent.width
                            spacing: Style.space(10)
                            PanelSeparator { foreground: root.foreground }
                            Label { text: root.signingIn ? "Complete " + root.providerLabel(root.auth.provider) + " sign-in" : "Sign-in needs attention"; font.bold: true }
                            Hint { text: root.auth.error || "Finish signing in in your browser. This panel will detect completion." }
                            Label { visible: !!root.auth.user_code; text: "Device code: " + (root.auth.user_code || ""); font.bold: true }
                            Row {
                                spacing: Style.space(6)
                                ActionButton { text: "Open sign-in page"; enabled: !root.busy; onClicked: root.perform(["auth-open"]) }
                                ActionButton { text: "Cancel"; enabled: !root.busy; onClicked: root.perform(["auth-cancel"]) }
                            }
                            Hint { text: "If the browser cannot return automatically, paste its callback URL below." }
                            Field { id: callback; placeholderText: "Callback URL"; password: true }
                            ActionButton {
                                text: "Finish sign-in"
                                enabled: !root.busy && callback.text.trim() !== ""
                                onClicked: { root.perform(["auth-callback"], {url: callback.text}); callback.text = "" }
                            }
                        }
                        Column {
                            visible: root.addingAccount && !root.signingIn
                            width: parent.width
                            spacing: Style.space(8)
                            PanelSeparator { foreground: root.foreground }
                            Hint { visible: !root.snapshot.running; text: "Start the proxy before adding an account." }
                            Repeater {
                                model: (root.snapshot.providers || []).filter(function(p) { return p.available })
                                Row {
                                    required property var modelData
                                    width: body.width
                                    spacing: Style.space(8)
                                    ProviderIcon { id: connectIcon; provider: modelData.id; anchors.verticalCenter: parent.verticalCenter }
                                    ActionButton {
                                        width: parent.width - connectIcon.width - parent.spacing
                                        text: "Connect " + modelData.name
                                        enabled: !root.busy && root.snapshot.running
                                        onClicked: root.perform(["auth-start", modelData.id])
                                    }
                                }
                            }
                        }
                        PanelSeparator { foreground: root.foreground }
                        ActionButton { text: root.addingKey ? "Hide API provider form" : "+ API-key provider"; onClicked: root.addingKey = !root.addingKey }
                        Column {
                            visible: root.addingKey
                            width: parent.width
                            spacing: Style.space(8)
                            Hint { text: "Add an OpenAI-compatible endpoint. Quota availability depends on the provider." }
                            Field { id: providerName; placeholderText: "Name, e.g. zai" }
                            Field { id: providerUrl; placeholderText: "Base URL, e.g. https://provider.example/v1" }
                            Field { id: providerKey; placeholderText: "API key"; password: true }
                            Field { id: providerModels; placeholderText: "Model IDs, separated by commas" }
                            ActionButton {
                                text: "Save provider"
                                enabled: root.snapshot.running && !root.busy
                                onClicked: {
                                    root.perform(["custom-add"], {name: providerName.text, url: providerUrl.text, key: providerKey.text, models: providerModels.text})
                                    providerKey.text = ""
                                }
                            }
                        }
                    }

                    Column {
                        visible: root.snapshot.configured && root.page === 2
                        width: parent.width
                        spacing: Style.space(14)
                        Label { text: "Display"; font.bold: true }
                        ActionButton {
                            text: "Extra limits: " + (root.showExtraLimits ? "On" : "Off")
                            active: root.showExtraLimits
                            tooltipText: "Show model-specific and shorter limits for all accounts"
                            onClicked: root.setDisplaySetting("showExtraLimits", !root.showExtraLimits)
                        }
                        PanelSeparator { foreground: root.foreground }
                        Label { text: "Proxy settings"; font.bold: true }
                        ActionButton {
                            text: "Launch at login: " + (root.snapshot.autostart ? "On" : "Off")
                            active: !!root.snapshot.autostart; enabled: !root.busy
                            onClicked: root.perform(["autostart", root.snapshot.autostart ? "off" : "on"])
                        }
                        Row {
                            spacing: Style.space(6)
                            ActionButton { text: "Restart proxy"; enabled: !root.busy; onClicked: root.perform(["restart"]) }
                            ActionButton {
                                text: root.showingLogs ? "Hide logs" : "View logs"
                                onClicked: { root.showingLogs = !root.showingLogs; if (root.showingLogs) root.perform(["logs-view"]) }
                            }
                        }
                        Column {
                            visible: root.showingLogs
                            width: parent.width
                            spacing: Style.space(8)
                            ActionButton { text: "Refresh logs"; enabled: !root.busy; onClicked: root.perform(["logs-view"]) }
                            Label { width: parent.width; text: Limits.maskEmails(root.logText, true) || "Loading logs…"; wrapMode: Text.WrapAnywhere; font.pixelSize: Style.font.caption; opacity: 0.7 }
                        }
                        PanelSeparator { foreground: root.foreground }
                        Label { text: "Account routing"; font.bold: true }
                        Hint { text: "Balance requests across accounts, or use one account until its allowance is exhausted." }
                        Row {
                            spacing: Style.space(6)
                            ActionButton { text: "Balance accounts"; active: root.preferences.routing === "round-robin"; enabled: root.snapshot.running && !root.busy; onClicked: root.perform(["routing", "round-robin"]) }
                            ActionButton { text: "Fill first"; active: root.preferences.routing === "fill-first"; enabled: root.snapshot.running && !root.busy; onClicked: root.perform(["routing", "fill-first"]) }
                        }
                        PanelSeparator { foreground: root.foreground }
                        Label { text: "Connect your coding tools"; font.bold: true }
                        Label { width: parent.width; text: root.snapshot.endpoint || ""; wrapMode: Text.WrapAnywhere; opacity: 0.6; font.pixelSize: Style.font.bodySmall }
                        Row {
                            spacing: Style.space(6)
                            ActionButton { text: "Copy endpoint"; onClicked: root.perform(["copy", "endpoint"]) }
                            ActionButton { text: "Copy API key"; onClicked: root.perform(["copy", "api-key"]) }
                        }
                        ActionButton {
                            text: (root.showingModels ? "Hide" : "Show") + " models (" + (root.snapshot.models || []).length + ")"
                            onClicked: root.showingModels = !root.showingModels
                        }
                        Column {
                            visible: root.showingModels
                            width: parent.width
                            spacing: Style.space(8)
                            Repeater {
                                model: root.snapshot.models || []
                                Label { required property string modelData; width: body.width; text: modelData; wrapMode: Text.WrapAnywhere; font.pixelSize: Style.font.bodySmall }
                            }
                            Hint { visible: !(root.snapshot.models || []).length; text: "No models reported by the enabled accounts." }
                        }
                        Label { text: "CLIProxyAPI " + (root.snapshot.version || "custom"); opacity: 0.35; font.pixelSize: Style.font.caption }
                    }
                }
            }
            Label {
                id: feedback
                width: parent.width; anchors.bottom: parent.bottom
                text: root.notice || root.snapshot.error || (quotaPoll.running ? "Refreshing account limits…" : "LOCAL PROXY · PRIVATE CREDENTIALS")
                color: root.noticeError || root.snapshot.error ? Color.accent : root.foreground
                opacity: root.notice || root.snapshot.error ? 1 : 0.4
                wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight
                font.pixelSize: Style.font.caption
            }
        }
    }
    component Label: Text {
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
    }
    component EmailLabel: Item {
        id: email
        required property string accountKey
        required property string emailText
        readonly property bool privateAddress: emailText.indexOf("@") >= 0
        readonly property bool revealed: !!root.revealedEmails[accountKey]
        readonly property bool concealed: privateAddress && !revealed
        implicitHeight: address.implicitHeight
        activeFocusOnTab: privateAddress
        Keys.onReturnPressed: if (privateAddress) root.toggleEmail(accountKey)
        Keys.onSpacePressed: if (privateAddress) root.toggleEmail(accountKey)
        Accessible.role: Accessible.Button
        Accessible.name: concealed ? "Reveal account email" : privateAddress ? "Hide account email" : emailText
        Label {
            id: address
            width: parent.width
            // Blur a constant placeholder: screenshots cannot recover the real address or its length.
            text: email.concealed ? "private@account.email" : email.emailText
            elide: Text.ElideMiddle
            font.pixelSize: Style.font.caption
            visible: !email.concealed
        }
        GaussianBlur {
            anchors.fill: address
            source: address
            radius: Style.space(7)
            samples: 17
            transparentBorder: true
            visible: email.concealed
        }
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: email.activeFocus ? 1 : 0
            border.color: Color.accent
        }
        MouseArea {
            anchors.fill: parent
            enabled: email.privateAddress
            cursorShape: Qt.PointingHandCursor
            onClicked: root.toggleEmail(email.accountKey)
        }
    }
    component ProviderIcon: Item {
        id: mark
        property string provider: ""
        readonly property bool builtin: provider === "codex" || provider === "claude"
        readonly property var icons: ({"gemini-cli": "gemini", "gemini": "gemini", "qwen": "qwen", "kimi": "kimi", "github-copilot": "githubcopilot", "antigravity": "antigravity", "xai": "grok", "zai": "zai"})
        readonly property bool light: Color.popups.background.r * 0.2126 + Color.popups.background.g * 0.7152 + Color.popups.background.b * 0.0722 > 0.6
        width: Style.space(26)
        height: width
        Image {
            id: logo
            anchors.fill: parent
            source: mark.builtin
                ? "file://" + (Quickshell.env("OMARCHY_PATH") || "/usr/share/omarchy") + "/shell/plugins/agents/assets/" + mark.provider + (mark.provider === "codex" && mark.light ? "-light" : "") + ".svg"
                : mark.icons[mark.provider] ? Qt.resolvedUrl("assets/" + mark.icons[mark.provider] + ".svg") : ""
            sourceSize.width: mark.width * 2
            sourceSize.height: mark.height * 2
            fillMode: Image.PreserveAspectFit
            visible: mark.builtin
        }
        ColorOverlay {
            anchors.fill: parent
            source: logo
            visible: !mark.builtin && logo.status === Image.Ready
            color: root.foreground
        }
        Label {
            anchors.centerIn: parent
            visible: logo.source.toString() === "" || logo.status === Image.Error
            text: root.providerLabel(mark.provider).slice(0, 1).toUpperCase()
            font.bold: true
            font.pixelSize: Style.font.title
        }
    }
    component Hint: Label {
        width: parent.width
        wrapMode: Text.WordWrap
        opacity: 0.55
        font.pixelSize: Style.font.bodySmall
    }
    component Field: TextField {
        width: parent.width
        foreground: root.foreground
        font.pixelSize: Style.font.bodySmall
        selectByMouse: true
    }
    component ActionButton: Button {
        foreground: root.foreground
        fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
        fontSize: Style.font.bodySmall
        bordered: true; focusable: true
        opacity: enabled ? 1 : 0.35
    }
}
