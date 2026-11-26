"""The installed agent-framework version for ``framework_version``; ``None`` when it cannot be imported."""
from __future__ import annotations

try:
    import agent_framework  # noqa: F401

    _AF_VERSION = getattr(agent_framework, "__version__", None)
except Exception:  # pragma: no cover
    _AF_VERSION = None
