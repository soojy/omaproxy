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
    property var updates: ({})
    property var routingSettings: ({values: {}, capabilities: {}, strategies: []})
    property var diagnostics: ({})
    property var customProviders: []
    property bool providerWeightsSupported: false
    property bool showingDiagnostics: false
    property bool showingRouting: false
    property bool pageRefreshPending: false
    property string editingProvider: ""
    property string originalProviderUrl: ""
    property string originalProviderModels: ""
    property string removingProvider: ""
    property var clientKeys: []
    property bool showingClientKeys: false
    property string revokingClient: ""
    readonly property bool quotaAlerts: setting("quotaAlerts", false) === true
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
    property int authRevision: 0
    property int connectionRevision: 0
    property bool changingConnection: false
    property bool editRemote: false
    property bool removeRemoteApiKey: false
    readonly property bool remoteConnection: snapshot.mode === "remote"
    property double now: Date.now() / 1000
    readonly property bool busy: action.running
    readonly property var proxyPower: Limits.powerState(snapshot.service)
    readonly property bool signingIn: auth.status === "wait"
    readonly property var quotaAccounts: Limits.quotaAccounts(quotaData.accounts, snapshot)
    readonly property int limitAccountCount: snapshot.running ? (snapshot.accounts || []).length : quotaAccounts.length
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function refresh() { if (!poll.running && !changingConnection) poll.running = true }
    function refreshActivePage() { pageRefreshPending = page === 1 || page === 2 }
    function refreshQuotas(force) {
        if (!quotaPoll.running && snapshot.running && !changingConnection) {
            quotaPoll.command = ["python3", "-B", helper, "quotas"].concat(force ? ["--force"] : []).concat(quotaAlerts ? ["--notify"] : [])
            quotaPoll.running = true
        }
    }
    function copyValue(kind) {
        if (clipboard.running) return
        noticeError = false
        notice = ""
        clipboard.command = ["python3", "-B", helper, "copy", kind]
        clipboard.running = true
    }
    function copyClientKey(name) {
        if (clipboard.running) return
        clipboard.command = ["python3", "-B", helper, "client-copy", name]
        clipboard.running = true
    }
    function perform(args, payload) {
        if (busy) return
        changingConnection = args[0] === "connection-save" || args[0] === "connection-local"
        if (changingConnection) { connectionRevision++; authRevision++ }
        if (args[0].indexOf("auth-") === 0) authRevision++
        noticeError = false
        notice = args[0] === "setup" ? "Downloading and verifying CLIProxyAPI…" : changingConnection ? "Checking connection…" : ""
        action.payload = payload === undefined ? "" : JSON.stringify(payload) + "\n"
        action.stdinEnabled = action.payload !== ""
        action.command = ["python3", "-B", helper].concat(args)
        action.running = true
    }
    function clearConnectionState() {
        preferences = ({}); updates = ({})
        routingSettings = ({values: {}, capabilities: {}, strategies: []})
        diagnostics = ({}); customProviders = []; clientKeys = []
        providerWeightsSupported = false; showingDiagnostics = false
        showingRouting = false; showingClientKeys = false
        editingProvider = ""; removingProvider = ""; revokingClient = ""
        originalProviderUrl = ""; originalProviderModels = ""
        providerKey.text = ""; callback.text = ""
        remoteManagementKey.text = ""; remoteApiKey.text = ""
        removeRemoteApiKey = false
        logText = ""; showingLogs = false; addingAccount = false; addingKey = false
    }
    function receive(result) {
        if (!result.connection_changed && result.connection_id !== snapshot.connection_id) return
        if (result.error) { noticeError = true; notice = result.error; return }
        if (result.connection_changed) {
            clearConnectionState()
            snapshot = ({configured: false, running: false, accounts: [], models: [], providers: [], connection_id: result.connection_id})
            quotaData = ({accounts: []})
            auth = ({})
            preferences = ({})
            revealedEmails = ({})
            logText = ""
            showingLogs = false
            addingAccount = false
            addingKey = false
            editRemote = false
        }
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
        if (result.updates) updates = result.updates
        if (result.routing_settings) routingSettings = result.routing_settings
        if (result.diagnostics) diagnostics = result.diagnostics
        if (result.custom_providers) customProviders = result.custom_providers
        if (result.custom_provider) { addingKey = false; editingProvider = ""; providerKey.text = "" }
        if (result.client_keys) clientKeys = result.client_keys
        if (result.provider_weights_supported !== undefined) providerWeightsSupported = result.provider_weights_supported
        if (result.logs !== undefined) logText = result.logs
        if (result.message) notice = result.message
        if (result.alerts && result.alerts.error) { noticeError = true; notice = result.alerts.error }
    }
    function setDisplaySetting(name, value) {
        var next = Object.assign({}, settings)
        next[name] = value
        root.settings = next
        if (bar && bar.shell) bar.shell.updateEntryInline(moduleName, next)
    }
    function accountLabel(a) { return a.email || a.label || a.name || "Account" }
    function diagnosticSummary(section) {
        if (!section || !section.availability) return "Not loaded"
        return section.availability + (section.retained === undefined ? "" : " · " + section.retained + " shown · " + (section.invalid || 0) + " unrecognized · " + (section.omitted || 0) + " omitted")
    }
    function diagnosticEventDetails(event) {
        var parts = []
        if (event.timestamp) parts.push(event.timestamp)
        if (event.provider) parts.push(event.provider)
        if (event.model_label) parts.push(event.model_label)
        if (typeof event.status_code === "number") parts.push("HTTP " + event.status_code)
        if (typeof event.ttft_ms === "number") parts.push("First token " + event.ttft_ms + " ms")
        Object.keys(event.tokens || {}).forEach(function(field) { parts.push(field.replace(/_/g, " ") + ": " + event.tokens[field]) })
        return parts.join(" · ")
    }
    function editProvider(provider) {
        editingProvider = provider.name
        providerName.text = provider.name
        providerUrl.text = provider.url
        providerModels.text = JSON.stringify(provider.models)
        originalProviderUrl = providerUrl.text
        originalProviderModels = providerModels.text
        providerKey.text = ""
        providerWeight.text = ""
        providerCredential.text = "0"
        addingKey = true
    }
    function newProvider() {
        editingProvider = ""
        providerName.text = ""
        providerUrl.text = ""
        providerModels.text = ""
        providerKey.text = ""
        providerWeight.text = ""
        providerCredential.text = "0"
        addingKey = true
    }
    function saveProvider() {
        try {
            var models = providerModels.text.trim()
            var payload = {name: providerName.text, key: providerKey.text}
            if (!editingProvider || providerUrl.text !== originalProviderUrl) payload.url = providerUrl.text
            if (!editingProvider || providerModels.text !== originalProviderModels) payload.models = models[0] === "[" ? JSON.parse(models) : models
            if (providerKey.text !== "" || providerWeight.text.trim() !== "") payload.credential_index = Number(providerCredential.text)
            if (providerWeight.text.trim() !== "") payload.weight = Number(providerWeight.text)
            perform(["custom-save"], payload)
            providerKey.text = ""
        } catch (e) { noticeError = true; notice = "Enter model IDs or a valid JSON model list." }
    }
    function saveRetryLimits() {
        if (![retryRounds.text, retryCredentials.text, retryWait.text].every(function(value) { return /^[0-9]+$/.test(value.trim()) })) {
            noticeError = true
            notice = "Enter a whole number in each retry field."
            return
        }
        perform(["routing-save"], {"request-retry": Number(retryRounds.text), "max-retry-credentials": Number(retryCredentials.text), "max-retry-interval": Number(retryWait.text)})
    }
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
        if (opened) {
            refresh(); refreshQuotas(false)
            if (snapshot.configured && !remoteConnection && !authPoll.running) authPoll.running = true
            refreshActivePage()
        } else {
            revealedEmails = ({}); removingProvider = ""; revokingClient = ""
            providerKey.text = ""; callback.text = ""; addingKey = false; editingProvider = ""
            remoteManagementKey.text = ""; remoteApiKey.text = ""
            pageRefreshPending = false
        }
    }
    onPageChanged: {
        scroll.contentY = 0
        removingProvider = ""
        revokingClient = ""
        refreshActivePage()
    }
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
        property int revision: 0
        onStarted: revision = root.connectionRevision
        onExited: if (revision !== root.connectionRevision) Qt.callLater(root.refresh)
        command: ["python3", "-B", root.helper, "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                if (poll.revision !== root.connectionRevision || root.changingConnection) return
                try {
                    var result = JSON.parse(text)
                    if (result.configured !== undefined) {
                        if (result.connection_id !== root.snapshot.connection_id) {
                            root.clearConnectionState()
                            root.connectionRevision++
                            root.authRevision++
                            root.quotaData = ({accounts: []})
                            root.auth = ({})
                            root.preferences = ({})
                            root.revealedEmails = ({})
                            remoteUrl.text = result.base_url || result.remote_base_url || ""
                        }
                        var wasRunning = root.snapshot.running
                        var oldNames = (root.snapshot.accounts || []).map(function(a) { return a.name }).join("|")
                        root.snapshot = result
                        if (result.quotas) root.quotaData = result.quotas
                        var newNames = (result.accounts || []).map(function(a) { return a.name }).join("|")
                        if (root.opened && result.running && (!wasRunning || oldNames !== newNames)) root.refreshQuotas(false)
                        if (root.opened && result.running && !wasRunning) root.refreshActivePage()
                    } else root.receive(result)
                } catch (e) { root.notice = "Unable to read proxy status."; root.noticeError = true }
            }
        }
    }
    Process {
        id: quotaPoll
        property int revision: 0
        onStarted: revision = root.connectionRevision
        onExited: if (revision !== root.connectionRevision) Qt.callLater(function() { root.refreshQuotas(false) })
        stdout: StdioCollector {
            onStreamFinished: {
                if (quotaPoll.revision !== root.connectionRevision || root.changingConnection) return
                try {
                    var result = JSON.parse(text)
                    if (result.connection_id !== root.snapshot.connection_id) return
                    if (result.quotas) root.quotaData = result.quotas
                    root.receive(result)
                } catch (e) { root.notice = "Unable to read account limits."; root.noticeError = true }
            }
        }
    }
    Process {
        id: authPoll
        property int revision: 0
        onStarted: revision = root.authRevision
        command: ["python3", "-B", root.helper, "auth-status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { if (authPoll.revision === root.authRevision && !root.busy) root.receive(JSON.parse(text)) } catch (e) {}
            }
        }
    }
    Process {
        id: clipboard
        property int revision: 0
        onStarted: revision = root.connectionRevision
        stdout: StdioCollector {
            onStreamFinished: {
                if (clipboard.revision !== root.connectionRevision || root.changingConnection) return
                try { root.receive(JSON.parse(text)) }
                catch (e) { root.notice = "Unable to copy to clipboard."; root.noticeError = true }
            }
        }
    }
    Process {
        id: action
        property string payload: ""
        onStarted: if (payload !== "") { write(payload); payload = "" }
        onExited: { root.changingConnection = false; Qt.callLater(root.refresh) }
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.receive(JSON.parse(text)) }
                catch (e) { root.notice = "The action returned no result."; root.noticeError = true }
                root.refresh()
            }
        }
    }
    Timer {
        interval: 100
        running: root.opened && root.snapshot.running && root.pageRefreshPending && !root.busy
        repeat: false
        onTriggered: {
            root.pageRefreshPending = false
            if (root.page === 2) root.perform(["preferences"])
            else if (root.page === 1) root.perform(["custom-list"])
        }
    }
    Timer { interval: root.opened ? 5000 : 20000; running: true; repeat: true; onTriggered: root.refresh() }
    Timer { interval: root.opened ? 60000 : 300000; running: (root.opened || root.quotaAlerts) && root.snapshot.running; repeat: true; onTriggered: root.refreshQuotas(false) }
    Timer { interval: 2000; running: root.signingIn && !root.remoteConnection; repeat: true; onTriggered: if (!authPoll.running && !root.busy) authPoll.running = true }
    Timer { interval: 10000; running: root.opened; repeat: true; onTriggered: root.now = Date.now() / 1000 }

    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "󰚩"
        active: root.snapshot.running
        activeColor: Color.accent
        tooltipText: "OmaProxy · " + (root.snapshot.running ? "Account limits" : root.remoteConnection ? "Remote server unavailable" : "Proxy stopped")
        onPressed: root.toggle()
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
                PanelHero {
                    width: parent.width
                    title: "OmaProxy"
                    meta: "Account limits"
                    foreground: root.foreground
                    fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
                    iconComponent: Component {
                        Text {
                            textFormat: Text.PlainText
                            text: "󰚩"
                            color: root.foreground
                            font.family: root.bar ? root.bar.fontFamily : Style.font.family
                            font.pixelSize: Style.font.display
                        }
                    }
                    trailingControl: Component {
                        ToggleSwitch {
                            id: powerSwitch
                            visible: root.snapshot.configured && !root.remoteConnection
                            checked: root.proxyPower.checked
                            busy: root.busy || poll.running || root.proxyPower.transitioning
                            foreground: root.foreground
                            activeFocusOnTab: visible
                            hasCursor: activeFocus
                            Accessible.role: Accessible.CheckBox
                            Accessible.name: "Proxy enabled"
                            Accessible.checkable: true
                            Accessible.checked: checked
                            function activate() {
                                if (!busy) root.perform([checked ? "stop" : "start"])
                            }
                            onToggled: activate()
                            Keys.onReturnPressed: activate()
                            Keys.onEnterPressed: activate()
                            Keys.onSpacePressed: activate()
                            PanelToolTip {
                                visible: powerSwitch.containsMouse
                                text: root.busy || root.proxyPower.transitioning ? "Updating proxy…" : powerSwitch.checked ? "Stop proxy" : "Start proxy"
                                fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
                            }
                        }
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
                        visible: !root.snapshot.configured && root.page !== 2
                        width: parent.width
                        spacing: Style.space(16)
                        Label { text: "Your accounts. Your remaining capacity."; font.bold: true; width: parent.width; wrapMode: Text.WordWrap }
                        Hint { text: "Connect to an existing server or set up a local proxy to see account limits." }
                        ActionButton { text: "Connect to remote server"; enabled: !root.busy; onClicked: { root.editRemote = true; root.page = 2 } }
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
                                Label { text: root.limitAccountCount + (root.snapshot.running ? " connected account(s)" : " cached account(s)"); font.bold: true }
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
                            text: root.remoteConnection ? "Remote server unavailable. Previous readings stay visible. Check the connection in Settings." : root.proxyPower.checked ? "Proxy API is unavailable. Previous readings stay visible." : "Start the proxy to refresh limits. Previous readings stay visible."
                        }
                        Column {
                            visible: root.limitAccountCount === 0
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
                            ActionButton { id: addAccount; text: root.remoteConnection ? "Manage accounts" : root.addingAccount ? "Done" : "+ Add account"; enabled: !root.busy; onClicked: { if (root.remoteConnection) root.perform(["dashboard"]); else root.addingAccount = !root.addingAccount } }
                        }
                        Hint { visible: root.remoteConnection || !(root.snapshot.accounts || []).length; text: root.remoteConnection ? "Add accounts in the server's management panel. Changes here affect that server's clients." : "Add a subscription account. Browser sign-in returns to this plugin automatically." }
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
                            visible: root.addingAccount && !root.signingIn && !root.remoteConnection
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
                        Label { text: "API-key providers"; font.bold: true }
                        ActionButton { text: "Refresh providers"; enabled: root.snapshot.running && !root.busy; onClicked: root.perform(["custom-list"]) }
                        Repeater {
                            model: root.customProviders
                            Column {
                                required property var modelData
                                width: body.width
                                spacing: Style.space(6)
                                Label { width: parent.width; text: modelData.name + " · " + modelData.credential_count + " credential(s)"; wrapMode: Text.WordWrap }
                                Repeater {
                                    model: modelData.credentials || []
                                    Hint { required property var modelData; text: "Credential " + modelData.index + " · weight " + (modelData.weight === null || modelData.weight === undefined ? "1 (default)" : modelData.weight) }
                                }
                                Row {
                                    spacing: Style.space(6)
                                    ActionButton { text: "Edit"; enabled: !root.busy; onClicked: root.editProvider(modelData) }
                                    ActionButton { text: "Test models"; enabled: root.snapshot.running && !root.busy; onClicked: root.perform(["custom-test", modelData.name]) }
                                    ActionButton {
                                        text: root.removingProvider === modelData.name ? "Confirm removal" : "Remove"
                                        enabled: root.snapshot.running && !root.busy
                                        onClicked: {
                                            if (root.removingProvider === modelData.name) { root.perform(["custom-remove", modelData.name]); root.removingProvider = "" }
                                            else root.removingProvider = modelData.name
                                        }
                                    }
                                }
                            }
                        }
                        Hint { text: "Test models performs model discovery only. It does not send an inference request." }
                        ActionButton { text: root.addingKey ? "Hide API provider form" : "+ API-key provider"; onClicked: { if (root.addingKey) root.addingKey = false; else root.newProvider() } }
                        Column {
                            visible: root.addingKey
                            width: parent.width
                            spacing: Style.space(8)
                            Hint { text: root.editingProvider ? "Edit provider. A blank API key preserves its existing credentials." : "Add an OpenAI-compatible endpoint. Quotas may be unavailable." }
                            Field { id: providerName; placeholderText: "Name, e.g. zai"; enabled: root.editingProvider === "" }
                            Field { id: providerUrl; placeholderText: "Base URL, e.g. https://provider.example/v1" }
                            Field { id: providerKey; placeholderText: "API key"; password: true }
                            Field { id: providerModels; placeholderText: "Model IDs, or JSON with name and alias" }
                            Hint { text: 'Aliases: [{"name":"upstream-model","alias":"coding-model"}]' }
                            Field { id: providerCredential; placeholderText: "Credential index (0 is the first)"; visible: root.editingProvider !== "" }
                            Field { id: providerWeight; placeholderText: "Optional weight (0 excludes this credential)"; visible: root.providerWeightsSupported }
                            ActionButton {
                                text: "Save provider"
                                enabled: root.snapshot.running && !root.busy
                                onClicked: {
                                    root.saveProvider()
                                }
                            }
                        }
                    }

                    Column {
                        visible: root.page === 2
                        width: parent.width
                        spacing: Style.space(14)
                        Label { text: "Connection"; font.bold: true }
                        Hint { text: root.remoteConnection ? "Remote server · " + (root.snapshot.base_url || "") : "Local proxy" }
                        Row {
                            spacing: Style.space(6)
                            ActionButton {
                                text: "Local"
                                active: !root.remoteConnection && !root.editRemote
                                enabled: !root.busy
                                onClicked: { if (root.remoteConnection) root.perform(["connection-local"]); else root.editRemote = false }
                            }
                            ActionButton { text: "Remote"; active: root.remoteConnection || root.editRemote; enabled: !root.busy; onClicked: root.editRemote = true }
                        }
                        Column {
                            visible: root.remoteConnection || root.editRemote || !root.snapshot.configured
                            width: parent.width
                            spacing: Style.space(8)
                            Hint { text: "Enter the server base URL without /v1. Use HTTPS, or localhost HTTP for an SSH tunnel." }
                            Field { id: remoteUrl; placeholderText: "Server URL, e.g. https://proxy.example.com"; text: root.snapshot.base_url || root.snapshot.remote_base_url || ""; enabled: !root.busy }
                            Field { id: remoteManagementKey; placeholderText: "Management key"; password: true; enabled: !root.busy }
                            Field { id: remoteApiKey; placeholderText: "Client API key (optional, for models)"; password: true; enabled: !root.busy }
                            Hint { text: "Blank keys keep saved values for the same URL. The management key enables accounts and quotas; the client key enables model discovery." }
                            ActionButton {
                                visible: root.remoteConnection && root.snapshot.has_api_key
                                text: root.removeRemoteApiKey ? "Client key will be removed on save" : "Remove saved client API key"
                                enabled: !root.busy
                                onClicked: { root.removeRemoteApiKey = true; remoteApiKey.text = "" }
                            }
                            ActionButton {
                                text: root.changingConnection ? "Checking…" : "Test and save connection"
                                enabled: !root.busy && remoteUrl.text.trim() !== ""
                                onClicked: {
                                    root.perform(["connection-save"], {base_url: remoteUrl.text, management_key: remoteManagementKey.text, api_key: remoteApiKey.text, clear_api_key: root.removeRemoteApiKey})
                                    remoteManagementKey.text = ""
                                    remoteApiKey.text = ""
                                }
                            }
                        }
                        ActionButton { visible: !root.snapshot.configured && !root.editRemote; text: "Set up local proxy"; enabled: !root.busy; onClicked: root.perform(["setup"]) }
                        PanelSeparator { foreground: root.foreground }
                        Label { text: "Display"; font.bold: true }
                        ActionButton {
                            text: "Extra limits: " + (root.showExtraLimits ? "On" : "Off")
                            active: root.showExtraLimits
                            tooltipText: "Show model-specific and shorter limits for all accounts"
                            onClicked: root.setDisplaySetting("showExtraLimits", !root.showExtraLimits)
                        }
                        ActionButton {
                            text: "Quota alerts: " + (root.quotaAlerts ? "On" : "Off")
                            active: root.quotaAlerts
                            onClicked: root.setDisplaySetting("quotaAlerts", !root.quotaAlerts)
                        }
                        Hint { text: "Optional alerts check limits every five minutes while closed. Stale or unknown limits never trigger low-allowance alerts." }
                        PanelSeparator { foreground: root.foreground }
                        Label { visible: root.snapshot.configured && !root.remoteConnection; text: "Proxy settings"; font.bold: true }
                        ActionButton {
                            visible: root.snapshot.configured && !root.remoteConnection
                            text: "Launch at login: " + (root.snapshot.autostart ? "On" : "Off")
                            active: !!root.snapshot.autostart; enabled: !root.busy
                            onClicked: root.perform(["autostart", root.snapshot.autostart ? "off" : "on"])
                        }
                        Row {
                            visible: root.snapshot.configured && !root.remoteConnection
                            spacing: Style.space(6)
                            ActionButton { text: "Restart proxy"; enabled: !root.busy; onClicked: root.perform(["restart"]) }
                            ActionButton {
                                text: root.showingLogs ? "Hide logs" : "View logs"
                                onClicked: { root.showingLogs = !root.showingLogs; if (root.showingLogs) root.perform(["logs-view"]) }
                            }
                        }
                        Column {
                            visible: root.showingLogs && !root.remoteConnection
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
                            Repeater {
                                model: root.routingSettings.strategies.length ? root.routingSettings.strategies : ["round-robin", "fill-first"]
                                ActionButton {
                                    required property string modelData
                                    text: modelData === "round-robin" ? "Balance" : modelData === "weighted-round-robin" ? "Weighted" : "Fill first"
                                    active: root.preferences.routing === modelData
                                    enabled: root.snapshot.running && !root.busy
                                    onClicked: root.perform(["routing", modelData])
                                }
                            }
                        }
                        ActionButton { text: root.showingRouting ? "Hide routing details" : "Routing details"; onClicked: root.showingRouting = !root.showingRouting }
                        Column {
                            visible: root.showingRouting
                            width: parent.width
                            spacing: Style.space(8)
                            Repeater {
                                model: [{field: "session-affinity", label: "Keep conversations on one account"},
                                        {field: "session-affinity-subagents", label: "Subagents inherit the conversation account"},
                                        {field: "disable-cooling", label: "Disable cooldowns"},
                                        {field: "save-cooldown-status", label: "Persist cooldown state"}]
                                ActionButton {
                                    required property var modelData
                                    width: parent.width
                                    text: modelData.label + ": " + (root.routingSettings.values[modelData.field] ? "On" : "Off")
                                    active: root.routingSettings.values[modelData.field] === true
                                    enabled: root.snapshot.running && !root.busy && root.routingSettings.capabilities[modelData.field] === true
                                    onClicked: { var change = {}; change[modelData.field] = !root.routingSettings.values[modelData.field]; root.perform(["routing-save"], change) }
                                }
                            }
                            Field { id: affinityTtl; text: root.routingSettings.values["session-affinity-ttl"] || "1h"; placeholderText: "Conversation affinity duration, e.g. 1h" }
                            ActionButton { text: "Save affinity duration"; enabled: root.snapshot.running && !root.busy && root.routingSettings.capabilities["session-affinity-ttl"] === true; onClicked: root.perform(["routing-save"], {"session-affinity-ttl": affinityTtl.text}) }
                            Hint { text: "Additional retry rounds / credentials per round / maximum cooldown wait (seconds). A credential cap of 0 means all eligible credentials." }
                            Row {
                                width: parent.width
                                spacing: Style.space(6)
                                Field { id: retryRounds; width: (parent.width - parent.spacing * 2) / 3; text: String(root.routingSettings.values["request-retry"] === undefined ? 3 : root.routingSettings.values["request-retry"]) }
                                Field { id: retryCredentials; width: (parent.width - parent.spacing * 2) / 3; text: String(root.routingSettings.values["max-retry-credentials"] === undefined ? 0 : root.routingSettings.values["max-retry-credentials"]) }
                                Field { id: retryWait; width: (parent.width - parent.spacing * 2) / 3; text: String(root.routingSettings.values["max-retry-interval"] === undefined ? 30 : root.routingSettings.values["max-retry-interval"]) }
                            }
                            ActionButton { text: "Save retry limits"; enabled: root.snapshot.running && !root.busy && root.routingSettings.capabilities["request-retry"] === true && root.routingSettings.capabilities["max-retry-credentials"] === true && root.routingSettings.capabilities["max-retry-interval"] === true; onClicked: root.saveRetryLimits() }
                            Repeater { model: root.routingSettings.limitations || []; Hint { required property string modelData; text: modelData } }
                        }
                        PanelSeparator { foreground: root.foreground }
                        ActionButton { text: root.showingDiagnostics ? "Hide diagnostics" : "Show diagnostics"; enabled: root.snapshot.running && !root.busy; onClicked: { root.showingDiagnostics = !root.showingDiagnostics; if (root.showingDiagnostics) root.perform(["diagnostics"]) } }
                        Column {
                            visible: root.showingDiagnostics
                            width: parent.width
                            spacing: Style.space(8)
                            ActionButton { text: "Refresh counters"; enabled: !root.busy; onClicked: root.perform(["diagnostics"]) }
                            Hint { text: "Account counters describe backend attempts. Upstream-key counters exclude OAuth accounts; they are not client usage or billing totals." }
                            Hint { text: "Accounts: " + root.diagnosticSummary(root.diagnostics.accounts) }
                            Repeater {
                                model: (root.diagnostics.accounts || {}).records || []
                                Label { required property var modelData; width: parent.width; text: modelData.provider + " · " + modelData.label + " · " + modelData.success + " succeeded / " + modelData.failed + " failed"; wrapMode: Text.WrapAnywhere; font.pixelSize: Style.font.caption }
                            }
                            Repeater {
                                model: (root.diagnostics.usage || {}).records || []
                                Label { required property var modelData; width: parent.width; text: modelData.provider + " · " + modelData.label + " · " + modelData.success + " succeeded / " + modelData.failed + " failed"; wrapMode: Text.WrapAnywhere; font.pixelSize: Style.font.caption }
                            }
                            Hint { text: "Upstream keys: " + root.diagnosticSummary(root.diagnostics.usage) }
                            Hint { text: ((root.diagnostics.accounts || {}).error || (root.diagnostics.usage || {}).error || "") }
                            Hint { text: "Capture pending activity removes up to 50 usage events from the backend queue. Other collectors will not receive them. No prompts are retained." }
                            ActionButton { text: "Capture pending activity"; enabled: !root.busy; onClicked: root.perform(["capture-activity"]) }
                            Hint { text: (root.diagnostics.queue || {}).error || "" }
                            Hint { text: "Activity: " + root.diagnosticSummary(root.diagnostics.queue) }
                            Repeater {
                                model: (root.diagnostics.queue || {}).events || []
                                Column {
                                    required property var modelData
                                    width: parent.width
                                    spacing: Style.space(4)
                                    Label { width: parent.width; text: modelData.client_name || modelData.client_label || "Client unavailable"; font.pixelSize: Style.font.caption }
                                    Label { width: parent.width; text: (modelData.request_label || "Request ID unavailable") + " · " + (modelData.account_label || "Account unavailable") + " · " + (modelData.outcome || "Outcome unavailable") + (typeof modelData.latency_ms === "number" ? " · " + modelData.latency_ms + " ms" : ""); wrapMode: Text.WrapAnywhere; font.pixelSize: Style.font.caption }
                                    Hint { width: parent.width; text: root.diagnosticEventDetails(modelData); visible: text !== "" }
                                }
                            }
                            Repeater { model: root.diagnostics.limitations || []; Hint { required property string modelData; text: modelData } }
                        }
                        PanelSeparator { foreground: root.foreground }
                        Label { text: "Connect your coding tools"; font.bold: true }
                        Label { width: parent.width; text: root.snapshot.endpoint || ""; wrapMode: Text.WrapAnywhere; opacity: 0.6; font.pixelSize: Style.font.bodySmall }
                        Row {
                            spacing: Style.space(6)
                            ActionButton { text: "Copy endpoint"; enabled: root.snapshot.configured && !clipboard.running; onClicked: root.copyValue("endpoint") }
                            ActionButton { text: "Copy API key"; enabled: root.snapshot.configured && !clipboard.running && (!root.remoteConnection || root.snapshot.has_api_key); onClicked: root.copyValue("api-key") }
                        }
                        ActionButton {
                            text: root.showingClientKeys ? "Hide client keys" : "Named client keys"
                            enabled: root.snapshot.running && !root.busy
                            onClicked: { root.showingClientKeys = !root.showingClientKeys; if (root.showingClientKeys) root.perform(["client-keys"]) }
                        }
                        Column {
                            visible: root.showingClientKeys
                            width: parent.width
                            spacing: Style.space(8)
                            Hint { text: "Create a separate key for each client, then configure that client with the endpoint and copied key. Existing clients keep working with the primary key." }
                            Field { id: clientName; placeholderText: "Client name, e.g. t3-code or codex-cli" }
                            ActionButton { text: "Create client key"; enabled: !root.busy && clientName.text.trim() !== ""; onClicked: root.perform(["client-create", clientName.text.trim()]) }
                            ActionButton { text: "Refresh client keys"; enabled: !root.busy; onClicked: root.perform(["client-keys"]) }
                            Repeater {
                                model: root.clientKeys
                                Column {
                                    required property var modelData
                                    width: body.width
                                    spacing: Style.space(6)
                                    Label { text: modelData.name + " · " + (modelData.active ? "Active" : "Creation unconfirmed or key removed"); width: parent.width; wrapMode: Text.WordWrap }
                                    Row {
                                        spacing: Style.space(6)
                                        ActionButton { text: "Copy client key"; enabled: modelData.active && !clipboard.running && !root.busy; onClicked: root.copyClientKey(modelData.name) }
                                        ActionButton {
                                            text: root.revokingClient === modelData.name ? "Confirm revocation" : "Revoke"
                                            enabled: !root.busy
                                            onClicked: { if (root.revokingClient === modelData.name) { root.perform(["client-revoke", modelData.name]); root.revokingClient = "" } else root.revokingClient = modelData.name }
                                        }
                                    }
                                }
                            }
                            Hint { text: "Revoking a key disconnects clients using it. Keys are copied only to the clipboard; prompts and raw keys are absent from diagnostics." }
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
                        PanelSeparator { foreground: root.foreground }
                        Column {
                            visible: !root.remoteConnection
                            width: parent.width
                            spacing: Style.space(8)
                        Label { text: "Backend updates"; font.bold: true }
                        Hint { text: "Installed: " + (root.updates.installed_version || root.snapshot.version || "unknown") + " · Reviewed: " + (root.updates.reviewed_version || "check for updates") }
                        Hint { visible: !!root.updates.latest_version; text: "Latest upstream: " + (root.updates.latest_version || "") }
                        Hint { text: "Updating briefly restarts a running proxy. Your configuration and previous backend are kept for rollback." }
                        ActionButton { visible: !root.remoteConnection; text: "Check backend updates"; enabled: !root.busy; onClicked: root.perform(["check-updates"]) }
                        ActionButton {
                            visible: !root.remoteConnection && root.updates.update_supported === true && root.updates.update_available === true
                            text: "Install reviewed update"
                            enabled: !root.busy
                            onClicked: root.perform(["backend-update"])
                        }
                        ActionButton {
                            visible: !root.remoteConnection && root.updates.rollback_available === true
                            text: "Restore previous backend"
                            enabled: !root.busy
                            onClicked: root.perform(["backend-rollback"])
                        }
                        Hint { visible: !!root.updates.error; text: root.updates.error || "" }
                        }
                        Hint { visible: !!root.snapshot.model_error; text: root.snapshot.model_error || "" }
                        Hint { visible: root.remoteConnection && !root.snapshot.has_api_key; text: "Add a client API key above to list models." }
                        Label { text: root.remoteConnection ? "CLIProxyAPI · Remote" : "CLIProxyAPI " + (root.snapshot.version || "custom"); opacity: 0.35; font.pixelSize: Style.font.caption }
                    }
                }
            }
            Label {
                id: feedback
                width: parent.width; anchors.bottom: parent.bottom
                text: root.notice || root.snapshot.error || (quotaPoll.running ? "Refreshing account limits…" : root.remoteConnection ? "REMOTE SERVER · " + (root.snapshot.running ? "CONNECTED" : "UNAVAILABLE") : "LOCAL PROXY · PRIVATE CREDENTIALS")
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
