# CLIProxyAPI backend security assessment (2026-10-06)

The production v8.0.13 pin remains blocked. The latest official release checked was [v8.0.16](https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.16), published 2026-10-05T21:46:28Z; both Linux architectures still use Go 1.26.4 and match the same 17 advisories. No patched default Linux artifact is available in the latest official release. This is not an exhaustive statement about custom builds or other asset variants.

Security inspection checked downloaded archive hashes against official metadata/checksums and scanned the extracted binaries without executing them. The installed v7.2.154 amd64 artifact also has the same 17 matches; withholding a new rollout does not remediate that existing installation.

## Reproduction and evidence

Scanner is pinned to `golang.org/x/vuln/cmd/govulncheck@v1.8.0`, built with local Go 1.27.0; binary analysis uses each binary's recorded build version. Database URL is https://vuln.go.dev, updated 2026-10-01T20:24:15Z. Retain the complete streaming JSON, scanner diagnostics, exit status and `go version -m` output when reviewing a replacement artifact. The scans below distinguish advisory IDs from individual finding records.

```sh
GOBIN=/tmp/omaproxy-security-20261005/tools go install golang.org/x/vuln/cmd/govulncheck@v1.8.0
go version -m /path/to/verified/cli-proxy-api
/tmp/omaproxy-security-20261005/tools/govulncheck -mode=binary -json /path/to/verified/cli-proxy-api
/tmp/omaproxy-security-20261005/tools/govulncheck -mode=binary /path/to/verified/cli-proxy-api
```

