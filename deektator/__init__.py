"""Offline desktop dictation."""

try:
    from ._release_version import VERSION as __version__
except ModuleNotFoundError:
    __version__ = "0.0.0+source"
