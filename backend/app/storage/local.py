"""Adapter de storage per a filesystem local."""
import io
import shutil
from pathlib import Path
from .protocol import StorageService


class LocalFSStorage:
    """Implementació de StorageService per a filesystem local."""

    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative: str) -> Path:
        """Resol el path i valida que estigui dins del base per evitar path traversal."""
        resolved = (self._base / relative).resolve()
        try:
            resolved.relative_to(self._base)
        except ValueError:
            raise ValueError(f"Path traversal detectat: {relative!r}")
        return resolved

    def upload(self, path: str, data: bytes | io.IOBase, content_type: str = "application/octet-stream") -> None:
        dest = self._safe_path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            dest.write_bytes(data)
        else:
            with open(dest, "wb") as f:
                shutil.copyfileobj(data, f)

    def download(self, path: str) -> bytes:
        return self._safe_path(path).read_bytes()

    def download_stream(self, path: str) -> io.BytesIO:
        return io.BytesIO(self.download(path))

    def delete(self, path: str) -> None:
        p = self._safe_path(path)
        if p.exists():
            p.unlink()

    def delete_prefix(self, prefix: str) -> None:
        if not prefix or prefix in (".", "/"):
            raise ValueError("prefix no pot ser buit ni arrel")
        p = self._safe_path(prefix)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    def exists(self, path: str) -> bool:
        return self._safe_path(path).exists()

    def list(self, prefix: str = "") -> list[str]:
        base = self._safe_path(prefix) if prefix else self._base
        if not base.exists():
            return []
        result = []
        for p in base.rglob("*"):
            if p.is_file():
                result.append(str(p.relative_to(self._base)))
        return result

    def public_url(self, path: str) -> str | None:
        return None
