"""Client side of licensing: the key is pasted at EVERY start (masterquo_start), exchanged for a short signed lease of
THIS run, renewed every few seconds; protected modules run only while the lease is valid (deny by default)."""
from .guard import LicenseDenied, LicenseGuard  # noqa: F401
