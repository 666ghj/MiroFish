"""Selecciona la implementació de StorageService per STORAGE_TYPE."""
from .protocol import StorageService


def create_storage_service() -> StorageService:
    from app.config import Config
    storage_type = Config.STORAGE_TYPE
    match storage_type:
        case "azure":
            from .azure_blob import AzureBlobStorage
            conn_str = Config.AZURE_STORAGE_CONNECTION_STRING
            container = Config.AZURE_STORAGE_CONTAINER
            if not conn_str:
                raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING no configurada per STORAGE_TYPE=azure")
            return AzureBlobStorage(conn_str, container)
        case _:
            from .local import LocalFSStorage
            return LocalFSStorage(Config.STORAGE_LOCAL_PATH)
