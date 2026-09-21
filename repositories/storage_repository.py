import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

import fsspec

from core.settings import Settings, get_settings
from fastapi import Depends


def _norm_rel(path: str) -> str:
    return str(PurePosixPath(path.strip().replace("\\", "/"))).lstrip("/")


class ObjectStorageRepository:
    def __init__(self, settings: Settings) -> None:
        self.bucket_uri = (settings.artifact_bucket_uri or "").strip()
        self.storage_options: dict[str, Any] = {}
        if settings.azure_storage_connection_string:
            self.storage_options["connection_string"] = settings.azure_storage_connection_string

    @property
    def enabled(self) -> bool:
        return bool(self.bucket_uri)

    def close(self) -> None:
        # fsspec filesystems are created per-call; nothing persistent to release.
        pass

    @staticmethod
    def _join_base_and_rel(base: str, relative_path: str) -> str:
        rel = _norm_rel(relative_path)
        if not rel:
            return base.rstrip("/")
        return f"{base.rstrip('/')}/{rel}"

    def _get_fs_and_base(self, base_uri: str | None = None) -> tuple[Any, str]:
        uri = (base_uri or self.bucket_uri).strip().rstrip("/")
        if not uri:
            raise ValueError("Storage bucket URI is not configured.")
        fs, _, paths = fsspec.get_fs_token_paths(uri, storage_options=self.storage_options)
        return fs, paths[0].rstrip("/")

    def read_json(self, relative_path: str, base_uri: str | None = None) -> Any:
        fs, base = self._get_fs_and_base(base_uri)
        remote_path = self._join_base_and_rel(base, relative_path)
        with fs.open(remote_path, "r") as handle:
            return json.load(handle)

    def write_json(self, relative_path: str, payload: Any, base_uri: str | None = None) -> None:
        fs, base = self._get_fs_and_base(base_uri)
        remote_path = self._join_base_and_rel(base, relative_path)
        parent = str(PurePosixPath(remote_path).parent)
        fs.makedirs(parent, exist_ok=True)
        with fs.open(remote_path, "w") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True))

    def exists(self, relative_path: str, base_uri: str | None = None) -> bool:
        fs, base = self._get_fs_and_base(base_uri)
        remote_path = self._join_base_and_rel(base, relative_path)
        return bool(fs.exists(remote_path))

    def delete(self, relative_path: str, base_uri: str | None = None) -> None:
        fs, base = self._get_fs_and_base(base_uri)
        remote_path = self._join_base_and_rel(base, relative_path)
        if fs.exists(remote_path):
            fs.rm(remote_path)

    def list_relative_paths(self, relative_prefix: str = "", base_uri: str | None = None) -> list[str]:
        fs, base = self._get_fs_and_base(base_uri)
        prefix = self._join_base_and_rel(base, relative_prefix) if relative_prefix else base
        paths = fs.find(prefix)
        base_norm = base.replace("\\", "/")
        out: list[str] = []
        for path in paths:
            raw = str(path).replace("\\", "/")
            if raw == base_norm:
                continue
            if raw.startswith(base_norm + "/"):
                out.append(raw[len(base_norm) + 1 :])
            else:
                out.append(raw)
        return out

    def download_to_local(
        self,
        relative_path: str,
        local_path: Path,
        base_uri: str | None = None,
    ) -> Path:
        fs, base = self._get_fs_and_base(base_uri)
        remote_path = self._join_base_and_rel(base, relative_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with fs.open(remote_path, "rb") as src:
            with local_path.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        return local_path
def get_storage_repository(settings: Settings = Depends(get_settings)) -> ObjectStorageRepository:
    return ObjectStorageRepository(settings=settings)
