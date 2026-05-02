"""Storage service for file management."""
from .protocol import StorageService
from .factory import create_storage_service

__all__ = ["StorageService", "create_storage_service"]
