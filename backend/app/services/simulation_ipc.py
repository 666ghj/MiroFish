"""
Simulation IPC channel
Inter-process communication between the Flask backend and a simulation script.

A simple command/response protocol over the file system:
1. Flask writes a command into the commands/ directory.
2. The simulation script polls that directory, runs the command and writes a
   response into the responses/ directory.
3. Flask polls the responses directory for the result.
"""

import os
import json
import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..utils.logger import get_logger

logger = get_logger('sosim.simulation_ipc')


class CommandType(str, Enum):
    """Command type"""
    INTERVIEW = "interview"              # Interview a single agent
    BATCH_INTERVIEW = "batch_interview"  # Interview several agents
    CLOSE_ENV = "close_env"              # Shut the environment down


class CommandStatus(str, Enum):
    """Command status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IPCCommand:
    """A command sent to the simulation process"""
    command_id: str
    command_type: CommandType
    args: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type.value,
            "args": self.args,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPCCommand':
        return cls(
            command_id=data["command_id"],
            command_type=CommandType(data["command_type"]),
            args=data.get("args", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


@dataclass
class IPCResponse:
    """A response returned by the simulation process"""
    command_id: str
    status: CommandStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPCResponse':
        return cls(
            command_id=data["command_id"],
            status=CommandStatus(data["status"]),
            result=data.get("result"),
            error=data.get("error"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


class SimulationIPCClient:
    """
    IPC client, used on the Flask side.

    Sends commands to a simulation process and waits for the response.
    """

    def __init__(self, simulation_dir: str):
        """
        Create a client bound to one simulation directory.

        Args:
            simulation_dir: Simulation data directory
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")

        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

    def send_command(
        self,
        command_type: CommandType,
        args: Dict[str, Any],
        timeout: float = 60.0,
        poll_interval: float = 0.5
    ) -> IPCResponse:
        """
        Send a command and wait for its response.

        Args:
            command_type: Command type
            args: Command arguments
            timeout: Response timeout, in seconds
            poll_interval: Poll interval, in seconds

        Returns:
            IPCResponse

        Raises:
            TimeoutError: No response arrived within the timeout
        """
        command_id = str(uuid.uuid4())
        command = IPCCommand(
            command_id=command_id,
            command_type=command_type,
            args=args
        )

        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        with open(command_file, 'w', encoding='utf-8') as f:
            json.dump(command.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"Sending IPC command {command_type.value}, command_id={command_id}")

        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        start_time = time.time()

        while time.time() - start_time < timeout:
            if os.path.exists(response_file):
                try:
                    with open(response_file, 'r', encoding='utf-8') as f:
                        response_data = json.load(f)
                    response = IPCResponse.from_dict(response_data)

                    # The exchange is complete, so neither file is needed again.
                    try:
                        os.remove(command_file)
                        os.remove(response_file)
                    except OSError:
                        pass

                    logger.info(f"Received IPC response: command_id={command_id}, status={response.status.value}")
                    return response
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse IPC response: {e}")

            time.sleep(poll_interval)

        logger.error(f"Timed out waiting for IPC response: command_id={command_id}")

        try:
            os.remove(command_file)
        except OSError:
            pass

        raise TimeoutError(f"Timed out after {timeout}s waiting for a response to the command.")

    def send_interview(
        self,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> IPCResponse:
        """
        Interview a single agent.

        Args:
            agent_id: Agent ID
            prompt: Interview question
            platform: Platform to interview on (optional)
                - "twitter": Twitter only
                - "reddit": Reddit only
                - None: both platforms on a dual-platform simulation, otherwise
                  the single platform that is running
            timeout: Response timeout, in seconds

        Returns:
            IPCResponse, whose result field holds the interview answers
        """
        args = {
            "agent_id": agent_id,
            "prompt": prompt
        }
        if platform:
            args["platform"] = platform

        return self.send_command(
            command_type=CommandType.INTERVIEW,
            args=args,
            timeout=timeout
        )

    def send_batch_interview(
        self,
        interviews: List[Dict[str, Any]],
        platform: str = None,
        timeout: float = 120.0
    ) -> IPCResponse:
        """
        Interview several agents in one command.

        Args:
            interviews: Interview list, each item {"agent_id": int, "prompt": str, "platform": str (optional)}
            platform: Default platform, overridden by an item's own platform
                - "twitter": Twitter only by default
                - "reddit": Reddit only by default
                - None: both platforms on a dual-platform simulation
            timeout: Response timeout, in seconds

        Returns:
            IPCResponse, whose result field holds every interview answer
        """
        args = {"interviews": interviews}
        if platform:
            args["platform"] = platform

        return self.send_command(
            command_type=CommandType.BATCH_INTERVIEW,
            args=args,
            timeout=timeout
        )

    def send_close_env(self, timeout: float = 30.0) -> IPCResponse:
        """
        Ask the simulation environment to shut down.

        Args:
            timeout: Response timeout, in seconds

        Returns:
            IPCResponse
        """
        return self.send_command(
            command_type=CommandType.CLOSE_ENV,
            args={},
            timeout=timeout
        )

    def check_env_alive(self) -> bool:
        """
        Report whether the simulation environment is alive.

        Liveness is read from env_status.json.
        """
        status_file = os.path.join(self.simulation_dir, "env_status.json")
        if not os.path.exists(status_file):
            return False

        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return status.get("status") == "alive"
        except (json.JSONDecodeError, OSError):
            return False


class SimulationIPCServer:
    """
    IPC server, used on the simulation-script side.

    Polls the commands directory, runs each command and writes the response.
    """

    def __init__(self, simulation_dir: str):
        """
        Create a server bound to one simulation directory.

        Args:
            simulation_dir: Simulation data directory
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")

        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

        self._running = False

    def start(self):
        """Mark the server as running."""
        self._running = True
        self._update_env_status("alive")

    def stop(self):
        """Mark the server as stopped."""
        self._running = False
        self._update_env_status("stopped")

    def _update_env_status(self, status: str):
        """Write the environment status file."""
        status_file = os.path.join(self.simulation_dir, "env_status.json")
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)

    def poll_commands(self) -> Optional[IPCCommand]:
        """
        Poll the commands directory for the oldest pending command.

        Returns:
            IPCCommand, or None when nothing is pending
        """
        if not os.path.exists(self.commands_dir):
            return None

        # Oldest first, so commands are served in the order they were sent.
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                command_files.append((filepath, os.path.getmtime(filepath)))

        command_files.sort(key=lambda x: x[1])

        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return IPCCommand.from_dict(data)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning(f"Failed to read command file {filepath}: {e}")
                continue

        return None

    def send_response(self, response: IPCResponse):
        """
        Write a response and retire the command that produced it.

        Args:
            response: IPC response
        """
        response_file = os.path.join(self.responses_dir, f"{response.command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response.to_dict(), f, ensure_ascii=False, indent=2)

        command_file = os.path.join(self.commands_dir, f"{response.command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass

    def send_success(self, command_id: str, result: Dict[str, Any]):
        """Write a successful response."""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.COMPLETED,
            result=result
        ))

    def send_error(self, command_id: str, error: str):
        """Write a failure response."""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.FAILED,
            error=error
        ))
