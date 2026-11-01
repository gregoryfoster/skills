"""Session-wide test setup shared by every directory under tests/."""

from tests.utils import unsigned_git

_ISOLATION = None


def pytest_configure(config):
    """Fixture commits must not sign with the caller's config (#546)."""
    global _ISOLATION
    _ISOLATION = unsigned_git.isolate()


def pytest_unconfigure(config):
    unsigned_git.restore(_ISOLATION)
