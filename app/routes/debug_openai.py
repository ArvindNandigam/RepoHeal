from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_library_intelligence_service
from app.services.library_intelligence import LibraryIntelligenceService


router = APIRouter(tags=["debug"])


@router.post("/debug-openai")
def debug_openai(
    request: Request,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
) -> dict[str, object]:
    request.state.library = "openai"
    request.state.symbols = []
    request.state.libraries = ["openai"]
    return service.build_response_payload("openai", [])