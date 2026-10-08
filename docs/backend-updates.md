# Backend updates

Automatic installation and upgrades are currently withheld. The pinned v8.0.13 and the latest checked v8.0.16 official binaries still have vulnerability advisory matches. Checks remain available, and recovery/guarded rollback can restore a previously installed state. See the [security assessment and approval criteria](backend-security.md). Compatibility tests and checksums do not grant production rollout approval.

GitHub's latest-release metadata is informational: downloading new metadata or adjacent checksums never changes the version or SHA-256 pins. The manifest is `VERSION` and `ARCHIVE_SHA256` in `scripts/omaproxy.py`; security approval additionally requires the exact version, architecture and digest in `backend_security.APPROVED_RELEASES`. That allowlist is empty. A future release requires a plugin change and review.

| Linux asset | Compressed bytes | Reviewed SHA-256 |
| --- | ---: | --- |
| `CLIProxyAPI_8.0.13_linux_amd64.tar.gz` | 22,952,865 | `50ecffb47fdd81c8c5a9825a73a7a905ab66342337e274f39c4276b92d3533f3` |
| `CLIProxyAPI_8.0.13_linux_aarch64.tar.gz` | 20,682,811 | `f7ff98a128075ea8437dadd58a88f429a401e452a42ef7119304139185f5344f` |

Pins and asset sizes were checked against the [v8.0.13 release](https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.13) on October 3, 2026. The amd64 executable is 69,217,256 bytes, which exceeds the previous 64 MiB executable limit. Limits are now 32 MiB compressed, 80 MiB executable, 128 KiB per metadata member, and 82 MiB total inflation. Only the five reviewed flat regular-file members are accepted; links, extensions, traversal paths, duplicates and trailing data remain forbidden. Downloads are bounded even with absent or dishonest Content-Length headers.

## Commands and result contract

```sh
python3 scripts/omaproxy.py check-updates
python3 scripts/omaproxy.py backend-update
python3 scripts/omaproxy.py backend-rollback
```

These commands return `{ "updates": { ... }, "message": "..." }`. `message` is optional. The `updates` fields are:

| Field | Meaning |
| --- | --- |
| `installed_version` | Actual running management header when available, otherwise the managed executable's help output |
| `version_source` | `running` or `executable` |
| `latest_version` | Latest stable GitHub release from a bounded metadata request; empty in update/rollback receipts |
| `reviewed_version` | Artifact pin under review; this field alone does not grant rollout approval |
| `release_approved` | Exact version, host architecture and archive digest appear in the local security approval allowlist |
| `security_error` | Reason automatic installation is withheld; empty only for an approved artifact |
| `update_available` | Approved release is newer than the observed installed version |
| `update_supported` | Security-approved managed installation and bubblewrap available; validation can still refuse incompatible configuration |
| `rollback_available` | Private backup receipt exists; the rollback operation checks its integrity |
| `providers` | Allowlisted provider names, IDs, login flags and availability from executable help |
| `restarted` | In update/rollback receipts, whether a previously running service was restarted |
| `error` | Safe display message for a security hold, failed metadata check or unsupported installation |

Fatal action errors use the bridge's existing `{ "error": "..." }` result and a nonzero exit code. Credentials, backend output and configuration contents are never returned. Checking updates does not restart, replace, or rewrite the backend. Help probes run only on explicit updater actions, in an empty working directory and clean environment. Status captures `X-CPA-VERSION` from its existing account request, avoiding a second management poll, and prefers it over the settings installation record.

## Validation, replacement and recovery

Updates require Linux and bubblewrap (`bwrap`). The actual staged executable parses a private copy of the unchanged configuration, including legacy YAML and comments. A fresh bubblewrap namespace contains the runtime, staged executable and copied configuration. Real HOME, auth files, service sockets, proxy environment and external networking are absent. The helper checks authenticated loopback `/v0/management/auth-files` and `/v1/models` without making inference requests. `-local-model` is used when supported. Background upstream refresh attempts have no external network access. If namespaces are blocked, or the configuration depends on files absent from the sandbox, the update refuses before changing the service. This check proves parsing and local API compatibility; it does not prove provider delivery or authenticated account health.

The updater takes a nonblocking lock, downloads and verifies the pinned archive, stages and probes the executable, then validates configuration. It publishes a private snapshot of binary, settings and exact config bytes before changing anything. It stops and restarts only a previously running service, replaces the executable atomically, refreshes provider capabilities, and verifies the running version plus local API health. A stopped service stays stopped. Start or health failures restore the previous binary, settings and config, then restart the previous service when it was running. A failed recovery reports that the files were restored but the service needs attention.

Successful operations keep one private `backend-backup` under the OmaProxy data directory. Rollback restores that binary and its configuration/settings; it does not rewrite auth files. It refuses if configuration has changed since the last successful operation, so it cannot restore revoked client keys or overwrite newer provider credentials. It validates the saved config and executable before stopping the service, checks the saved binary digest, and preserves the replaced state as the next backup. Updates and rollback share the management mutation lock with native controls. After a killed updater, `backend-pending` remains recoverable. The next explicit update or rollback first restores that snapshot and its previous running state. An invalid pending snapshot is refused for manual recovery.

Custom executables and symlinked managed binaries are refused. Newer installed releases are not automatically downgraded. An active process must report the same version as the executable on disk; stop the proxy before updating when versions disagree or the running version cannot be verified. This prevents claiming that a backup can restore an executable already replaced manually. An update already at the reviewed version reconciles stale settings/provider metadata without a restart. Repeating `setup` on an existing managed configuration is refused in favor of `backend-update`, so setup cannot bypass the transaction.

## Verification

```sh
python3 -m unittest discover -s tests -v
OMAPROXY_TEST_BACKEND=/path/to/reviewed/cli-proxy-api \
  python3 -m unittest discover -s tests -p test_backend_updates.py -v
```

The optional lane uses fake credentials and unchanged legacy YAML inside an isolated namespace. Normal unit tests use fake artifacts and mocked service control. No tests operate the user's service or credentials. Real release validation on this workstation covered amd64; arm64 metadata and SHA-256 pins were checked, but its executable was not run here.
