"""Interfície abstracta per a la capa de storage de fitxers."""
from typing import IO, Iterator, Protocol, runtime_checkable


@runtime_checkable
class StorageService(Protocol):
    def upload(self, path: str, data: bytes | IO, content_type: str = "application/octet-stream") -> None:
        ...

    def download(self, path: str) -> bytes:
        ...

    def download_stream(self, path: str) -> IO:
        ...

    def delete(self, path: str) -> None:
        ...

    def delete_prefix(self, prefix: str) -> None:
        """Esborra tots els fitxers que comencen per prefix."""
        ...

    def exists(self, path: str) -> bool:
        ...

    def list(self, prefix: str = "") -> list[str]:
        """Retorna paths relatius sota el prefix."""
        ...

    def public_url(self, path: str) -> str | None:
        """URL pública si el backend ho suporta, None si no."""
        ...
