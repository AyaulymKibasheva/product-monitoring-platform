"""REST API source adapters."""

from .bestbuy import BestBuySource
from .dummyjson import DummyJsonSource

__all__ = ["BestBuySource", "DummyJsonSource"]

from .dummyjson import DummyJsonSource

__all__ = ["DummyJsonSource"]
