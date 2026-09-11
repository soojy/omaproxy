# Configuration and removal

# Files and service

| Path | Purpose |
| --- | --- |
| `~/.config/omarchy/plugins/soojy.omaproxy/` | Installed shell plugin |
| `~/.config/omaproxy/config.yaml` | Backend configuration |
| `~/.config/omaproxy/settings.json` | Bridge settings and local keys, mode 0600 |
| `~/.config/omaproxy/connection.json` | Selected connection mode and remote URL/keys, mode 0600 |
| `~/.config/omaproxy/remote-state/` | Separate quota cache and authentication error state for each remote connection |
| `~/.config/omaproxy/auth/` | Provider credentials, private directory |
| `~/.config/omaproxy/quotas.json` | Private cached quota readings |
| `~/.config/omaproxy/oauth-session.json` | Private pending browser sign-in session |
| `~/.local/share/omaproxy/cli-proxy-api` | Verified backend executable |
| `~/.config/systemd/user/omaproxy.service` | User service |

XDG config/data overrides are supported. The service binds to loopback, requires
a generated client key, and keeps remote management disabled. Secrets never
appear in normal status JSON or QML properties. Copy buttons intentionally put
the selected key on your clipboard; your clipboard manager may retain it.

Changing host, port, or authentication keys directly in `config.yaml` requires
matching changes in the private `settings.json` used by the bridge. Other
backend settings can be managed through its control panel.

```bash
omarchy-shell soojy.omaproxy toggle
omarchy-shell soojy.omaproxy showPage limits
python3 scripts/omaproxy.py status
systemctl --user status omaproxy.service
journalctl --user -u omaproxy.service
```

## Remote connections

In **Settings → Connection → Remote**, enter a server base URL such as
`https://proxy.example.com` or `https://proxy.example.com/prefix`. Do not include
`/v1`, `/v0/management`, or `/management.html`: OmaProxy appends those paths.
URLs containing credentials, query parameters, or fragments are rejected.

Supply the server's **management key**. The optional **client API key** enables
model discovery and copying the client key for coding tools. Choose **Test and
save connection** to validate access before changing the active connection.
Blank key fields reuse saved values only when the server URL is unchanged.
Keys never appear in saved shell settings or status output; input is sent to
Python over stdin and stored privately in `connection.json`.

Direct remote management requires the server's `remote-management.allow-remote`
setting and management secret to be configured for remote access. HTTPS uses
normal certificate verification. Alternatively, use an existing SSH tunnel,
for example forwarding a free laptop port to the server's loopback port:

```bash
ssh -N -L 127.0.0.1:18317:127.0.0.1:8317 user@server
```

Then connect OmaProxy to `http://127.0.0.1:18317`. OmaProxy does not manage the
tunnel. HTTP is accepted only for loopback addresses. Requests do not follow
redirects or use environment HTTP proxies.

Accounts, quotas, models, account enablement, API-key providers, and routing use
the selected server. Changes affect its other clients too. **Manage accounts**
opens the server's panel for new-account sign-in; sign in with your server's
management key. Native remote OAuth is not yet supported.

Local start/stop/restart, autostart, configuration-file editing, and journal logs
are unavailable in remote mode. Selecting Remote does not install a binary or
change a local service. Selecting Local restores the saved local configuration;
existing installations without `connection.json` continue using Local.

Remote caches are separated by URL and credentials. Changing connections cannot
write an old refresh into the new connection's cache. If the management key is
rejected, automatic management requests stop until the connection is tested and
saved again. Rejected client keys stop model polling without hiding accounts or
quotas. No keys or remote details belong in GitHub reports.

## Removal

To remove the integration while retaining credentials:

```bash
systemctl --user disable --now omaproxy.service
omarchy plugin remove soojy.omaproxy
rm ~/.config/systemd/user/omaproxy.service
systemctl --user daemon-reload
```
