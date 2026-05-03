# backend/alembic/env.py
import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Afegir el backend al path perquè els imports funcionin
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.db import Base
import app.models.db_models  # noqa: F401 — registra tots els models al Base

config = context.config

# Llegir DATABASE_URL de l'entorn (prioritat sobre alembic.ini)
db_url = os.environ.get('DATABASE_URL', config.get_main_option('sqlalchemy.url'))
config.set_main_option('sqlalchemy.url', db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
