# Security

Please report vulnerabilities through GitHub's **Report a vulnerability** form
or privately to the maintainer. Do not include credentials in a public issue.

OmaProxy runs as an unsandboxed Omarchy plugin. It starts a user-level proxy
service only after setup, stores its configuration and credentials separately
under `~/.config/omaproxy`, and uses loopback-only management with generated keys.
The installer verifies the pinned backend release against its published SHA-256
checksums. The proxy engine and upstream provider endpoints are separate trust
boundaries.

Email labels are blurred by default and reveal on click; closing the popup hides them again. The concealed view blurs a fixed placeholder rather than the real address. Inline logs redact email addresses. It does not encrypt
credentials, alter the backend, or redact files exported outside the plugin.
Copy API key intentionally places a secret on the clipboard, where a clipboard
manager may retain it.