Each of the seven reviewed binaries emitted 17 distinct advisory IDs at symbol level (173 symbol records), plus 24 package and 17 module records: 214 finding records total, not 214 vulnerabilities. JSON mode exits zero even with findings. Latest amd64 text mode exits 3 and reports 17 vulnerabilities. A CI gate must parse finding records or use text-mode exit status, and must distinguish scanner failure from a completed negative scan. [Official govulncheck documentation](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck#hdr-Exit_codes).

Binary matches prove linked vulnerable symbols, not exploitability or per-configuration reachability; binary output cannot show call stacks. [Official limitations](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck#hdr-Limitations).

## Reviewed artifact identity

All binary toolchains are Go 1.26.4. Archive digests below were independently recomputed; v8 values match GitHub API digest and checksum manifest. v7 digest matches the existing plugin pin and checksum manifest.

| Asset | Archive SHA-256 | Executable SHA-256 | Advisories |
| --- | --- | --- | --- |
| `CLIProxyAPI_7.2.154_linux_amd64` | `2a2256ceff048d5fa813aa54e8daa43e870b40e698d5cd21efad46e25aa5a1f9` | `2ac891225e031d733d82457611d2be663fb9d71f8e84ceb919f35003d67e394f` | 17 |
| `CLIProxyAPI_8.0.13_linux_aarch64` | `f7ff98a128075ea8437dadd58a88f429a401e452a42ef7119304139185f5344f` | `9dfe80b79f8466b4e56d51d71869ce759021942a9279e43dbea92eda21b994d7` | 17 |
| `CLIProxyAPI_8.0.13_linux_amd64` | `50ecffb47fdd81c8c5a9825a73a7a905ab66342337e274f39c4276b92d3533f3` | `b682e9e42586263f476888361514f68f89ff4ebf89a5dadba394b850b797ce41` | 17 |
| `CLIProxyAPI_8.0.15_linux_aarch64` | `172f1f71dc0381538c09f44a65c687b55035c61ff63f505a6b7edd4fc7b69c95` | `d7bf5df02b094f90435291d44526cd658beae4bec88eef01368c5dccc8132d8f` | 17 |
| `CLIProxyAPI_8.0.15_linux_amd64` | `3acca2d978ba140b4b664bcfb74acea8f6c9a32c24fa6e2d58130f6c1128d3a8` | `426d9353288f810eb31b362e1e2ac9605b6c948e10147946f6f26cab187aa81d` | 17 |
| `CLIProxyAPI_8.0.16_linux_aarch64` | `e84f37c92bf48a057e5c2ff3e2a30851a4e43c64efcf442473ea04a43b9ddebb` | `3e01096477acd04493126ca4c513cf065f36f54d6afc5e9a8ebb9dfc1489dbfd` | 17 |
| `CLIProxyAPI_8.0.16_linux_amd64` | `affb5a189184e41b4335549e498df6f4f1c7f15dd0d04a28286becc2dfa78579` | `d67242f2cde3b944c7702b1a99a9ef5a0c0678aa6b1210923988429426768b4c` | 17 |

Release metadata: [v8.0.13](https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/tags/v8.0.13), [v8.0.15](https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/tags/v8.0.15), [v7.2.154](https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/tags/v7.2.154), [v8.0.16](https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/tags/v8.0.16). The v8.0.13 release workflow itself pins [GO_VERSION 1.26.4](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/.github/workflows/release.yaml#L14); this workflow, go.mod, API server, and Git token store are unchanged between v8.0.13 and v8.0.15.

The v8.0.16 default archives independently match both GitHub asset digests and the [official checksum manifest](https://github.com/router-for-me/CLIProxyAPI/releases/download/v8.0.16/checksums.txt). Both binaries record Go1.26.4 and CGO_ENABLED=1. All 100 embedded dependency version/checksum pairs match both architectures of v8.0.13 and v8.0.15. Complete v8.0.16 JSON streams were parsed to their end (496 protocol records each); no scanner timed out or emitted diagnostics. The no-plugin variants were not evaluated. These binary results do not extend the historical source reachability assessment below to v8.0.16.

## Advisory matrix and reachability

The following versions are recorded by all reviewed v8 binaries. The source reachability assessment is based on v8.0.13; v8.0.16 received binary analysis only. Fixed versions are minimum advisory fixes, not a substitute for scanning the replacement artifact. Default here means the fresh OmaProxy-generated loopback HTTP configuration with a file auth store. It does not mean all existing installations, arbitrary backend configs, environment variables, or plugins have that configuration.

| Advisory | Component found | Minimum fix | Assessment |
| --- | --- | --- | --- |
| [GO-2026-4970](https://pkg.go.dev/vuln/GO-2026-4970) | stdlib os Go1.26.4 | Go1.26.5 | Source scan traces go-billy BoundOS.Chroot to os.Root.OpenRoot via GitTokenStore. Requires enabled Git store and malicious symlink/trailing-slash inputs; default file store bypasses this path. |
| [GO-2026-5026](https://pkg.go.dev/vuln/GO-2026-5026) | stdlib bundled IDNA Go1.26.4 | Go1.26.6 | HTTP client code is used; exploit requires security decisions across ASCII/Unicode hostname conversion. No confirmed application exploit. |
| [GO-2026-5841](https://pkg.go.dev/vuln/GO-2026-5841) | klauspost/compress v1.17.4 | v1.18.7 | Requires attacker-controlled dictionary passed to s2.NewDict; no direct app call found. Transitive/plugin reachability unproven. |
| [GO-2026-5856](https://pkg.go.dev/vuln/GO-2026-5856) | stdlib crypto/tls Go1.26.4 | Go1.26.5 | Requires ECH-enabled handshake; no direct ECH configuration found. TLS outbound client use alone does not prove ECH use. |
| [GO-2026-5932](https://pkg.go.dev/vuln/GO-2026-5932) | x/crypto v0.54.0 openpgp | No fixed version | Unsafe/unmaintained OpenPGP package requires migration/removal or documented absent use. No direct app import/call found. |
| [GO-2026-5942](https://pkg.go.dev/vuln/GO-2026-5942) | stdlib bundled DNS Go1.26.4 | Go1.26.6 | Requires malformed SVCB/HTTPS DNS record parsing. Outbound DNS is used; exact feature/path reachability unproven. |
| [GO-2026-5972](https://pkg.go.dev/vuln/GO-2026-5972) | stdlib encoding/asn1 Go1.26.4 | Go1.26.6 | Source scan traces ASN.1 through x509.CreateCertificateRequest and optional Home client CSR setup (internal/home/certificate.go:294). Malicious recursion input precondition/exploit untested. |
| [GO-2026-6088](https://pkg.go.dev/vuln/GO-2026-6088) | stdlib encoding/xml Go1.26.4 | Go1.26.6 | Source scan traces XML via mimetype/charset, validator and Gin binding. Actual malicious input path/recursive DecodeElement precondition unproven; no direct XML app call found. |
| [GO-2026-6089](https://pkg.go.dev/vuln/GO-2026-6089) | stdlib net/http Go1.26.4 | Go1.26.6 | Requires unencrypted HTTP/2 enabled; main server Protocols unset, no h2c enable found, plugin bridge explicitly disables unencrypted HTTP/2. Default precondition not established. |
| [GO-2026-6090](https://pkg.go.dev/vuln/GO-2026-6090) | stdlib crypto/tls Go1.26.4 | Go1.26.6 | Malicious TLS client can force endless key-derivation work on server. Default loopback HTTP lacks TLS listener; configurable server.tls.enable activates path. Remote TLS server is exposed before application auth. |
| [GO-2026-6091](https://pkg.go.dev/vuln/GO-2026-6091) | stdlib html/template Go1.26.4 | Go1.26.6 | Requires attacker data in affected JavaScript regexp template context; direct vulnerable template path not established. |
| [GO-2026-6213](https://pkg.go.dev/vuln/GO-2026-6213) | go-git/v6 alpha.4 pseudo-version | v6.0.0-alpha.5 | GITSTORE_GIT_URL enables real clone/worktree operations; malicious repository symlink content is relevant. Default file auth store bypasses Git store. |
| [GO-2026-6214](https://pkg.go.dev/vuln/GO-2026-6214) | go-git/v6 alpha.4 pseudo-version | v6.0.0-alpha.5 | GITSTORE_GIT_URL enables Git operations involving remote references; crafted refs are relevant. Default file auth store bypasses Git store. |
| [GO-2026-6218](https://pkg.go.dev/vuln/GO-2026-6218) | stdlib net/url Go1.26.4 | Go1.26.6 | Requires long relative paths with repeated parent segments; outbound HTTP redirects/URL resolution are relevant. Exact hostile input route untested. |
| [GO-2026-6303](https://pkg.go.dev/vuln/GO-2026-6303) | x/crypto v0.54.0 ssh | v0.55.0 | Requires SSH server using non-public-key auth callbacks with source-address restrictions. No direct app SSH server/call found; dependency/plugin reachability unproven. |
| [GO-2026-6354](https://pkg.go.dev/vuln/GO-2026-6354) | x/crypto v0.54.0 ssh | v0.56.0 | Source scan confirms NewClientConn via go-git SSH transport and GitTokenStore.Pull. Requires SSH Git store/hostile peer; default file auth store bypasses Git path. |
| [GO-2026-6355](https://pkg.go.dev/vuln/GO-2026-6355) | x/crypto v0.54.0 ssh | v0.56.0 | Source scan confirms NewClientConn via go-git SSH transport and GitTokenStore.Pull. Requires SSH Git store/hostile peer; default file auth store bypasses Git path. |

Exact go-git dependency is `v6.0.0-alpha.4.0.20260520124234-0860a7d8a164`. `golang.org/x/net` is already v0.57.0, but the standard library's bundled HTTP/DNS code still needs the newer Go toolchain.

Source evidence (v8.0.13 checkout, commit d7914afdedca7af95ee974a42453dc49fc1388ce):

- OmaProxy [fresh setup](../scripts/omaproxy.py), in `setup()`, generates host `127.0.0.1`, allow-remote false, no TLS enable and a local auth directory. This is not evidence that an existing user's configuration is still default.
- [API server constructor](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/internal/api/server.go#L257) sets only Addr and Handler on http.Server. [Start](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/internal/api/server.go#L299) only creates tls.Config/tls.NewListener when cfg.TLS.Enable; mux [TLS handshake](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/internal/api/protocol_multiplexer.go#L69) runs before HTTP authentication. The mux routes Redis/HTTP, not an app SSH listener.
- [Plugin HTTP bridge](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/internal/pluginhost/http_bridge.go#L303) explicitly sets SetUnencryptedHTTP2(false).
- [GITSTORE_GIT_URL gate](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/cmd/server/main.go#L297), [Git-store initialization](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/cmd/server/main.go#L540), [file-store fallback](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/cmd/server/main.go#L676), and [PlainClone](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/internal/store/gitstore.go#L149) show the optional path. Configuration allow-remote false is management authorization, not a patch for cryptographic or parser vulnerabilities.
- Focused non-test source searches did not find direct NewServerConn, ssh.Dial, s2.NewDict, OpenPGP, os.OpenRoot/OpenInRoot, ECH, or h2c enable calls. This only limits direct app-source claims. Third-party dependencies, dynamically loaded plugins, and arbitrary backend configuration remain outside this negative search's proof.


Supplemental source analysis of v8.0.13 completed with `GOTOOLCHAIN=go1.26.4 govulncheck -C /path/to/v8.0.13-checkout -json ./cmd/server`, without tests, using Linux amd64 and the local default CGO configuration. This does not prove full release-build equivalence. The scanner records Go1.26.4 and emits 75 findings: 17 module, 16 package and 42 symbol records, covering 12 distinct advisory IDs at symbol level. Call traces identify optional Git/SSH/os.Root paths and the TLS server handshake. Static analysis does not evaluate configured exploit preconditions.

The five binary-only symbol IDs absent from that source scan are GO-2026-5841 (s2.NewDict), GO-2026-5932 (OpenPGP), GO-2026-5942 (SVCB/HTTPS DNS), GO-2026-6091 (HTML regexp template), and GO-2026-6303 (SSH server auth restriction). This distinguishes linked symbols from static call reachability for the scanned build. It does not establish safety for other build variants or dynamically loaded plugins, or justify lifting the hold.

## Safe release path

The [release approval policy](../scripts/backend_security.py) currently has an empty allowlist. Fresh setup, the direct installer and backend upgrades refuse an unapproved exact version/architecture/archive digest before candidate download, extraction, execution, snapshots or service replacement. Read-only release checks report `release_approved: false` and a security reason, and keep the install action unavailable. Local locks are still created for updater/recovery coordination. Preserve read-only release metadata and recovery of prior interrupted transactions; rollback may restore a vulnerable prior binary and is recovery, not vulnerability remediation. Explicit user-selected custom executables require separate trust and must not become an implicit fallback/download trust anchor.

Unblock only after official upstream release builds use a patched Go toolchain (at least Go1.26.6 for these advisories), upgrade go-git/v6 to alpha.5 or newer, compress to v1.18.7 or newer, x/crypto to v0.56.0 or newer, and address OpenPGP's no-fix advisory through maintained replacement/removal or a reviewed bounded reachability exception. Re-download/check both supported architectures, scan exact binaries with saved complete output, document reachability and residual findings, and run the existing isolated configuration/API compatibility lanes. Do not invent an unofficial replacement hash or claim this gating work resolves upstream vulnerabilities. PR security acceptance remains pending patched artifact review.
