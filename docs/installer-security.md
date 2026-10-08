# Backend installer trust policy

Automatic setup is currently withheld pending a patched upstream build and security review. The following **CLIProxyAPI v8.0.13** artifacts remain pinned for reproducible inspection, but are not approved for automatic installation. See the [backend security assessment](backend-security.md).

Their SHA-256 digests are embedded in `ARCHIVE_SHA256` in [the installer](../scripts/omaproxy.py). The exact plugin commit binds artifact identity; the separate, currently empty security approval allowlist binds version, architecture and digest before setup or upgrade can download or execute a candidate.

| Architecture | Archive | Pinned SHA-256 |
| --- | --- | --- |
| x86_64 | `CLIProxyAPI_8.0.13_linux_amd64.tar.gz` | `50ecffb47fdd81c8c5a9825a73a7a905ab66342337e274f39c4276b92d3533f3` |
| aarch64 | `CLIProxyAPI_8.0.13_linux_aarch64.tar.gz` | `f7ff98a128075ea8437dadd58a88f429a401e452a42ef7119304139185f5344f` |

These digests were checked on 2026-10-03 against the [release metadata](https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.13). The amd64 archive was also downloaded, hashed locally and passed through the production extractor. Arm64 executable behavior was not tested here. This establishes the reviewed snapshot; it does not prove the upstream executable is harmless. Later replacement of both an archive and its adjacent checksum cannot change the embedded expected digest.

The checksum manifest remains a consistency check only: its entry must match the embedded digest, and the downloaded archive must independently hash to that digest **before decompression or tar parsing**. Missing or duplicate checksum entries fail closed. Backend updates require reviewing the new artifacts, layout, limits, and digests in a new plugin commit; setup never discovers new trust anchors from remote metadata.

## Resource and archive limits

| Input/output | Hard ceiling |
| --- | --- |
| Checksum manifest download | 64 KiB |
| Compressed archive download | 32 MiB |
| Total expanded tar stream | 82 MiB |
| Executable, declared and actually copied | 80 MiB |
| Each allowed documentation/config example member | 128 KiB |

Both HTTP responses are read in bounded chunks. Oversized declared lengths are rejected before reading; missing or dishonest lengths cannot bypass the byte counter. Truncated declared downloads are rejected too.

After digest validation, gzip data is streamed to a bounded temporary file before parsing any tar header. The installer reads raw 512-byte headers, checks their checksums, and accepts exactly five flat regular files: `cli-proxy-api`, `LICENSE`, `README.md`, `README_CN.md`, and `config.example.yaml`. It rejects alternate paths, duplicate names, GNU/PAX extension records, sparse files, links, devices, directories, invalid padding/terminators, and nonzero trailing payloads.

Only `cli-proxy-api` is copied, with declared and actual size checks. Archive paths are never used as destination paths. Temporary files are removed on failure, and the existing installed executable is replaced atomically only after every check passes.

The reviewed archive sizes are 22,952,865 bytes (amd64) and 20,682,811 bytes (aarch64). The amd64 executable is 69,217,256 bytes; it exceeded the old executable and inflation limits. It passed isolated configuration validation with fake credentials. See [backend updates](backend-updates.md) for staging, recovery and rollback behavior.

## Explicit local backend override

`setup --binary /absolute/path/to/backend` uses a user-selected local executable. This deliberately bypasses automatic download verification and runs that executable's `--help` to discover capabilities. The user is responsible for trusting that file; it is never selected automatically.
