"""
Module Giao tiếp IPC của Mô phỏng
Dùng cho giao tiếp liên tiến trình giữa backend Flask và file script mô phỏng

Cấu trúc lệnh/phản hồi đơn giản được hiện thực hóa thông qua hệ thống tệp:
1. Flask ghi lệnh vào thư mục commands/
2. Kịch bản mô phỏng thăm dò (poll) thư mục lệnh, thực thi lệnh và ghi chuỗi phản hồi vào thư mục responses/
3. Flask thăm dò lại thư mục phản hồi để nhận kết quả
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

logger = get_logger('mirofish.simulation_ipc')


class CommandType(str, Enum):
    """Các loại lệnh (command)"""
    INTERVIEW = "interview"           # Phỏng vấn agent đơn lẻ
    BATCH_INTERVIEW = "batch_interview"  # Phỏng vấn hàng loạt
    CLOSE_ENV = "close_env"           # Đóng môi trường


class CommandStatus(str, Enum):
    """Trạng thái của các lệnh (command)"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IPCCommand:
    """Lệnh (Command) IPC"""
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
    """Phản hồi (Response) IPC"""
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
    Client (Máy khách) IPC Mô phỏng (dùng phía Flask)
    
    Được dùng để gửi file tới tiến trình mô phỏng và chờ response trả về
    """
    
    def __init__(self, simulation_dir: str):
        """
        Khởi tạo Client IPC
        
        Args:
            simulation_dir: Thư mục chứa dữ liệu mô phỏng
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")
        
        # Đảm bảo rằng thư mục đã tồn tại
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
        Gửi lệnh ra và đợi kết quả phản hồi lại
        
        Args:
            command_type: Loại lệnh
            args: Tham số của lệnh
            timeout: Thời gian timeout (giây)
            poll_interval: Khoảng thời gian giữa các lần thăm dò (giây)
            
        Returns:
            IPCResponse
            
        Raises:
            TimeoutError: Lỗi quá thời gian chờ phản hồi
        """
        command_id = str(uuid.uuid4())
        command = IPCCommand(
            command_id=command_id,
            command_type=command_type,
            args=args
        )
        
        # Ghi vào file lệnh
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        with open(command_file, 'w', encoding='utf-8') as f:
            json.dump(command.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Send IPC command: {command_type.value}, command_id={command_id}")
        
        # Chờ kết quả phản hồi
        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if os.path.exists(response_file):
                try:
                    with open(response_file, 'r', encoding='utf-8') as f:
                        response_data = json.load(f)
                    response = IPCResponse.from_dict(response_data)
                    
                    # Xóa file lệnh và file phản hồi đi
                    try:
                        os.remove(command_file)
                        os.remove(response_file)
                    except OSError:
                        pass
                    
                    logger.info(f"Received IPC response: command_id={command_id}, status={response.status.value}")
                    return response
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse response: {e}")
            
            time.sleep(poll_interval)
        
        # Timed out
        logger.error(f"Timeout waiting for IPC response: command_id={command_id}")
        
        # Xóa file lệnh đi
        try:
            os.remove(command_file)
        except OSError:
            pass
        
        raise TimeoutError(f"Wait command response timed out ({timeout} seconds)")
    
    def send_interview(
        self,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> IPCResponse:
        """
        Gửi lệnh phỏng vấn agent đơn lẻ
        
        Args:
            agent_id: Agent ID
            prompt: Câu hỏi phỏng vấn
            platform: Chỉ định nền tảng (Tùy chọn)
                - "twitter": Chỉ phỏng vấn ở nền tảng Twitter
                - "reddit": Chỉ phỏng vấn ở nền tảng Reddit
                - None: Phỏng vấn đồng thời cả hai nền tảng khi mô phỏng nền tảng kép, phỏng vấn một nền tảng đó khi mô phỏng nền tảng đơn
            timeout: Thời gian timeout
            
        Returns:
            IPCResponse, trong đó trường result sẽ chứa kết quả cuộc phỏng vấn
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
        Gửi lệnh phỏng vấn hàng loạt
        
        Args:
            interviews: Danh sách phỏng vấn, mỗi phần tử chứa {"agent_id": int, "prompt": str, "platform": str(Tùy chọn)}
            platform: Nền tảng mặc định (Tùy chọn, sẽ bị ghi đè bởi "platform" của từng mục phỏng vấn riêng lẻ)
                - "twitter": Mặc định chỉ phỏng vấn ở nền tảng Twitter
                - "reddit": Mặc định chỉ phỏng vấn ở nền tảng Reddit
                - None: Mỗi Agent sẽ được phỏng vấn đồng thời trên cả hai nền tảng khi mô phỏng nền tảng kép
            timeout: Thời gian timeout
            
        Returns:
            IPCResponse, trong đó trường result sẽ chứa tất cả các kết quả phỏng vấn
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
        Gửi lệnh đóng môi trường
        
        Args:
            timeout: Thời gian timeout
            
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
        Kiểm tra xem môi trường mô phỏng còn sống hay không
        
        Được xác định thông qua việc kiểm tra tệp tin env_status.json
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
    Server (Máy chủ) IPC Mô phỏng (dùng phía kịch bản mô phỏng)
    
    Tiến hành thăm dò thư mục lệnh, thực thi lệnh và trả về kết quả phản hồi
    """
    
    def __init__(self, simulation_dir: str):
        """
        Khởi tạo Máy chủ IPC
        
        Args:
            simulation_dir: Thư mục chứa dữ liệu mô phỏng
        """
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, "ipc_commands")
        self.responses_dir = os.path.join(simulation_dir, "ipc_responses")
        
        # Đảm bảo rằng thư mục đã tồn tại
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
        
        # Trạng thái môi trường
        self._running = False
    
    def start(self):
        """Đánh dấu Máy chủ đang ở trạng thái chạy"""
        self._running = True
        self._update_env_status("alive")
    
    def stop(self):
        """Đánh dấu Máy chủ đang ở trạng thái dừng"""
        self._running = False
        self._update_env_status("stopped")
    
    def _update_env_status(self, status: str):
        """Cập nhật tệp trạng thái môi trường"""
        status_file = os.path.join(self.simulation_dir, "env_status.json")
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def poll_commands(self) -> Optional[IPCCommand]:
        """
        Thăm dò thư mục lệnh, trả về lệnh chờ xử lý đầu tiên
        
        Returns:
            IPCCommand hoặc None
        """
        if not os.path.exists(self.commands_dir):
            return None
        
        # Lấy danh sách file lệnh và sắp xếp theo thời gian
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
                logger.warning(f"Failed to read command file: {filepath}, {e}")
                continue
        
        return None
    
    def send_response(self, response: IPCResponse):
        """
        Gửi phản hồi
        
        Args:
            response: Phản hồi IPC
        """
        response_file = os.path.join(self.responses_dir, f"{response.command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Xóa file lệnh đi
        command_file = os.path.join(self.commands_dir, f"{response.command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    def send_success(self, command_id: str, result: Dict[str, Any]):
        """Gửi phản hồi thành công"""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.COMPLETED,
            result=result
        ))
    
    def send_error(self, command_id: str, error: str):
        """Gửi phản hồi lỗi"""
        self.send_response(IPCResponse(
            command_id=command_id,
            status=CommandStatus.FAILED,
            error=error
        ))
