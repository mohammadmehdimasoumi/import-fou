"""Payment helpers."""
import asyncio

from .models import Cart


async def charge(cart: Cart) -> bool:
    await asyncio.sleep(0.1)
    return cart.total > 0


def refund(amount: float) -> str:
    return f"Refunded {amount}"
