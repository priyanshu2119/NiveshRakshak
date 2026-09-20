"""Shared fixtures: isolate the DB per test session, register the live marker."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# point the DB at a temp file BEFORE server modules load
os.environ["NR_DB"] = os.path.join(tempfile.mkdtemp(prefix="nr-test-"), "test.sqlite")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits real SEBI endpoints (deselect by default: -m 'not live')")


@pytest.fixture(scope="session")
def db_ready():
    from server import db
    db.init()
    return db
