"""Adapter de storage per a Azure Blob Storage."""
import io
from .protocol import StorageService


class AzureBlobStorage:
    """Implementació de StorageService per a Azure Blob Storage."""

    def __init__(self, connection_string: str, container_name: str) -> None:
        from azure.storage.blob import BlobServiceClient
        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._container = container_name
        self._ensure_container()

    def _ensure_container(self) -> None:
        container_client = self._client.get_container_client(self._container)
        if not container_client.exists():
            container_client.create_container()

    def _blob_client(self, path: str):
        return self._client.get_blob_client(container=self._container, blob=path)

    def upload(self, path: str, data: bytes | io.IOBase, content_type: str = "application/octet-stream") -> None:
        blob = self._blob_client(path)
        if isinstance(data, bytes):
            blob.upload_blob(data, overwrite=True, content_settings={"content_type": content_type})
        else:
            blob.upload_blob(data, overwrite=True, content_settings={"content_type": content_type})

    def download(self, path: str) -> bytes:
        return self._blob_client(path).download_blob().readall()

    def download_stream(self, path: str) -> io.BytesIO:
        return io.BytesIO(self.download(path))

    def delete(self, path: str) -> None:
        self._blob_client(path).delete_blob(delete_snapshots="include")

    def delete_prefix(self, prefix: str) -> None:
        container = self._client.get_container_client(self._container)
        blobs = container.list_blobs(name_starts_with=prefix)
        for blob in blobs:
            container.delete_blob(blob.name, delete_snapshots="include")

    def exists(self, path: str) -> bool:
        return self._blob_client(path).exists()

    def list(self, prefix: str = "") -> list[str]:
        container = self._client.get_container_client(self._container)
        return [b.name for b in container.list_blobs(name_starts_with=prefix)]

    def public_url(self, path: str) -> str | None:
        return self._blob_client(path).url
