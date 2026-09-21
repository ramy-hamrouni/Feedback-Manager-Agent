from typing import Annotated

from fastapi import APIRouter, Depends

from core.settings import Settings, get_settings
from repositories.mongo_repository import MongoRepository, get_mongo_repository
from services.narrative_artifacts_service import NarrativeArtifactsService, get_artifacts_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    artifacts: Annotated[NarrativeArtifactsService, Depends(get_artifacts_service)],
    mongo: Annotated[MongoRepository, Depends(get_mongo_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    artifact_info = dict(artifacts.artifact_info)
    return {
        "status": "ok" if artifacts.ready else "degraded",
        "ready": artifacts.ready,
        "artifact_source": {
            "enabled": artifact_info.get("enabled"),
            "release_prefix": artifact_info.get("release_prefix"),
            "errors": artifact_info.get("errors"),
            "per_artifact": artifacts.artifact_sources,
        },
        "artifact_counts": {
            "framework_rows_loaded": artifacts.framework_rows_loaded,
            "competency_descriptions_loaded": artifacts.competency_descriptions_loaded,
        },
        "artifact_preview": {
            "framework_rows": artifacts.framework_rows_preview(),
            "competency_descriptions": artifacts.competency_descriptions_preview(),
        },
        "mongo": {
            "enabled": mongo.enabled,
            "region": mongo.region,
            "database": settings.mongo_database,
        },
        "runs": {
            "persistence_enabled": settings.persist_runs_to_storage,
            "storage_prefix": settings.run_storage_prefix,
            "bucket_uri": artifact_info.get("bucket_uri"),
        },
    }
