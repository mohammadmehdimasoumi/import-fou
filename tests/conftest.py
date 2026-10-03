import pytest

MAIN = '''\
"""Entry point of the sample app."""
import os
import requests
from pathlib import Path
from database import Database

# a comment line

VERSION = "1.0"
counter = 0


def main(argv=None):
    """Run the app."""
    token = os.environ.get("TOKEN")  # trailing comment
    return token


async def fetch_data(url, *, timeout: float = 5.0) -> bytes:
    data = await get(url)
    return data
'''

USER = '''\
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .product import Product
import models.product

if TYPE_CHECKING:
    from database import Session

try:
    import ujson as json
except ImportError:
    import json

MAX_AGE: Final = 120


@dataclass
class User(Base, metaclass=Meta):
    """A user."""

    name = "Ali"
    LIMIT = 10

    def __init__(self, name):
        self.name = name
        self.age: int = 0
        self.age = 1

    def login(self):
        token = "x"
        return token

    async def refresh(self):
        pass

    @staticmethod
    def make():
        return User("x")

    @classmethod
    def build(cls):
        cls.registry = {}
        return cls("y")

    @property
    def title(self):
        return self.name

    @title.setter
    def title(self, value):
        self.name = value


def helper(a, b=2, /, c=3, *args, d, e=5, **kwargs):
    def inner():
        pass

    total = a + b
    for i in range(3):
        total += i
    return inner
'''

PRODUCT = '''\
class Product:
    def price(self):
        return 1


@app.route("/")
@cache(timeout=60)
def home():
    pass
'''

HELPER = '''\
import sys


def run():
    global STATE
    STATE = 1
    if (n := 10) > 5:
        return n
'''


@pytest.fixture
def sample_project(tmp_path):
    root = tmp_path / "MyProject"
    files = {
        "main.py": MAIN,
        "config.py": "DEBUG = True\n",
        "models/__init__.py": "",
        "models/user.py": USER,
        "models/product.py": PRODUCT,
        "utils/helper.py": HELPER,
        "notes.txt": "hello\n\nworld\n",
        "data/settings.json": '{"a": 1}\n',
        ".hidden/secret.py": "SECRET = 1\n",
        "venv/lib.py": "X = 1\n",
        "__pycache__/main.cpython-312.pyc": "junk",
        "node_modules/pkg/index.py": "Y = 1\n",
    }
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root
