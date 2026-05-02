import os
import pytest


def test_database_url_default():
    """DATABASE_URL per defecte ha de ser SQLite"""
    from backend.app.config import Config
    assert Config.DATABASE_URL.startswith("sqlite")


def test_storage_type_default():
    from backend.app.config import Config
    assert Config.STORAGE_TYPE == "local"


def test_storage_local_path_exists():
    from backend.app.config import Config
    assert Config.STORAGE_LOCAL_PATH is not None
