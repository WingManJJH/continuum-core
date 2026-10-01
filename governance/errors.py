"""Shared error type for every governance write path (re-exported as store.EditError)."""


class EditError(ValueError):
    """A rejected edit — the reason is safe to show the owner in the UI."""
