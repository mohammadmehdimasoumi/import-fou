"""Domain models."""
from dataclasses import dataclass
from typing import List

from ..config import TAX_RATE


@dataclass
class Product:
    """A product that can be sold."""

    name: str
    price: float

    def with_tax(self) -> float:
        """Return the price including tax."""
        return round(self.price * (1 + TAX_RATE), 2)


class Cart:
    """A shopping cart."""

    def __init__(self) -> None:
        self.items: List[Product] = []

    def add(self, product: Product) -> None:
        self.items.append(product)

    @property
    def total(self) -> float:
        return sum(p.with_tax() for p in self.items)

    @staticmethod
    def empty_message() -> str:
        return "Your cart is empty"
