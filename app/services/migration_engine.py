from __future__ import annotations

import logging
from typing import Any

from app.knowledge.repository import KnowledgeRepository
from app.discovery.web_search import generate_search_queries, serper_search, rank_sources
from app.discovery.document_extractor import fetch_page, extract_relevant_sections
from app.discovery.regex_extractor import extract_relationships_regex
from app.discovery.llm_extractor import extract_relationships_groq
from app.discovery.validation import validate_relationship
from app.services.version_resolver import resolve_library_metadata

logger = logging.getLogger(__name__)

def _deduplicate_relationships(rels: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    METHOD_RANK = {"regex": 2, "groq": 1}
    for rel in rels:
        key = (rel.get("from"), rel.get("relation"), rel.get("to"))
        existing = best.get(key)
        if existing is None:
            best[key] = rel
        else:
            # Higher confidence wins; on tie, higher method rank wins
            new_score = (rel.get("confidence", 0), METHOD_RANK.get(rel.get("extraction_method"), 0))
            old_score = (existing.get("confidence", 0), METHOD_RANK.get(existing.get("extraction_method"), 0))
            if new_score > old_score:
                best[key] = rel
    return list(best.values())

class MigrationEngine:
    def __init__(self, knowledge_repository: KnowledgeRepository) -> None:
        self.knowledge_repository = knowledge_repository

    def _store_relationship(self, rel: dict, url: str, snippets: list[str], known_relationships: list[dict], library: str, debug_trace: dict | None) -> None:
        existing_rel = next((r for r in known_relationships if r["to"] == rel.get("to") and r["relation"] == rel.get("relation")), None)
        if existing_rel:
            updated_rel = self.knowledge_repository.increment_supporting_sources(existing_rel["_id"])
            if updated_rel:
                rel["status"] = updated_rel.get("status", "candidate")
            self.knowledge_repository.insert_evidence(
                relationship_id=existing_rel["_id"], url=url, source_type="discovery", snippet=snippets[0] if snippets else ""
            )
        else:
            rel_id = self.knowledge_repository.insert_relationship(
                from_sym=rel.get("from"), relation=rel.get("relation"), to_sym=rel.get("to"), confidence=rel.get("confidence", 1.0), library=library
            )
            rel["status"] = "candidate"
            self.knowledge_repository.insert_evidence(
                relationship_id=rel_id, url=url, source_type="discovery", snippet=snippets[0] if snippets else ""
            )
            if debug_trace:
                debug_trace["storage_action"] = "candidate_created"
            known_relationships.append({"_id": rel_id, "to": rel.get("to"), "relation": rel.get("relation"), "status": "candidate"})

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
                "regex_used": False,
                "groq_used": False,
                "skip_reason": None,
                "regex_relationships": [],
                "groq_relationships": [],
                "deduplicated_relationships": [],
                "validation_results": [],
                "rejected_relationships": [],
                "storage_action": None
            } if debug else None

            # Step 2: Discovery Mode (Search)
            queries = generate_search_queries(symbol, library)
            if debug: debug_trace["queries"] = queries
            search_results = serper_search(queries)
            if debug: debug_trace["raw_results_count"] = len(search_results)
            
            ranked_results = rank_sources(search_results)
            if debug: debug_trace["ranked_results"] = [{"title": r.get("title"), "url": r.get("url"), "score": r.get("score")} for r in ranked_results]
            
            # Step 3 & 4: Fetch pages and extraction
            
            # PHASE 1: Regex Extraction
            # We process pages until we find a validated regex relationship.
            found_valid_regex = False
            page_data_cache = [] # Cache pages we fetch in case we need Groq fallback
            
            for result in ranked_results:
                url = result.get("url")
                if not url: continue
                if debug: debug_trace["urls_fetched"].append(url)
                
                page_text = fetch_page(url)
                if not page_text: continue
                
                snippets = extract_relevant_sections(page_text, symbol)
                if not snippets: continue
                if debug: debug_trace["snippets_extracted"].extend(snippets)
                
                # Cache for groq just in case
                page_data_cache.append({"url": url, "page_text": page_text, "snippets": snippets})
                
                regex_rels = extract_relationships_regex(symbol, library, snippets)
                if regex_rels:
                    if debug:
                        debug_trace["regex_used"] = True
                        debug_trace["regex_relationships"].extend(regex_rels)
                        debug_trace["relationships_extracted"].extend(regex_rels)
                        
                    deduped = _deduplicate_relationships(regex_rels)
                    if debug: debug_trace["deduplicated_relationships"].extend(deduped)
                    
                    for rel in deduped:
                        is_valid, rejection_reason = validate_relationship(rel, page_text)
                        if debug: 
                            debug_trace["validation_results"].append({"relationship": rel, "valid": is_valid})
                            if not is_valid:
                                debug_trace["rejected_relationships"].append({"relationship": rel, "reason": rejection_reason})
                        
                        if is_valid:
                            self._store_relationship(rel, url, snippets, known_relationships, library, debug_trace)
                            found_valid_regex = True
                            
                # If regex found valid relationships on this page, we STOP entirely.
                if found_valid_regex:
                    if debug: debug_trace["skip_reason"] = "regex_relationship_found"
                    break
                    
            # PHASE 2: Groq Fallback
            if not found_valid_regex:
                if debug: debug_trace["groq_used"] = True
                
                all_snippets = [s for page in page_data_cache for s in page["snippets"]]
                if all_snippets:
                    groq_rels = extract_relationships_groq(symbol, library, all_snippets, ranked_results)
                    if groq_rels:
                        if debug:
                            debug_trace["groq_relationships"].extend(groq_rels)
                            debug_trace["relationships_extracted"].extend(groq_rels)
                            
                        deduped = _deduplicate_relationships(groq_rels)
                        if debug: debug_trace["deduplicated_relationships"].extend(deduped)
                        
                        fallback_page = page_data_cache[0] if page_data_cache else None
                        if fallback_page:
                            for rel in deduped:
                                is_valid, rejection_reason = validate_relationship(rel, fallback_page["page_text"])
                                if debug:
                                    debug_trace["validation_results"].append({"relationship": rel, "valid": is_valid})
                                    if not is_valid:
                                        debug_trace["rejected_relationships"].append({"relationship": rel, "reason": rejection_reason})
                                        
                                if is_valid:
                                    self._store_relationship(rel, fallback_page["url"], fallback_page["snippets"], known_relationships, library, debug_trace)

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
