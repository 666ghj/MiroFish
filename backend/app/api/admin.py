"""Admin API: configuració sistema i historial d'execucions."""
from flask import request, jsonify
from sqlalchemy import select, desc, func
from . import admin_bp
from .. import require_admin
from ..db import get_session
from ..models.db_models import SystemConfigModel, SimulationModel, ProjectModel, UserModel


@admin_bp.route('/config', methods=['GET'])
@require_admin
def get_config():
    with get_session() as db:
        entries = db.execute(select(SystemConfigModel)).scalars().all()
        result = []
        for e in entries:
            result.append({
                'key': e.key,
                'value': '●●●●' if e.is_secret else e.value,
                'value_type': e.value_type,
                'group': e.group,
                'label': e.label,
                'description': e.description,
                'is_secret': e.is_secret,
            })
    return jsonify({'success': True, 'data': result})


@admin_bp.route('/config', methods=['PATCH'])
@require_admin
def patch_config():
    data = request.get_json(silent=True) or {}
    with get_session() as db:
        for key, value in data.items():
            entry = db.get(SystemConfigModel, key)
            if entry:
                entry.value = str(value)
        db.commit()
    return jsonify({'success': True})


@admin_bp.route('/executions', methods=['GET'])
@require_admin
def list_executions():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('pageSize', 20, type=int)
    filter_user_id = request.args.get('user_id')
    offset = (page - 1) * page_size

    with get_session() as db:
        stmt = (
            select(SimulationModel, ProjectModel, UserModel)
            .join(ProjectModel, SimulationModel.project_id == ProjectModel.id)
            .outerjoin(UserModel, ProjectModel.user_id == UserModel.id)
            .order_by(desc(SimulationModel.created_at))
        )
        if filter_user_id:
            stmt = stmt.where(ProjectModel.user_id == filter_user_id)

        total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
        rows = db.execute(stmt.offset(offset).limit(page_size)).all()
        result = []
        for sim, proj, user in rows:
            result.append({
                'simulation_id': sim.id,
                'project_id': proj.id,
                'project_name': proj.name,
                'user_email': user.email if user else None,
                'status': sim.status,
                'platform': sim.platform,
                'rounds_total': sim.rounds_total,
                'rounds_completed': sim.rounds_completed,
                'created_at': sim.created_at.isoformat(),
            })
    return jsonify({'success': True, 'data': result, 'total': total, 'page': page, 'pageSize': page_size})
