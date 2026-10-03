"""Entry point."""
from .core.models import Cart, Product
from .utils.helpers import log_calls


@log_calls
def run():
    cart = Cart()
    cart.add(Product("Book", 12.5))
    print(cart.total)
