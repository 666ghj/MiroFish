"""Selecciona la implementació de StorageService per STORAGE_TYPE."""
import os
from .protocol import StorageService


def create_storage_service() -> StorageService:
    storage_type = os.environ.get("STORAGE_TYPE", "local")
    match storage_type:
        case "azure":
            from .azure_blob import AzureBlobStorage
            conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            container = os.environ.get("AZURE_STORAGE_CONTAINER", "mirofish")
            if not conn_str:
                raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING no configurada per STORAGE_TYPE=azure")
            return AzureBlobStorage(conn_str, container)
        case _:
            from .local import LocalFSStorage
            base = os.environ.get("STORAGE_LOCAL_PATH",
                                   os.path.join(os.path.dirname(__file__), "../../../uploads"))
            return LocalFSStorage(base)
