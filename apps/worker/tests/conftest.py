import pytest

from dhandrishti.config import default_config


@pytest.fixture(scope="session")
def cfg():
    return default_config()
