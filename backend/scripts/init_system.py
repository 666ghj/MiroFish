#!/usr/bin/env python3
"""
Inicialitzar el sistema MiroFish per al primer ús.
Ús: ADMIN_EMAIL=admin@dev.local ADMIN_PASSWORD=adminpass123 uv run python backend/scripts/init_system.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def main():
    from app.config import Config
    from app.db import init_db, get_session
    from app.models.db_models import UserModel, SystemConfigModel
    from app.services.auth_service import hash_password
    from sqlalchemy import select

    db_url = Config.DATABASE_URL
    short_url = db_url.split('@')[-1] if '@' in db_url else db_url
    print(f"[init_system] Connecting to: {short_url}")
    init_db(db_url)

    # Executar migracions Alembic
    try:
        import subprocess
        result = subprocess.run(
            ['uv', 'run', 'alembic', 'upgrade', 'head'],
            cwd=os.path.dirname(__file__) + '/..',
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[init_system] Alembic warning: {result.stderr}")
        else:
            print("[init_system] Alembic migrations: OK")
    except Exception as e:
        print(f"[init_system] Alembic skipped: {e}")

    with get_session() as db:
        # Crear admin si no existeix cap usuari
        any_user = db.execute(select(UserModel).limit(1)).scalar_one_or_none()
        if any_user is None:
            admin_email = Config.ADMIN_EMAIL or input("Admin email: ").strip()
            admin_password = Config.ADMIN_PASSWORD or input("Admin password: ").strip()
            if not admin_email or not admin_password:
                print("[init_system] ERROR: ADMIN_EMAIL i ADMIN_PASSWORD requerits")
                sys.exit(1)
            admin = UserModel(
                email=admin_email.lower(),
                name="Admin",
                role="admin",
                status="active",
                password_hash=hash_password(admin_password)
            )
            db.add(admin)
            db.commit()
            print(f"[init_system] Admin creat: {admin_email}")
        else:
            print(f"[init_system] Usuaris existents, saltant creació admin")

        # Inserir SystemConfig per defecte si no existeix
        defaults = [
            ('llm.model_name',  Config.LLM_MODEL_NAME,     'string', 'llm',    'Model LLM',        '', False),
            ('llm.base_url',    Config.LLM_BASE_URL,        'string', 'llm',    'URL base LLM',     '', False),
            ('llm.api_key',     Config.LLM_API_KEY or '',   'string', 'llm',    'API Key LLM',      '', True),
            ('limits.max_projects_per_user', '20',          'int',    'limits', 'Màx. projectes',   '', False),
            ('limits.max_simulations',       '10',          'int',    'limits', 'Màx. simulacions', '', False),
        ]
        for key, value, vtype, group, label, desc, is_secret in defaults:
            existing = db.get(SystemConfigModel, key)
            if not existing:
                db.add(SystemConfigModel(
                    key=key, value=value, value_type=vtype,
                    group=group, label=label, description=desc, is_secret=is_secret
                ))
        db.commit()
        print("[init_system] SystemConfig per defecte: OK")

    print("[init_system] Inicialització completada.")


if __name__ == '__main__':
    main()
