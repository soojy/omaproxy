# Backend installer trust policy

Automatic setup supports the following **CLIProxyAPI v7.2.154** Linux release archives. Their SHA-256 digests are embedded in `ARCHIVE_SHA256` in [the installer](../scripts/omaproxy.py), so the exact reviewed plugin commit is the trust anchor.

| Architecture | Archive | Pinned SHA-256 |
| --- | --- | --- |
| x86_64 | `CLIProxyAPI_7.2.154_linux_amd64.tar.gz` | `2a2256ceff048d5fa813aa54e8daa43e870b40e698d5cd21efad46e25aa5a1f9` |
| aarch64 | `CLIProxyAPI_7.2.154_linux_aarch64.tar.gz` | `3a0cd18d64e3b9990ca72136dbb1da97eedddade00ee6768e8b49fab1de6925e` |

These digests were checked on 2026-09-08 by downloading both [release archives](https://github.com/router-for-me/CLIProxyAPI/releases/tag/v7.2.154), computing their SHA-256 locally, and comparing them with GitHub's release-asset digests and the release checksum manifest. This establishes the reviewed snapshot; it does not prove the upstream executable is harmless. Later replacement of both an archive and its adjacent checksum cannot change the embedded expected digest.

The checksum manifest remains a consistency check only: its entry must match the embedded digest, and the downloaded archive must independently hash to that digest **before decompression or tar parsing**. Missing or duplicate checksum entries fail closed. Backend updates require reviewing the new artifacts, layout, limits, and digests in a new plugin commit; setup never discovers new trust anchors from remote metadata.

## Resource and archive limits

| Input/output | Hard ceiling |
| --- | --- |
| Checksum manifest download | 64 KiB |
| Compressed archive download | 32 MiB |
| Total expanded tar stream | 66 MiB |
| Executable, declared and actually copied | 64 MiB |
| Each allowed documentation/config example member | 128 KiB |

Both HTTP responses are read in bounded chunks. Oversized declared lengths are rejected before reading; missing or dishonest lengths cannot bypass the byte counter. Truncated declared downloads are rejected too.

After digest validation, gzip data is streamed to a bounded temporary file before parsing any tar header. The installer reads raw 512-byte headers, checks their checksums, and accepts exactly five flat regular files: `cli-proxy-api`, `LICENSE`, `README.md`, `README_CN.md`, and `config.example.yaml`. It rejects alternate paths, duplicate names, GNU/PAX extension records, sparse files, links, devices, directories, invalid padding/terminators, and nonzero trailing payloads.

Only `cli-proxy-api` is copied, with declared and actual size checks. Archive paths are never used as destination paths. Temporary files are removed on failure, and the existing installed executable is replaced atomically only after every check passes.

The reviewed archive sizes are 21,578,431 bytes (amd64) and 19,464,005 bytes (aarch64). Their executable sizes are 65,247,208 and 59,471,464 bytes respectively. Both architectures have been validated through the bounded installer without running either downloaded executable during that check.

## Explicit local backend override

`setup --binary /absolute/path/to/backend` uses a user-selected local executable. This deliberately bypasses automatic download verification and runs that executable's `--help` to discover capabilities. The user is responsible for trusting that file; it is never selected automatically.
