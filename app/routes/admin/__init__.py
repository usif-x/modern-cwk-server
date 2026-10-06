"""Admin blueprint assembled from focused route modules."""

from . import auth, catalog, market, players, security, tools
from ._common import admin_bp

__all__ = ["admin_bp"]
