from __future__ import annotations

import logging
from typing import Any

from app.knowledge.repository import KnowledgeRepository
from app.discovery.web_search import generate_search_queries, search
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
            
            if known_symbol and known_relationships:
                # Cache HIT!
                results.append({
                    "symbol": symbol,
                    "known": True,
                    "relationships": known_relationships,
                    "_debug": {"flow": "mongo_hit"} if debug else None
                })
                continue
                
            # Miss: We know the symbol but no relationships, or we don't know the symbol
            if not known_symbol:
                self.knowledge_repository.insert_symbol(symbol, library)
                
            debug_trace = {
                "flow": "discovery",
                "queries": [],
                "urls_fetched": [],
                "snippets_extracted": [],
                "relationships_extracted": [],
                "validation_results": []
            } if debug else None

            # Step 2: Discovery Mode (Search)
            queries = generate_search_queries(symbol)
            if debug: debug_trace["queries"] = queries
            search_results = search(queries)
            
            new_relationships = []
            
            # Step 3 & 4: Fetch pages and LLM extraction
            for result in search_results:
                url = result.get("href")
                if not url: continue
                if debug: debug_trace["urls_fetched"].append(url)
                
                page_text = fetch_page(url)
                if not page_text: continue
                
                snippets = extract_relevant_sections(page_text, symbol)
                if not snippets: continue
                if debug: debug_trace["snippets_extracted"].extend(snippets)
                
                extracted_rels = extract_relationships(symbol, snippets)
                if debug: debug_trace["relationships_extracted"].extend(extracted_rels)
                
                # Step 5: Validation & Insert
                for rel in extracted_rels:
                    is_valid = validate_relationship(rel, page_text)
                    if debug: debug_trace["validation_results"].append({"relationship": rel, "valid": is_valid})
                    
                    if is_valid:
                        # Insert / Upsert (if Rediscovered -> update timestamp but keep status unless we explicitly promote)
                        # We use find_one_and_update in repo to insert as candidate.
                        rel_id = self.knowledge_repository.insert_relationship(
                            from_sym=rel.get("from"),
                            relation=rel.get("relation"),
                            to_sym=rel.get("to"),
                            confidence=rel.get("confidence", 1.0),
                            library=library
                        )
                        
                        # Check if it was already known and we just rediscovered it -> Promote!
                        existing_rel = next((r for r in known_relationships if r["to"] == rel.get("to") and r["relation"] == rel.get("relation")), None)
                        if existing_rel and existing_rel.get("status") == "candidate":
                            self.knowledge_repository.promote_to_verified(rel_id)
                            rel["status"] = "verified"
                        else:
                            rel["status"] = "candidate"
                            
                        self.knowledge_repository.insert_evidence(
                            relationship_id=rel_id,
                            url=url,
                            source_type="discovery",
                            snippet=snippets[0] if snippets else ""
                        )
                        
                        new_relationships.append(rel)
                        
            # Refresh known relationships after discovery
            final_relationships = self.knowledge_repository.lookup_relationships(symbol)
            
            results.append({
                "symbol": symbol,
                "known": bool(final_relationships), # it's known if we found relationships or if it existed before
                "relationships": final_relationships,
                "_debug": debug_trace
            })
            
        return {
            "library": library,
            "latest_version": latest_version,
            "results": results
        }
