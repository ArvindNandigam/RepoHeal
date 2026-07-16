from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.knowledge_base import add_to_knowledge_base
from app.discovery.web_search import generate_search_queries, serper_search, rank_sources
from app.discovery.document_extractor import fetch_page, extract_relevant_sections
from app.discovery.regex_extractor import extract_relationships_regex
from app.discovery.llm_extractor import extract_relationships_groq_batch
from app.discovery.fallback_extractor import extract_relationships_fallback
from app.discovery.validation import validate_relationship
from app.services.version_resolver import resolve_library_metadata

logger = logging.getLogger(__name__)

def _deduplicate_relationships(rels: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    METHOD_RANK = {"regex": 2, "groq": 1, "fallback": 3}
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
            if rel_id:
                self.knowledge_repository.insert_evidence(
                    relationship_id=rel_id, url=url, source_type="discovery", snippet=snippets[0] if snippets else ""
                )
                if debug_trace:
                    debug_trace["storage_action"] = "candidate_created"
                known_relationships.append({"_id": rel_id, "to": rel.get("to"), "relation": rel.get("relation"), "status": "candidate"})

    def resolve(self, library: str, symbols: list[str], debug: bool = False) -> dict[str, Any]:
        """
        Main entry point for discovery.
        """
        logger.info("Resolving %d symbols for %s", len(symbols), library)

        _overall_budget_exhausted = False
        results: list[dict] = []
        
        # Determine library context
        library_record = self.knowledge_repository.lookup_library(library)
        if not library_record:
            meta = resolve_library_metadata(library)
            if meta:
                self.knowledge_repository.upsert_library(
                    library=library,
                    latest_version=meta.get("latest_version"),
                    official_docs=meta.get("official_docs"),
                    github_repo=meta.get("github_repo"),
                    pypi_url=meta.get("pypi_url")
                )
                latest_version = meta.get("latest_version")
            else:
                self.knowledge_repository.upsert_library(library=library)
                latest_version = None
        else:
            latest_version = library_record.get("latest_version")

        groq_pending = []
        symbol_data_map = {}

        # PHASE 1 & 2: Search, Regex, Fallback
        for symbol in symbols:
            # Step 1: Check knowledge base (Level 1 + 2)
            known_relationships = self.knowledge_repository.lookup_relationships(symbol)
            if known_relationships:
                # Refresh cache timestamp
                for rel in known_relationships:
                    self.knowledge_repository.increment_supporting_sources(rel["_id"])
                
                results.append({
                    "symbol": symbol,
                    "known": True,
                    "relationships": known_relationships,
                    "_debug": {"cached": True} if debug else None
                })
                continue
            
            debug_trace = {
                "queries": [],
                "urls_fetched": [],
                "raw_results_count": 0,
                "snippets_extracted": [],
                "regex_used": False,
                "regex_relationships": [],
                "fallback_used": False,
                "fallback_relationships": [],
                "groq_used": False,
                "groq_relationships": [],
                "relationships_extracted": [],
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
            
            page_data_cache = []
            for result in ranked_results:
                url = result.get("url")
                if not url: continue
                if debug: debug_trace["urls_fetched"].append(url)
                
                page_text = fetch_page(url)
                if not page_text: continue
                
                snippets = extract_relevant_sections(page_text, symbol)
                if not snippets: continue
                if debug: debug_trace["snippets_extracted"].extend(snippets)
                
                page_data_cache.append({"url": url, "page_text": page_text, "snippets": snippets})

            fallback_rels = extract_relationships_fallback(symbol, library)
            
            if not page_data_cache:
                if debug: debug_trace["skip_reason"] = "no_page_content"
                if fallback_rels:
                    if debug:
                        debug_trace["fallback_used"] = True
                        debug_trace["fallback_relationships"].extend(fallback_rels)
                        debug_trace["relationships_extracted"].extend(fallback_rels)
                    for rel in fallback_rels:
                        rel_id = self.knowledge_repository.insert_relationship(
                            from_sym=rel.get("from"), relation=rel.get("relation"), to_sym=rel.get("to"),
                            confidence=rel.get("confidence", 1.0), library=library
                        )
                        rel["status"] = "candidate"
                        if rel_id:
                            known_relationships.append({"_id": rel_id, "to": rel.get("to"), "relation": rel.get("relation"), "status": "candidate"})
                self.knowledge_repository.insert_symbol(symbol, library)
                final_relationships = self.knowledge_repository.lookup_relationships(symbol)
                results.append({
                    "symbol": symbol,
                    "known": bool(final_relationships),
                    "relationships": final_relationships,
                    "_debug": debug_trace
                })
                continue

            all_rels = []
            
            if debug: debug_trace["regex_used"] = True
            for page_data in page_data_cache:
                regex_rels = extract_relationships_regex(symbol, library, page_data["snippets"])
                if regex_rels:
                    if debug:
                        debug_trace["regex_relationships"].extend(regex_rels)
                        debug_trace["relationships_extracted"].extend(regex_rels)
                    all_rels.extend(regex_rels)

            if fallback_rels:
                if debug:
                    debug_trace["fallback_used"] = True
                    debug_trace["fallback_relationships"].extend(fallback_rels)
                    debug_trace["relationships_extracted"].extend(fallback_rels)
                all_rels.extend(fallback_rels)

            symbol_data_map[symbol] = {
                "all_rels": all_rels,
                "page_data_cache": page_data_cache,
                "debug_trace": debug_trace,
                "known_relationships": known_relationships,
                "ranked_results": ranked_results
            }

            if not all_rels:
                all_snippets = [s for page in page_data_cache for s in page["snippets"]]
                groq_pending.append({
                    "symbol": symbol,
                    "snippets": all_snippets,
                    "source_context": ranked_results
                })

        # PHASE 3: Groq Batching
        groq_results = {}
        if groq_pending:
            logger.info("Batching %d symbols to Groq for %s", len(groq_pending), library)
            groq_results, groq_budget_exhausted = extract_relationships_groq_batch(library, groq_pending)
            if groq_budget_exhausted:
                _overall_budget_exhausted = True

        # PHASE 4: Merge, Deduplicate, Validate, Store
        for symbol, data in symbol_data_map.items():
            all_rels = data["all_rels"]
            page_data_cache = data["page_data_cache"]
            debug_trace = data["debug_trace"]
            known_relationships = data["known_relationships"]

            # Merge Groq
            if symbol in groq_results:
                groq_rels = groq_results[symbol]
                if debug_trace:
                    debug_trace["groq_used"] = True
                    debug_trace["groq_relationships"].extend(groq_rels)
                    debug_trace["relationships_extracted"].extend(groq_rels)
                all_rels.extend(groq_rels)
                for rel in groq_rels:
                    add_to_knowledge_base(
                        library=library,
                        symbol=rel.get("from", symbol),
                        entry={
                            "to": rel.get("to", ""),
                            "relation": rel.get("relation", "deprecated_in_favor_of"),
                            "confidence": rel.get("confidence", 0.9),
                            "source": "groq",
                            "first_seen": datetime.now(timezone.utc).date().isoformat(),
                        }
                    )

            if all_rels:
                deduped = _deduplicate_relationships(all_rels)
                if debug_trace: debug_trace["deduplicated_relationships"] = deduped
                
                for rel in deduped:
                    rel_from = rel.get("from", "")
                    if rel_from and rel_from != symbol:
                        rel_from_tail = rel_from.split(".")[-1] if "." in rel_from else rel_from
                        symbol_tail = symbol.split(".")[-1]
                        if rel_from_tail == symbol_tail:
                            rel["from"] = symbol
                            
                    evidence_page = page_data_cache[0]
                    for page_data in page_data_cache:
                        page_text_lower = page_data["page_text"].lower()
                        if (rel.get("to", "").lower() in page_text_lower or 
                            rel.get("from", "").lower() in page_text_lower):
                            evidence_page = page_data
                            break
                    
                    is_valid, rejection_reason = validate_relationship(rel, evidence_page["page_text"])
                    if debug_trace:
                        debug_trace["validation_results"].append({"relationship": rel, "valid": is_valid})
                        if not is_valid:
                            debug_trace["rejected_relationships"].append({"relationship": rel, "reason": rejection_reason})
                    
                    if is_valid:
                        self._store_relationship(rel, evidence_page["url"], evidence_page["snippets"], known_relationships, library, debug_trace)

            self.knowledge_repository.insert_symbol(symbol, library)
            final_relationships = self.knowledge_repository.lookup_relationships(symbol)
            
            results.append({
                "symbol": symbol,
                "known": bool(final_relationships),
                "relationships": final_relationships,
                "_debug": debug_trace
            })
            
        intelligence_status = "degraded" if _overall_budget_exhausted else "ok"
        intelligence_reason = "budget_exhausted" if _overall_budget_exhausted else None

        return {
            "library": library,
            "latest_version": latest_version,
            "intelligence_status": intelligence_status,
            "intelligence_reason": intelligence_reason,
            "results": results
        }
