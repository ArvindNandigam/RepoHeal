from __future__ import annotations

import logging
from typing import Any

from app.knowledge.repository import KnowledgeRepository
from app.discovery.web_search import generate_search_queries, serper_search, rank_sources
from app.discovery.document_extractor import fetch_page, extract_relevant_sections
from app.discovery.llm_extractor import extract_relationships
from app.discovery.validation import validate_relationship
from app.services.version_resolver import resolve_library_metadata

logger = logging.getLogger(__name__)

class MigrationEngine:
    def __init__(self, knowledge_repository: KnowledgeRepository) -> None:
        self.knowledge_repository = knowledge_repository

    def resolve(self, library: str, symbols: list[str], debug: bool = False) -> dict[str, Any]:
        """
        For EACH symbol independently:
        1. Mongo lookup (symbols + relationships)
        2. If hit -> return immediately
        3. If miss -> run discovery pipeline
        4. Store discoveries as candidates
        5. If rediscovered -> promote to verified
        """
        
        # 1. Ensure Library Exists
        lib_doc = self.knowledge_repository.lookup_library(library)
        if not lib_doc:
            metadata = resolve_library_metadata(library)
            self.knowledge_repository.upsert_library(
                library=library,
                latest_version=metadata.get("latest_version"),
                official_docs=metadata.get("official_docs"),
                github_repo=metadata.get("github_repo"),
                pypi_url=metadata.get("pypi_url"),
            )
            lib_doc = self.knowledge_repository.lookup_library(library)
            
        latest_version = lib_doc.get("latest_version") if lib_doc else None
        
        results = []
        
        for symbol in symbols:
            # Step 1: Mongo Lookup
            known_symbol = self.knowledge_repository.lookup_symbol(symbol)
            known_relationships = self.knowledge_repository.lookup_relationships(symbol)
            
            if known_symbol:
                # Cache HIT!
                results.append({
                    "symbol": symbol,
                    "known": True,
                    "relationships": known_relationships,
                    "_debug": {"flow": "mongo_hit"} if debug else None
                })
                continue
                
            # Miss: we don't know the symbol — run discovery first, insert after
                
            debug_trace = {
                "flow": "discovery",
                "search_provider": "serper",
                "queries": [],
                "raw_results_count": 0,
                "ranked_results": [],
                "urls_fetched": [],
                "snippets_extracted": [],
                "relationships_extracted": [],
                "validation_results": []
            } if debug else None

            # Step 2: Discovery Mode (Search)
            queries = generate_search_queries(symbol, library)
            if debug: debug_trace["queries"] = queries
            search_results = serper_search(queries)
            if debug: debug_trace["raw_results_count"] = len(search_results)
            
            ranked_results = rank_sources(search_results)
            if debug: debug_trace["ranked_results"] = [{"title": r.get("title"), "url": r.get("url"), "score": r.get("score")} for r in ranked_results]
            
            new_relationships = []
            
            # Step 3 & 4: Fetch pages and LLM extraction
            for result in ranked_results:
                url = result.get("url")
                if not url: continue
                if debug: debug_trace["urls_fetched"].append(url)
                
                page_text = fetch_page(url)
                if not page_text: continue
                
                snippets = extract_relevant_sections(page_text, symbol)
                if not snippets: continue
                if debug: debug_trace["snippets_extracted"].extend(snippets)
                
                extracted_rels = extract_relationships(symbol, library, snippets, ranked_results)
                if debug: debug_trace["relationships_extracted"].extend(extracted_rels)
                
                # Step 5: Validation & Insert
                for rel in extracted_rels:
                    is_valid = validate_relationship(rel, page_text)
                    if debug: debug_trace["validation_results"].append({"relationship": rel, "valid": is_valid})
                    
                    if is_valid:
                        existing_rel = next((r for r in known_relationships if r["to"] == rel.get("to") and r["relation"] == rel.get("relation")), None)
                        if existing_rel:
                            updated_rel = self.knowledge_repository.increment_supporting_sources(existing_rel["_id"])
                            if updated_rel:
                                rel["status"] = updated_rel.get("status", "candidate")
                            
                            self.knowledge_repository.insert_evidence(
                                relationship_id=existing_rel["_id"],
                                url=url,
                                source_type="discovery",
                                snippet=snippets[0] if snippets else ""
                            )
                        else:
                            rel_id = self.knowledge_repository.insert_relationship(
                                from_sym=rel.get("from"),
                                relation=rel.get("relation"),
                                to_sym=rel.get("to"),
                                confidence=rel.get("confidence", 1.0),
                                library=library
                            )
                            rel["status"] = "candidate"
                            
                            self.knowledge_repository.insert_evidence(
                                relationship_id=rel_id,
                                url=url,
                                source_type="discovery",
                                snippet=snippets[0] if snippets else ""
                            )
                            
                            known_relationships.append({"_id": rel_id, "to": rel.get("to"), "relation": rel.get("relation"), "status": "candidate"})
                        
                        new_relationships.append(rel)
                        
            # Discovery completed without crashing — NOW insert the symbol as known
            self.knowledge_repository.insert_symbol(symbol, library)
            
            # Refresh known relationships after discovery
            final_relationships = self.knowledge_repository.lookup_relationships(symbol)
            
            results.append({
                "symbol": symbol,
                "known": bool(final_relationships),
                "relationships": final_relationships,
                "_debug": debug_trace
            })
            
        return {
            "library": library,
            "latest_version": latest_version,
            "results": results
        }
