# Native preview

Run the checkout QML on an Omarchy desktop with its installed Quickshell and
shared shell components:

```sh
python3 scripts/preview-plugin.py --page settings
# Preview another checkout without copying infrastructure into it:
python3 scripts/preview-plugin.py --repo /path/to/checkout --page settings
```

The launcher creates a private temporary configuration, copies `BarWidget.qml`,
`LimitModel.js` and assets, and links the installed `Commons` and `Ui` modules.
It replaces the Python bridge with `tests/fixtures/preview_bridge.py`. All
accounts use `example.invalid` addresses. The fixture has no network, service,
clipboard, provider, installation or real configuration operations.

The separate preview bar and popup briefly take native keyboard focus. They use
the actual Omarchy `Panel`, `KeyboardPanel`, `BarIconButton` and control types.
The existing shell stays running. Press Ctrl+C in the launching terminal to
stop the preview. Use `--duration 30` to stop it automatically. Temporary files
are removed on exit unless `--keep` is supplied. `--keep` retains the copied
source, fixture state, command trace, log and smoke capture in a private `/tmp`
directory; remove that directory after inspecting it.

Startup IPC attempts share a fifteen-second deadline, with at most 50 attempts
and a five-second timeout per attempt, capped by the remaining startup time.
Smoke IPC calls have a ten-second timeout; a timed-out call aborts the smoke
lane. The launcher terminates the preview and removes its temporary files on
failure, escalating to a kill if the child does not stop, unless `--keep` was
supplied to retain files for inspection.

The launcher prints its configuration path and a scoped IPC command. Always
pass that exact path when addressing the preview. For example:

```sh
quickshell ipc -p /tmp/omaproxy-preview-EXAMPLE call soojy.omaproxy showPage accounts
quickshell ipc -p /tmp/omaproxy-preview-EXAMPLE call omaproxy-preview controls
quickshell ipc -p /tmp/omaproxy-preview-EXAMPLE call omaproxy-preview state
quickshell ipc -p /tmp/omaproxy-preview-EXAMPLE call omaproxy-preview quit
```

The plugin IPC target keeps its normal name but configuration selection isolates
it from the installed plugin. The extra `omaproxy-preview` target belongs only
to the temporary host. Its `activate` function invokes one enabled, visible
native button's click handler by exact label. Its `capture` function captures
the rendered popup card through Qt's `grabToImage`; it excludes unrelated
windows and desktop content.

## Repeatable verification

```sh
python3 scripts/preview-plugin.py --smoke --keep
```

The smoke lane waits for fixture status and switches through native tab controls.
It detects the feature set in the checkout and verifies the corresponding
handlers and state transitions:

- Cold Settings startup with its initial status response deliberately delayed.
  The lane observes the initial stopped snapshot and verifies that the queued
  `preferences` request loads routing values before any tab navigation. It waits
  for queued page refreshes to finish before activating subsequent controls.
- Backend update check, reviewed fixture install and restore.
- Weighted routing, conversation affinity, subagent affinity, cooldown toggles,
  duration and retry edits, rejecting blank or fractional retry inputs before
  invoking the bridge, quota alert opt-in and opt-out, and alert-delivery errors
  from an opted-in native quota refresh. The fixture sends no notifications.
- Read-only diagnostics refresh and explicit fixture activity capture, displayed
  retained/unrecognized/omitted counts, named client labels, timestamp, HTTP
  status, model pseudonym, latency, first-token time and token counters.
- Named client-key creation, refresh and copy, staged revocation reset on page
  changes, and confirmed revocation. No raw key is generated, displayed or copied
  by the fixture.
- Provider discovery, editing JSON model aliases, preserving credential counts,
  credential weights, staged removal, confirmation reset on page changes,
  confirmed removal and creation with dummy credentials. URL-only edits omit
  unchanged models from the stdin payload and preserve aliases. The fixture
  uses the `provider_weights_supported` capability and public credential rows.
  Confirmed saves close the form; reopening starts with the refreshed values.
- Remote connection save with dummy keys, saved client-key removal and local
  connection selection.

It closes and reopens Accounts, checks that the email reveal state is empty,
that password fields are cleared and that the active Accounts tab refreshes,
captures the rendered cards, waits for complete PNG files, and checks the
fixture command trace. It exits nonzero if a control, state transition or
capture is missing. Field values use percent-encoded IPC transport so brackets
in JSON aliases arrive intact. The native form still parses those values and
submits its own normal stdin payload to the fixture.

Inspect the retained PNG files and `quickshell.log` before treating the visual
check as complete. All contracts return synthetic values. Quota alert settings
use the temporary bar host; the fixture never sends desktop notifications.

This lane verifies QML loading, native rendering, binding and action wiring,
and concealment after reopening. It does not verify live upstream responses,
downloads, service restarts, billing totals, provider delivery, clipboard
contents or pointer hit testing. Prefer AT-SPI inspection when available; on
Quickshell 0.3.1 here the Qt application exposes no top-level AT-SPI windows.
The scoped native control bridge keeps the lane executable despite that gap.

Recorded validation on the development desktop used Quickshell 0.3.1 and the
installed Omarchy components. The updater, controls and remote smoke lanes
passed; their cards were visually inspected. The final controls lane also
covered named client keys, public provider weights, diagnostic population
counts, activity metadata, cold Settings startup and alert-delivery errors. The
logs contained a host portal registration
warning and no QML errors. The fixture never executed the real backend bridge.
