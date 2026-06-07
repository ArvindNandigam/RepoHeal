import sys
import re
from typing import Dict, List, Any
from datetime import datetime, timezone

from app.intelligence.webtool_client import WebtoolClient
from app.models.migration_models import (
    CorrelationResult, SymbolAssessment, SymbolRelationship, VersionDistance
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

def parse_version(v: str):
    if not v or v == "unknown":
        return None

    match = re.search(r"\d+(?:\.\d+){0,2}", str(v))
    if not match:
        return None

    parts = [int(part) for part in match.group(0).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _version_delta(installed: str, target: str):
    v_inst = parse_version(installed)
    v_target = parse_version(target)
    if not v_inst or not v_target:
        return None

    major = v_target[0] - v_inst[0]
    if major > 0:
        return (major, v_target[1], v_target[2])
    if major < 0:
        return (major, v_target[1] - v_inst[1], v_target[2] - v_inst[2])

    minor = v_target[1] - v_inst[1]
    patch = v_target[2] - v_inst[2] if minor == 0 else v_target[2]
    return (major, minor, patch)


def _is_version_gte(installed: str, target: str) -> bool:
    v_inst = parse_version(installed)
    v_target = parse_version(target)
    if not v_inst or not v_target:
        return False
    return v_inst >= v_target


def _evidence_links(relationship: Dict[str, Any]) -> List[str]:
    links = []
    for key in ("evidence_links", "evidence", "urls", "sources"):
        value = relationship.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    links.append(item)
                elif isinstance(item, dict) and item.get("url"):
                    links.append(item["url"])

    for key in ("url", "source_url"):
        value = relationship.get(key)
        if isinstance(value, str):
            links.append(value)

    return list(dict.fromkeys(links))

class MigrationCorrelator:
    def __init__(self, webtool_client: WebtoolClient):
        self.client = webtool_client

    async def correlate(self, analysis: Dict[str, Any], repo_id: str) -> CorrelationResult:
        fingerprints = analysis.get("fingerprints", {})
        dependency_graph = analysis.get("dependency_graph", {})

        assessments: List[SymbolAssessment] = []
        errors: List[str] = []
        total_symbols = 0
        requests = []
        fingerprint_data = {}

        for library, fp_data in fingerprints.items():
            symbols = fp_data.get("symbols", [])
            if (
                not symbols
                or library not in dependency_graph
                or library in sys.stdlib_module_names
            ):
                continue

            unique_symbols = sorted(set(symbols))
            requests.append({
                "library": library,
                "symbols": unique_symbols,
            })
            fingerprint_data[library] = fp_data
            total_symbols += len(symbols)

        libraries_checked = len(requests)
        for offset in range(0, len(requests), 25):
            batch = requests[offset:offset + 25]
            try:
                response = await self._fetch_batch_intelligence(batch)
            except Exception as e:
                batch_names = ", ".join(item["library"] for item in batch)
                logger.error(f"Error fetching bulk intelligence for {batch_names}: {e}")
                errors.append(f"{batch_names}: {str(e)}")
                continue

            for library_response in response.get("results", []):
                library = library_response.get("library")
                if not library or library_response.get("status") == "failed":
                    errors.append(
                        f"{library or 'unknown'}: "
                        f"{library_response.get('reason', 'source_unavailable')}"
                    )
                    continue

                fp_data = fingerprint_data.get(library, {})
                installed_version = fp_data.get("version", "unknown")
                latest_version = dependency_graph.get(
                    library, {}
                ).get("latest_version", "unknown")
                wt_latest = library_response.get("latest_version")
                if wt_latest and wt_latest != "unknown":
                    latest_version = wt_latest

                for result in library_response.get("results", []):
                    symbol_name = result.get("symbol")
                    if not symbol_name:
                        continue

                    relationships = [
                        SymbolRelationship(
                            relation=relationship.get("relation"),
                            target=(
                                relationship.get("target")
                                or relationship.get("to")
                            ),
                            status=relationship.get("status"),
                            confidence=relationship.get("confidence"),
                            evidence_links=_evidence_links(relationship)
                        )
                        for relationship in result.get("relationships", [])
                        if relationship.get("relation")
                        and (relationship.get("target") or relationship.get("to"))
                        and relationship.get("status")
                    ]
                    status = self._determine_status(
                        relationships,
                        installed_version
                    )
                    assessments.append(
                        SymbolAssessment(
                            symbol=symbol_name,
                            library=library,
                            installed_version=installed_version,
                            latest_version=latest_version,
                            status=status,
                            relationships=relationships,
                            version_distance=self._calculate_version_distance(
                                installed_version,
                                latest_version,
                                relationships
                            )
                        )
                    )

        return CorrelationResult(
            repository=repo_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_symbols=total_symbols,
            assessments=assessments,
            libraries_checked=libraries_checked,
            webtool_errors=errors
        )

    async def _fetch_batch_intelligence(self, batch: List[Dict[str, Any]]) -> Dict[str, Any]:
        if hasattr(self.client, "get_bulk_intelligence"):
            response = await self.client.get_bulk_intelligence(batch)
            if isinstance(response, dict) and isinstance(response.get("results"), list):
                return response

        if not hasattr(self.client, "get_symbol_intelligence"):
            return {"results": []}

        results = []
        for item in batch:
            response = await self.client.get_symbol_intelligence(
                item["library"],
                item["symbols"]
            )
            if isinstance(response, dict):
                response.setdefault("library", item["library"])
                results.append(response)

        return {"results": results}
        
    def _determine_status(self, relationships: List[SymbolRelationship], installed_version: str) -> str:
        if not relationships:
            return "healthy"
            
        has_removed = False
        has_deprecated = False
        
        for rel in relationships:
            if rel.relation == "removed_in":
                has_removed = True
                if _is_version_gte(installed_version, rel.target):
                    return "breaking"
            elif rel.relation == "deprecated_in_favor_of":
                has_deprecated = True
            elif rel.relation == "deprecated_in":
                if _is_version_gte(installed_version, rel.target):
                    return "deprecated"
                has_deprecated = True
                
        if has_removed:
            return "at_risk"
        if has_deprecated:
            return "deprecated"
            
        return "healthy"
        
    def _calculate_version_distance(self, installed: str, latest: str, relationships: List[SymbolRelationship]) -> VersionDistance:
        maj_diff, min_diff, pat_diff = 0, 0, 0
        latest_delta = _version_delta(installed, latest)
        if latest_delta:
            maj_diff, min_diff, pat_diff = [max(0, value) for value in latest_delta]
                
        dep_in = None
        rem_in = None
        for rel in relationships:
            if rel.relation == "deprecated_in":
                dep_in = rel.target
            elif rel.relation == "removed_in":
                rem_in = rel.target

        dep_delta = _version_delta(installed, dep_in) if dep_in else None
        rem_delta = _version_delta(installed, rem_in) if rem_in else None
                
        return VersionDistance(
            installed=installed,
            latest=latest,
            deprecated_in=dep_in,
            removed_in=rem_in,
            major_diff=maj_diff,
            minor_diff=min_diff,
            patch_diff=pat_diff,
            deprecated_major_diff=dep_delta[0] if dep_delta else None,
            deprecated_minor_diff=dep_delta[1] if dep_delta else None,
            deprecated_patch_diff=dep_delta[2] if dep_delta else None,
            removed_major_diff=rem_delta[0] if rem_delta else None,
            removed_minor_diff=rem_delta[1] if rem_delta else None,
            removed_patch_diff=rem_delta[2] if rem_delta else None
        )
