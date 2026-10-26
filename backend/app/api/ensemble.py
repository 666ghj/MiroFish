"""
Ensemble API routes (mounted under ``/api/simulation``).

An ensemble runs N seeded replicates of one prepared simulation, polls every
simulated agent at the end of each run, and aggregates the results into
distributions. See ``services/ensemble_runner.py`` for the model.

    POST /ensemble/create                      create + clone replicates, returns questions and cost estimate
    PUT  /ensemble/<id>/outcome-questions      edit the poll questions (only while status is 'created')
    POST /ensemble/<id>/start
    POST /ensemble/<id>/stop
    GET  /ensemble/<id>                        status and per-replicate progress
    GET  /ensemble/<id>/summary                404 until aggregated
    GET  /ensemble/list?simulation_id=
"""

import traceback

from flask import jsonify, request

from . import ensemble_bp
from ..services.ensemble_runner import EnsembleError, EnsembleManager
from ..utils.locale import t
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.ensemble')


def _ok(data, status=200):
    return jsonify({"success": True, "data": data}), status


def _error(message, status):
    return jsonify({"success": False, "error": message}), status


def _handle(error: Exception):
    """Map an exception from the ensemble service to a JSON error response."""
    if isinstance(error, EnsembleError):
        return _error(str(error), error.status_code)
    logger.error(f"Ensemble request failed: {error}")
    return jsonify({
        "success": False,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }), 500


@ensemble_bp.route('/ensemble/create', methods=['POST'])
def create_ensemble():
    """
    Create an ensemble from a prepared simulation.

    Body (JSON)::

        {
            "simulation_id": "sim_xxxx",       // required: the prepared base simulation
            "max_rounds": 24,                  // required: the cost guard
            "n_replicates": 5,                 // 1-50, default 5
            "concurrency": 1,                  // 1-4, default 1
            "base_seed": 12345,                // optional; replicate seeds derive from it
            "platform": "parallel",            // only "parallel" is supported
            "outcome_questions": [...],        // optional: 1-3 questions, [] = no poll;
                                               // derived with one LLM call when omitted
            "llm_temperature": 0.7             // optional, 0-2
        }

    The response carries the questions (edit them with PUT before starting) and
    a conservative ``cost_estimate``. Nothing runs until ``/start``.
    """
    try:
        data = request.get_json(silent=True) or {}
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return _error(t('api.requireSimulationId'), 400)

        ensemble = EnsembleManager.create(
            simulation_id,
            n_replicates=data.get('n_replicates', 5),
            max_rounds=data.get('max_rounds'),
            base_seed=data.get('base_seed'),
            platform=data.get('platform', 'parallel'),
            concurrency=data.get('concurrency', 1),
            outcome_questions=data.get('outcome_questions'),
            llm_temperature=data.get('llm_temperature'),
        )
        return _ok(ensemble, 201)
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/<ensemble_id>/outcome-questions', methods=['PUT'])
def put_outcome_questions(ensemble_id: str):
    """Replace the poll questions. Body: ``{"outcome_questions": [...]}``. Only while status is 'created'."""
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get('outcome_questions'), list):
            return _error("outcome_questions must be a list", 400)
        return _ok(EnsembleManager.update_outcome_questions(ensemble_id, data['outcome_questions']))
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/<ensemble_id>/start', methods=['POST'])
def start_ensemble(ensemble_id: str):
    """Start running the replicates (background thread; poll ``GET /ensemble/<id>``)."""
    try:
        return _ok(EnsembleManager.start(ensemble_id))
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/<ensemble_id>/stop', methods=['POST'])
def stop_ensemble(ensemble_id: str):
    """Stop running replicates and mark the remaining ones stopped."""
    try:
        return _ok(EnsembleManager.stop(ensemble_id))
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/<ensemble_id>/resume', methods=['POST'])
def resume_ensemble(ensemble_id: str):
    """Continue a stopped or interrupted ensemble from where its runs left off."""
    try:
        return _ok(EnsembleManager.resume(ensemble_id))
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/<ensemble_id>/resume-info', methods=['GET'])
def get_ensemble_resume_info(ensemble_id: str):
    """What resuming would do to each run of the ensemble."""
    try:
        return _ok(EnsembleManager.resume_info(ensemble_id))
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/list', methods=['GET'])
def list_ensembles():
    """List ensembles, newest first. Query: ``simulation_id`` filters by base simulation."""
    try:
        ensembles = EnsembleManager.list_ensembles(request.args.get('simulation_id'))
        return jsonify({"success": True, "data": ensembles, "count": len(ensembles)})
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/<ensemble_id>', methods=['GET'])
def get_ensemble(ensemble_id: str):
    """Ensemble status with per-replicate progress (current_round / total_rounds)."""
    try:
        return _ok(EnsembleManager.get(ensemble_id))
    except Exception as error:
        return _handle(error)


@ensemble_bp.route('/ensemble/<ensemble_id>/summary', methods=['GET'])
def get_ensemble_summary(ensemble_id: str):
    """The aggregated summary (distributions per question and behavioural metric); 404 until it exists."""
    try:
        summary = EnsembleManager.summary(ensemble_id)
        if summary is None:
            return _error("The ensemble has not been aggregated yet", 404)
        return _ok(summary)
    except Exception as error:
        return _handle(error)
