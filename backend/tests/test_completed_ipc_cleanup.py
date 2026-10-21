"""A server-deleted command must not prevent cleanup of its response."""
import json
from pathlib import Path
import threading
import time

import pytest

from app.services import simulation_ipc as module
from app.services.simulation_ipc import (
    CommandStatus, CommandType, IPCResponse, SimulationIPCClient, SimulationIPCServer,
)


@pytest.mark.parametrize("server_removes_command", [False, True])
def test_completed_exchange_cleans_both_protocol_files(monkeypatch, tmp_path, server_removes_command):
    client = SimulationIPCClient(str(tmp_path))
    server = SimulationIPCServer(str(tmp_path))
    response_ready = threading.Event()
    stop = threading.Event()
    errors = []
    original_exists = module.os.path.exists

    def observe_only_complete_server_response(path):
        if Path(path).parent == Path(client.responses_dir) and str(path).endswith(".json"):
            response_ready.wait(timeout=2)
        return original_exists(path)

    # Deterministically observe the state after the server finishes responding,
    # rather than depending on thread scheduling between its write and unlink.
    monkeypatch.setattr(module.os.path, "exists", observe_only_complete_server_response)

    def respond():
        try:
            deadline = time.monotonic() + 2
            while not stop.is_set() and time.monotonic() < deadline:
                command = server.poll_commands()
                if command:
                    response = IPCResponse(command.command_id, CommandStatus.COMPLETED,
                                           result={"answer": "local test response"})
                    if server_removes_command:
                        server.send_response(response)
                    else:
                        # Also cover the allowed interleaving where the client
                        # observes a response before the server removes its command.
                        (Path(server.responses_dir) / f"{command.command_id}.json").write_text(
                            json.dumps(response.to_dict()), encoding="utf-8"
                        )
                    response_ready.set()
                    return
                stop.wait(0.005)
        except Exception as error:
            errors.append(error)
            response_ready.set()

    thread = threading.Thread(target=respond)
    thread.start()
    try:
        response = client.send_command(CommandType.INTERVIEW, {"agent_id": 7}, timeout=3, poll_interval=0.005)
    finally:
        stop.set()
        thread.join(timeout=3)
    assert not errors
    assert not thread.is_alive()
    assert response.status == CommandStatus.COMPLETED
    assert response.result == {"answer": "local test response"}
    assert not list(Path(client.commands_dir).glob("*.json"))
    assert not list(Path(client.responses_dir).glob("*.json"))
