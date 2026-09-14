"""Errors for the namespaced versioned workspace store."""


class VersionedStoreError(RuntimeError):
    """Base error raised by versioned workspace store adapters."""


class VersionedStoreConflictError(VersionedStoreError):
    """Create failed because the namespaced key already exists."""


class VersionedStoreNotFoundError(VersionedStoreError):
    """Mutating operation targeted a missing namespaced record."""


class VersionedStoreVersionConflictError(VersionedStoreError):
    """Compare-and-swap update saw a stale expected_version."""
