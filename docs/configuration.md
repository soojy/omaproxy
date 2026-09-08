# Configuration and removal

# Files and service

| Path | Purpose |
| --- | --- |
| `~/.config/omarchy/plugins/soojy.omaproxy/` | Installed shell plugin |
| `~/.config/omaproxy/config.yaml` | Backend configuration |
| `~/.config/omaproxy/settings.json` | Bridge settings and local keys, mode 0600 |
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

To remove the integration while retaining credentials:

```bash
systemctl --user disable --now omaproxy.service
omarchy plugin remove soojy.omaproxy
rm ~/.config/systemd/user/omaproxy.service
systemctl --user daemon-reload
```
