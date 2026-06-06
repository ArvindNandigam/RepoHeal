import asyncio
from typing import Dict, List, Any
from datetime import datetime, timezone
import packaging.version

from app.intelligence.webtool_client import WebtoolClient
from app.models.migration_models import (
    CorrelationResult, SymbolAssessment, SymbolRelationship, VersionDistance
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

def parse_version(v: str):
    try:
        return packaging.version.parse(v)
    except:
        return None

class MigrationCorrelator:
    def __init__(self, webtool_client: WebtoolClient):
        self.client = webtool_client

    async def correlate(self, analysis: Dict[str, Any], repo_id: str) -> CorrelationResult:
        fingerprints = analysis.get("fingerprints", {})
        dependency_graph = analysis.get("dependency_graph", {})
        
        assessments: List[SymbolAssessment] = []
        errors: List[str] = []
        libraries_checked = 0
        total_symbols = 0
        
        for library, fp_data in fingerprints.items():
            symbols = fp_data.get("symbols", [])
            installed_version = fp_data.get("version", "unknown")
            latest_version = dependency_graph.get(library, {}).get("latest_version", "unknown")
            
            if not symbols:
                continue
                
            libraries_checked += 1
            total_symbols += len(symbols)
            
            try:
                # Query Restricted Webtool
                response = await self.client.get_symbol_intelligence(library, symbols)
                results = response.get("results", [])
                
                # We can also update latest_version if webtool has better data
                wt_latest = response.get("latest_version")
                if wt_latest and wt_latest != "unknown":
                    latest_version = wt_latest

                for res in results:
                    symbol_name = res.get("symbol")
                    relationships_data = res.get("relationships", [])
                    
                    relationships = []
                    for rel_data in relationships_data:
                        relationships.append(
                            SymbolRelationship(
                                relation=rel_data.get("relation"),
                                target=rel_data.get("target"),
                                status=rel_data.get("status"),
                                confidence=rel_data.get("confidence")
                            )
                        )
                    
                    status = self._determine_status(relationships, installed_version)
                    version_distance = self._calculate_version_distance(
                        installed_version, latest_version, relationships
                    )
                    
                    assessment = SymbolAssessment(
                        symbol=symbol_name,
                        library=library,
                        installed_version=installed_version,
                        latest_version=latest_version,
                        status=status,
                        relationships=relationships,
                        version_distance=version_distance
                    )
                    assessments.append(assessment)
                    
            except Exception as e:
                logger.error(f"Error fetching intelligence for {library}: {e}")
                errors.append(f"{library}: {str(e)}")
                
        return CorrelationResult(
            repository=repo_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_symbols=total_symbols,
            assessments=assessments,
            libraries_checked=libraries_checked,
            webtool_errors=errors
        )
        
    def _determine_status(self, relationships: List[SymbolRelationship], installed_version: str) -> str:
        if not relationships:
            return "healthy"
            
        has_breaking = False
        has_deprecated = False
        
        # If any relationship is "removed_in", check versions
        for rel in relationships:
            if rel.relation == "removed_in":
                has_breaking = True # Simple heuristic for now: if there's a removed_in, it's breaking or at_risk.
                # If we could parse version, we could check if installed >= removed.
                v_inst = parse_version(installed_version)
                v_rem = parse_version(rel.target)
                if v_inst and v_rem:
                    if v_inst >= v_rem:
                        return "breaking"
                    else:
                        return "at_risk"
            elif rel.relation == "deprecated_in_favor_of":
                has_deprecated = True
            elif rel.relation == "deprecated_in":
                has_deprecated = True
                
        if has_breaking:
            return "at_risk"
        if has_deprecated:
            return "deprecated"
            
        return "healthy"
        
    def _calculate_version_distance(self, installed: str, latest: str, relationships: List[SymbolRelationship]) -> VersionDistance:
        v_inst = parse_version(installed)
        v_latest = parse_version(latest)
        
        maj_diff, min_diff, pat_diff = 0, 0, 0
        if v_inst and v_latest and hasattr(v_inst, 'major') and hasattr(v_latest, 'major'):
            maj_diff = max(0, v_latest.major - v_inst.major)
            if v_latest.major == v_inst.major:
                min_diff = max(0, v_latest.minor - v_inst.minor)
                if v_latest.minor == v_inst.minor:
                    pat_diff = max(0, v_latest.micro - v_inst.micro)
            else:
                min_diff = v_latest.minor
                pat_diff = v_latest.micro
                
        dep_in = None
        rem_in = None
        for rel in relationships:
            if rel.relation == "deprecated_in":
                dep_in = rel.target
            elif rel.relation == "removed_in":
                rem_in = rel.target
                
        return VersionDistance(
            installed=installed,
            latest=latest,
            deprecated_in=dep_in,
            removed_in=rem_in,
            major_diff=maj_diff,
            minor_diff=min_diff,
            patch_diff=pat_diff
        )
