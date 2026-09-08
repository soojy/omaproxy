# Security

Please report vulnerabilities through GitHub's **Report a vulnerability** form
or privately to the maintainer. Do not include credentials in a public issue.

OmaProxy runs as an unsandboxed Omarchy plugin. It starts a user-level proxy
service only after setup, stores its configuration and credentials separately
under `~/.config/omaproxy`, and uses loopback-only management with generated keys.
The installer verifies the backend archive against architecture-specific SHA-256
digests embedded in the plugin snapshot. Adjacent release checksums are only a
consistency check. Downloads, decompression, and executable extraction are bounded;
only the reviewed flat regular-file archive layout is accepted. See the
[installer trust policy](docs/installer-security.md). The proxy engine and upstream provider endpoints are separate trust
boundaries.

Email labels are blurred by default and reveal on click; closing the popup hides them again. The concealed view blurs a fixed placeholder rather than the real address. Inline logs redact email addresses. It does not encrypt
credentials, alter the backend, or redact files exported outside the plugin.
Copy API key intentionally places a secret on the clipboard, where a clipboard
manager may retain it.
