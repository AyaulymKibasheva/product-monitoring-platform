"""REST API source adapters."""

from .bestbuy import BestBuySource
from .dummyjson import DummyJsonSource
from .steam import SteamStoreSource

__all__ = ["BestBuySource", "DummyJsonSource", "SteamStoreSource"]

from .dummyjson import DummyJsonSource

__all__ = ["DummyJsonSource"]
