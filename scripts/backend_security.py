"""Automatic rollout approvals bind a reviewed version, architecture and archive digest.

An artifact checksum establishes identity, not vulnerability remediation. Keep
this allowlist empty until a patched upstream build and its exposure assessment
have been reviewed. Release discovery never adds approvals.
"""

APPROVED_RELEASES = frozenset()
SECURITY_HOLD = (
    "Automatic backend installation is withheld pending a patched upstream build "
    "and security review. See docs/backend-security.md."
)


def release_approved(version, architecture, digest):
    """Require approval of this exact artifact, including its architecture."""
    return (version, architecture, digest) in APPROVED_RELEASES


def require_release_approval(version, architecture, digest):
    """Refuse an unapproved download before execution or filesystem mutation."""
    if not release_approved(version, architecture, digest):
        raise ValueError(SECURITY_HOLD)


def bridge_release_status(bridge):
    """Return the host artifact's review status without network or executable probes."""
    architecture = {'x86_64': 'amd64', 'aarch64': 'aarch64'}.get(bridge.platform.machine())
    approved = release_approved(bridge.VERSION, architecture, bridge.ARCHIVE_SHA256.get(architecture))
    return {'release_approved': approved, 'security_error': '' if approved else SECURITY_HOLD}
