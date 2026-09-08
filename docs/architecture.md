# Research and architecture

Investigated on 2026-09-08 against the installed Omarchy shell and upstream code.

## What an Omarchy plugin is

The installed `/usr/share/omarchy/shell/README.md` and `plugins/README.md`
describe a Git repository with a root `manifest.json`, schema version 1,
namespaced ID, declared kinds, and QML entry points. User plugins are discovered
under `~/.config/omarchy/plugins/`. Presence in the bar layout enables a
third-party bar widget. QML runs in the shared shell process and imports the
host's `qs.Ui` and `qs.Commons` modules. Plugin code is unsandboxed.

OmaProxy declares one `bar-widget`. Like the stock power and network widgets,
it extends `Panel` and uses `BarIconButton` plus `KeyboardPanel`. A separate
Python bridge handles operations through short-lived `Quickshell.Io.Process`
instances. The long-running proxy belongs to systemd, not the shell process.

This is an **Omarchy shell plugin**, not a Codex plugin; `.codex-plugin` manifests
and the Codex plugin-creator workflow do not apply.

## VibeProxy

Source: https://github.com/automazeio/vibeproxy

Inspected commit: `866ff0ffe9ab6e59419a6cbbb3fe72f45caa8342`.

- `ServerManager.swift` starts CLIProxyAPIPlus and invokes login flags.
- `AuthStatus.swift` tracks authentication files and account state.
- `SettingsView.swift` provides the native macOS UI.
- `ConfigComposer.swift` composes provider and routing configuration.
- `ThinkingProxy.swift` is an additional HTTP relay on 8317, forwarding to
  CLIProxyAPI on 8318, with model-name suffix transforms and Gateway routing.
- `TunnelManager.swift` and Sparkle cover extra macOS application features.

The reference's linked `router-for-me/CLIProxyAPIPlus` repository returned 404
both in GitHub browsing and `git clone`. No replacement community fork is
silently trusted or installed. OmaProxy accepts a user-selected Plus executable.

## CLIProxyAPI

Source: https://github.com/router-for-me/CLIProxyAPI

Inspected main commit: `d198db54d4c4886c99b21488d54fc576933019a3`.
Installer release: `v7.2.154` (separately tested as a downloaded executable).

CLIProxyAPI is the actual Go server: provider authentication, refresh,
translation between supported API formats, model discovery, routing, retries,
and account selection belong here. Reimplementing those inside a desktop
shell plugin would duplicate the engine and couple shell stability to requests.

The bridge uses these interfaces:

| Interface | Use |
| --- | --- |
| `--help` | Discover available native provider login flags |
| `GET /<provider>-auth-url` | Start browser OAuth without a terminal |
| `GET /get-auth-status` | Observe authentication completion |
| `POST /oauth-callback` | Submit a manually pasted callback |
| `DELETE /oauth-session` | Cancel pending sign-in |
| `GET /v0/management/auth-files` | Sanitized account status |
| `PATCH /v0/management/auth-files/status` | Pause/resume a specific account |
| `GET /v1/models` | Models available to the client key |
| `POST /api-call` | Provider quota lookups with backend token substitution |
| `PUT /routing/strategy` | Native account routing settings |
| `PUT /openai-compatibility` | Native API-provider setup |

Authentication is initiated through the backend management API. Browser opening
is the only external UI step. Device codes, polling, cancel, and callback URL
entry stay inside the shell popup. Callback URLs and API-key form data cross
the process boundary over stdin, not command-line arguments. The pending
session is private and survives a shell reload.

Quota endpoints and payloads were checked against the upstream management
center source at https://github.com/router-for-me/Cli-Proxy-API-Management-Center,
particularly `src/features/quota/providers/` and `src/utils/quota/`. These are
provider-specific endpoints and may evolve. Unknown or failed readings are
explicit; a failed refresh never implies an exhausted allowance.

The native UI has exactly three tabs: Limits, Accounts, Settings. Settings
contains models. Quota fetches are separate from fast local health polling,
cache successful readings, retain stale readings on error, and use a lock to
avoid duplicate refreshes from multiple monitor instances.

## Scope and differences

The plugin workflow is native: account limits, proxy lifecycle, browser login
progress, account status and enablement, API-key provider entry, routing,
autostart, logs, models, and connection details. The backend's management panel
remains available outside the plugin for advanced configuration.

VibeProxy's Swift ThinkingProxy, Vercel Gateway integration, public tunnels,
and Sparkle updates are not ported. Models are shown as reported by the backend,
without synthetic aliases that imply unavailable reasoning support. Backend
installation is explicit, version-pinned, and checksum-verified. Plugin updates
use Omarchy's standard Git update path once published.
