"""Small helper functions."""
import functools


def slugify(text):
    return text.lower().replace(" ", "-")


def log_calls(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
