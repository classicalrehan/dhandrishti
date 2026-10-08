"""PostgreSQL access for the worker (psycopg 3)."""

import os

import psycopg

DEFAULT_URL = "postgresql://dhandrishti:dhandrishti_dev@localhost:5432/dhandrishti"


def database_url() -> str:
    return os.environ.get("DD_DATABASE_URL", DEFAULT_URL)


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or database_url())
