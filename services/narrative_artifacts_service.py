import difflib
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Iterator

from fastapi import Depends
from repositories.storage_repository import ObjectStorageRepository, get_storage_repository
from core.settings import Settings, get_settings


import pandas as pd

from core.settings import Settings, get_settings
from domain.narrative_rules import comp_key, norm

class NarrativeArtifactsService:
    def __init__(
        self,
        settings: Settings,
        storage_repo: ObjectStorageRepository | None = None,
    ) -> None:
        self._storage = storage_repo
        self._settings = settings
        self._artifact_sources: dict[str, str] = {}
        self._artifact_info = self._resolve_artifact_context()
        self._release_manifest = self._load_release_manifest()
        self._framework_rows = self._load_framework_rows()
        self._competency_descriptions = self._load_competency_descriptions()

    @property
    def artifact_info(self) -> dict[str, Any]:
        return self._artifact_info

    @property
    def artifact_sources(self) -> dict[str, str]:
        return dict(self._artifact_sources)

    @property
    def startup_errors(self) -> list[str]:
        return list(self._artifact_info.get("errors") or [])

    def close(self) -> None:
        self._storage.close()

    @property
    def ready(self) -> bool:
        if not bool(self._artifact_info.get("enabled")):
            return True
        if not self._artifact_info.get("release_prefix"):
            return False
        if not self._framework_rows or not self._competency_descriptions:
            return False
        return not bool(self._artifact_info.get("errors"))

    @property
    def framework_rows_loaded(self) -> int:
        return len(self._framework_rows)

    @property
    def competency_descriptions_loaded(self) -> int:
        return len(self._competency_descriptions)

    @property

    @property

    def framework_rows_preview(self, limit: int = 3) -> list[dict[str, Any]]:
        return self._framework_rows[:limit]

    def competency_descriptions_preview(self, limit: int = 3) -> dict[str, str]:
        return dict(list(self._competency_descriptions.items())[:limit])


    def _resolve_artifact_context(self) -> dict[str, Any]:
        bucket_uri = self._storage.bucket_uri
        cache_dir = Path(self._settings.artifact_local_cache_dir).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)

        info: dict[str, Any] = {
            "enabled": self._storage.enabled,
            "bucket_uri": bucket_uri,
            "release_prefix": None,
            "cache_dir": str(cache_dir),
            "storage_options": {
                "has_connection_string": bool(self._storage.storage_options.get("connection_string")),
            },
            "errors": [],
        }

        if not self._storage.enabled:
            return info

        try:
            release_version = (self._settings.artifact_release_version or "").strip()
            if release_version:
                info["release_prefix"] = f"{bucket_uri.rstrip('/')}/releases/{release_version}"
                return info

            latest = self._storage.read_json("latest.json")
            info["release_prefix"] = latest.get("release_prefix")
        except Exception as exc:
            info["errors"].append(f"artifact_context_error: {exc}")

        return info

    def _load_release_manifest(self) -> dict[str, Any]:
        release_prefix = str(self._artifact_info.get("release_prefix") or "").strip()
        if not release_prefix:
            return {}

        try:
            manifest = self._storage.read_json("release_manifest.json", base_uri=release_prefix)
            if isinstance(manifest, dict):
                self._artifact_info["release_manifest"] = {
                    "release_version": manifest.get("release_version"),
                    "artifact_count": manifest.get("artifact_count"),
                }
                return manifest
        except Exception as exc:
            self._artifact_info.setdefault("errors", []).append(f"release_manifest_error: {exc}")

        return {}

    def _manifest_entry(self, relative_path: str) -> dict[str, Any] | None:
        artifacts = self._release_manifest.get("artifacts") if isinstance(self._release_manifest, dict) else None
        if not isinstance(artifacts, list):
            return None
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if str(artifact.get("name") or "").strip() == relative_path:
                return artifact
        return None

    @staticmethod
    def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_local_file(self, path: Path, expected: dict[str, Any] | None) -> bool:
        if not expected:
            return path.exists()
        if not path.exists():
            return False

        expected_size = expected.get("size_bytes")
        if expected_size is not None:
            try:
                if int(path.stat().st_size) != int(expected_size):
                    return False
            except Exception:
                return False

        expected_hash = str(expected.get("sha256") or "").strip().lower()
        if expected_hash:
            actual_hash = self._sha256_file(path).lower()
            if actual_hash != expected_hash:
                return False
        return True

    def _artifact_local_path(self, relative_path: str, local_fallback: Path) -> Path:
        release_prefix = self._artifact_info.get("release_prefix")
        if not release_prefix:
            self._artifact_sources[relative_path] = "local_fallback"
            return local_fallback

        cache_dir = Path(self._artifact_info["cache_dir"])
        local_cache_path = cache_dir / relative_path
        local_cache_path.parent.mkdir(parents=True, exist_ok=True)
        expected = self._manifest_entry(relative_path)

        if local_cache_path.exists() and self._verify_local_file(local_cache_path, expected):
            self._artifact_sources[relative_path] = "cloud_storage_cached"
            return local_cache_path

        if local_cache_path.exists() and not self._verify_local_file(local_cache_path, expected):
            try:
                local_cache_path.unlink()
            except Exception:
                pass

        try:
            self._storage.download_to_local(
                relative_path,
                local_cache_path,
                base_uri=str(release_prefix),
            )

            if not self._verify_local_file(local_cache_path, expected):
                self._artifact_info.setdefault("errors", []).append(
                    f"artifact_checksum_error:{relative_path}"
                )
                self._artifact_sources[relative_path] = "local_fallback"
                return local_fallback
            self._artifact_sources[relative_path] = "cloud_storage_downloaded"
            return local_cache_path
        except Exception as exc:
            self._artifact_info.setdefault("errors", []).append(
                f"artifact_fetch_error:{relative_path}: {exc}"
            )
            self._artifact_sources[relative_path] = "local_fallback"
            return local_fallback

    def _load_framework_rows(self) -> list[dict[str, Any]]:
        path = self._artifact_local_path(
            "framework/framework_rows.jsonl",
            Path("framework_index") / "framework_rows.jsonl",
        )
        if not path.exists():
            return []

        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    @staticmethod
    def _resolve_col(frame: pd.DataFrame, *names: str) -> str | None:
        index = {" ".join(str(c).strip().lower().split()): c for c in frame.columns}
        for name in names:
            key = " ".join(str(name).strip().lower().split())
            if key in index:
                return index[key]
        return None

    def _load_competency_descriptions(self) -> dict[str, str]:
        path = self._artifact_local_path(
            "competency/competencies_clean.xlsx",
            Path("data preprocessing") / "competencies_clean.xlsx",
        )
        if not path.exists():
            return {}

        try:
            frame = pd.read_excel(path)
        except Exception as exc:
            self._artifact_info.setdefault("errors", []).append(f"competency_excel_read_error: {exc}")
            return {}

        comp_col = self._resolve_col(frame, "Competency", "Competency Name", "Competency in Eng", "competencyName")
        desc_col = self._resolve_col(
            frame,
            "Competency Description",
            "Competency Description in Eng",
            "Description",
            "competencyDescription",
        )
        if comp_col is None or desc_col is None:
            self._artifact_info.setdefault("errors", []).append(
                f"competency_excel_columns_not_found: found={list(frame.columns)}"
            )
            return {}

        out: dict[str, str] = {}
        for _, row in frame.iterrows():
            comp = row.get(comp_col)
            desc = row.get(desc_col)
            if pd.isna(comp) or pd.isna(desc):
                continue
            comp_name = str(comp).strip()
            text = str(desc).strip()
            if not comp_name or not text:
                continue
            out[comp_name] = text
            out[norm(comp_name)] = text
            out[comp_key(comp_name)] = text
        return out

    def lookup_framework_rows(self, competency: str) -> list[dict[str, Any]]:
        key = comp_key(competency)
        hits = [r for r in self._framework_rows if r.get("competency_key") == key]
        if hits:
            return hits

        normalized = competency.strip().lower()
        return [r for r in self._framework_rows if str(r.get("competency", "")).strip().lower() == normalized]

    def lookup_competency_description(self, competency: str) -> str | None:
        if not self._competency_descriptions:
            return None

        probes = [competency, norm(competency), comp_key(competency)]
        for probe in probes:
            if probe in self._competency_descriptions:
                return self._competency_descriptions[probe]

        normalized = norm(competency)
        close = difflib.get_close_matches(normalized, list(self._competency_descriptions.keys()), n=1, cutoff=0.87)
        if close:
            return self._competency_descriptions.get(close[0])
        return None


def get_artifacts_service(
    storage_repo: Annotated[ObjectStorageRepository, Depends(get_storage_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[NarrativeArtifactsService]:
    artifacts =  NarrativeArtifactsService(settings, storage_repo)
    try:
        yield artifacts
    finally:
        artifacts.close()
