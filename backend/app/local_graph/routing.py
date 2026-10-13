"""Prevent stored projects from silently moving between graph providers."""

from flask import request
from ..config import Config


def check_project_provider():
    if not request.path.startswith('/api/') or request.method == 'OPTIONS':
        return None
    from ..models.project import ProjectManager
    from ..services.simulation_manager import SimulationManager
    body = request.get_json(silent=True)
    values = {**request.args, **(body if isinstance(body, dict) else {}), **(request.view_args or {})}
    projects = []
    project_id = values.get('project_id')
    if not project_id and values.get('simulation_id'):
        state = SimulationManager().get_simulation(values['simulation_id'])
        project_id = state.project_id if state else None
    if project_id:
        project = ProjectManager.get_project(project_id)
        if project:
            projects.append(project)
    if values.get('graph_id'):
        projects.extend(ProjectManager.find_projects_by_graph_id(values['graph_id']))
    for project in projects:
        if project.graph_provider != Config.GRAPH_PROVIDER:
            return {'success': False, 'error':
                    f'This project uses graph provider {project.graph_provider}, but the app is configured for '
                    f'{Config.GRAPH_PROVIDER}. Switch providers or create a new project.'}, 409
    return None
