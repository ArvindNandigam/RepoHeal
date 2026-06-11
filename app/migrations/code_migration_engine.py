from typing import Any

from app.config import settings
from app.llm.base import LLMConfig, BaseLLMProvider
from app.llm.providers import create_llm_provider
from app.llm.context_builder import build_migration_context, MigrationContext
from app.llm.patch_generator import LLMPatchGenerator, PatchResult
from app.llm.validator import validate_patch, ValidationResult
from app.llm.confidence import calculate_overall_confidence, ConfidenceLevel
from app.migrations.classifier import classify_recommendation, MigrationClass
from app.migrations.ast_transforms import apply_deterministic_transform
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_FILES_PER_PATCH = getattr(settings, "MAX_FILES_PER_PATCH", 10)
MAX_LINES_PER_PATCH = getattr(settings, "MAX_LINES_PER_PATCH", 500)
MAX_TOKENS_PER_REQUEST = getattr(settings, "MAX_TOKENS_PER_REQUEST", 4096)
ENABLE_LLM_PATCHING = getattr(settings, "ENABLE_LLM_PATCHING", True)
AST_FIRST_RISK_THRESHOLD = getattr(settings, "AST_FIRST_RISK_THRESHOLD", 85)
AUTO_PR_RISK_THRESHOLD = getattr(settings, "AUTO_PR_RISK_THRESHOLD", 85)
DRAFT_PR_RISK_THRESHOLD = getattr(settings, "DRAFT_PR_RISK_THRESHOLD", 85)


class PatchPlan:
    def __init__(
        self,
        migration_class: MigrationClass,
        symbol: str,
        library: str,
        file_path: str,
        original_code: str,
        modified_code: str | None = None,
        explanation: str = "",
        confidence: float = 0.0,
        llm_confidence: float = 0.0,
        validation: ValidationResult | None = None,
        risk_score: float = 50.0,
        confidence_level: ConfidenceLevel = ConfidenceLevel.LOW,
    ):
        self.migration_class = migration_class
        self.symbol = symbol
        self.library = library
        self.file_path = file_path
        self.original_code = original_code
        self.modified_code = modified_code
        self.explanation = explanation
        self.confidence = confidence
        self.llm_confidence = llm_confidence
        self.validation = validation
        self.risk_score = risk_score
        self.confidence_level = confidence_level

    @property
    def valid(self) -> bool:
        return self.validation is not None and self.validation.valid

    def to_dict(self) -> dict:
        return {
            "migration_class": self.migration_class.value,
            "symbol": self.symbol,
            "library": self.library,
            "file_path": self.file_path,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "llm_confidence": self.llm_confidence,
            "risk_score": self.risk_score,
            "confidence_level": self.confidence_level.value if self.confidence_level else "LOW",
            "valid": self.valid,
            "validation": self.validation.to_dict() if self.validation else None,
            "has_changes": (self.modified_code or "").strip() != (self.original_code or "").strip(),
        }


class CodeMigrationEngine:
    def __init__(self, repo_id: str, analysis: dict[str, Any], file_contents: dict[str, str] | None = None):
        self.repo_id = repo_id
        self.analysis = analysis
        self.file_contents = file_contents or {}
        self.plans: list[PatchPlan] = []

    async def process_recommendations(self, recommendations: list[dict[str, Any]]) -> list[PatchPlan]:
        if not ENABLE_LLM_PATCHING:
            logger.info("LLM patching is disabled by configuration")
            return []

        if not recommendations:
            return []

        max_risk = max((r.get("risk_score", 50) for r in recommendations), default=50)

        # TWO-PASS strategy:
        # Pass 1: AST-first for ALL symbols (if risk < threshold)
        #         Every AST result is verified by Groq
        # Pass 2: Groq handles what AST couldn't + safety check
        #         Runs on ALL affected nodes to ensure no breakage

        # PASS 1: AST-first for every recommendation
        do_ast_first = max_risk < AST_FIRST_RISK_THRESHOLD
        ast_successes = set()
        pass1_plans = []

        for rec in recommendations:
            symbol = rec.get("symbol", "")
            risk_score = rec.get("risk_score", 50)
            replacement = rec.get("replacement", "")
            action_type = rec.get("action_type", "")

            file_path = self._find_affected_file(symbol)
            original_code = self._get_file_content(file_path)
            if not original_code:
                logger.warning(f"No source found for {symbol} in {self.repo_id}")
                continue

            if do_ast_first and (action_type or replacement):
                # Try AST transform first
                ast_plan = self._try_ast_transform(rec, file_path, original_code, symbol, risk_score)
                if ast_plan and ast_plan.valid:
                    # AST succeeded — Groq verifies the patch
                    verified = await self._groq_verify(symbol, original_code, ast_plan.modified_code)
                    if verified:
                        ast_plan.llm_confidence = max(ast_plan.llm_confidence, 0.85)
                        ast_plan.confidence_level = ConfidenceLevel.HIGH
                        ast_plan.explanation += " | Verified by Groq"
                        ast_successes.add(symbol)
                        pass1_plans.append(ast_plan)
                        self.plans.append(ast_plan)
                        logger.info("AST-first success for %s (risk=%s, verified by Groq)", symbol, risk_score)
                        continue

            # Fall through: mark for Pass 2 (Groq)
            mc = classify_recommendation(action_type, description=rec.get("description", ""), library=rec.get("library", ""), confidence=rec.get("confidence", 0))
            pass1_plans.append(("groq_pass2", mc, rec, file_path, original_code))

        # PASS 2: Groq handles remaining + safety pass
        recs_for_groq = [p for p in pass1_plans if isinstance(p, tuple)]
        patched_files = {}

        for tag, mc, rec, file_path, original_code in recs_for_groq:
            symbol = rec.get("symbol", "")
            replacement = rec.get("replacement", "")
            risk_score = rec.get("risk_score", 50)

            # Include all prior AST results & the current file as context for Groq
            file_map = {fp: self._get_file_content(fp) for fp in self._all_affected_files()}
            for fp, code in patched_files.items():
                file_map[fp] = code

            plan = await self._groq_patch_with_safety(
                rec, file_path, original_code,
                file_map, ast_successes,
            )
            if plan:
                patched_files[file_path] = plan.modified_code or original_code
                self.plans.append(plan)

        logger.info("Two-pass migration: AST-first=%s, AST-successes=%d, total-plans=%d",
                     do_ast_first, len(ast_successes), len(self.plans))
        return self.plans

    def _try_ast_transform(self, rec: dict, file_path: str, original_code: str, symbol: str, risk_score: float) -> PatchPlan | None:
        """Try a deterministic AST transform for a symbol replacement."""
        replacement = rec.get("replacement", "")
        action_type = rec.get("action_type", "")

        if not replacement and not action_type:
            return None

        # Build action_type and params from the relationship
        if replacement and not action_type:
            action_type = "rename_symbol"

        if action_type == "rewrite_import":
            params = {"old_module": symbol, "new_module": replacement}
        elif action_type == "rename_symbol":
            old_name = symbol.split(".")[-1]
            new_name = replacement.split(".")[-1] if replacement else ""
            params = {"old_name": old_name, "new_name": new_name}
        elif action_type == "update_api_signature":
            params = {"func_name": symbol, "param_changes": rec.get("param_changes", {})}
        else:
            return None

        try:
            modified = apply_deterministic_transform(original_code, action_type, params)
        except Exception:
            return None

        if modified == original_code:
            return None

        validation = validate_patch(original_code, modified)
        if not validation.valid:
            return None

        return PatchPlan(
            migration_class=MigrationClass.SAFE_AST,
            symbol=symbol, library=rec.get("library", ""),
            file_path=file_path,
            original_code=original_code, modified_code=modified,
            explanation=f"AST transform: {action_type} ({symbol} → {replacement})",
            confidence=rec.get("confidence", 0.8),
            llm_confidence=0.7,
            validation=validation,
            risk_score=risk_score,
            confidence_level=ConfidenceLevel.MEDIUM,
        )

    async def _groq_verify(self, symbol: str, original: str, modified: str) -> bool:
        """Ask Groq to verify an AST-generated patch is correct."""
        from app.llm.providers import create_llm_provider
        config = LLMConfig()
        provider = create_llm_provider(config)
        try:
            prompt = (
                f"Verify this code change for symbol '{symbol}' is correct and does not introduce bugs.\n\n"
                f"BEFORE:\n{original}\n\nAFTER:\n{modified}\n\n"
                "Respond with JSON: {\"correct\": true/false, \"reason\": \"...\"}"
            )
            result = await provider.complete(prompt, response_format={"type": "json_object"})
            if result and isinstance(result, dict):
                return result.get("correct", False)
            return False
        except Exception:
            return False
        finally:
            await provider.close()

    async def _groq_patch_with_safety(
        self, rec: dict, file_path: str, original_code: str,
        all_file_map: dict[str, str], already_fixed: set[str],
    ) -> PatchPlan | None:
        """Groq patches a remaining item with full context + safety check."""
        config = LLMConfig()
        provider = create_llm_provider(config)
        try:
            context = MigrationContext(
                repository=self.repo_id,
                library=rec.get("library", ""),
                current_version=rec.get("installed_version", ""),
                target_version=rec.get("latest_version", ""),
                symbol=rec.get("symbol", ""),
                replacement=rec.get("replacement", ""),
                affected_files=[{"path": fp, "content": code} for fp, code in all_file_map.items()],
                confidence=rec.get("confidence", 0.5),
                risk_score=rec.get("risk_score", 50),
                recommendation=rec,
            )
            context.already_fixed = sorted(already_fixed)

            generator = LLMPatchGenerator(provider)
            patch = await generator.generate_patch(context)
            validation = validate_patch(original_code, patch.modified_code)
            llm_conf = patch.confidence
            overall = calculate_overall_confidence(
                rec.get("confidence", 0.5), llm_conf, validation,
                rec.get("risk_score", 50), len(all_file_map)
            )
            return PatchPlan(
                migration_class=MigrationClass.LLM_CANDIDATE,
                symbol=rec.get("symbol", ""),
                library=rec.get("library", ""),
                file_path=file_path,
                original_code=original_code,
                modified_code=patch.modified_code if validation.valid else None,
                explanation=patch.explanation,
                confidence=rec.get("confidence", 0.5),
                llm_confidence=llm_conf,
                validation=validation,
                risk_score=rec.get("risk_score", 50),
                confidence_level=overall,
            )
        except Exception as e:
            logger.error("Groq patch+safety failed for %s: %s", rec.get("symbol", ""), e)
            mc = classify_recommendation(rec.get("action_type", ""), rec.get("description", ""), rec.get("library", ""), rec.get("confidence", 0))
            return PatchPlan(mc, rec.get("symbol", ""), rec.get("library", ""), file_path, original_code, risk_score=rec.get("risk_score", 50))
        finally:
            await provider.close()

    def _all_affected_files(self) -> set[str]:
        """Return all file paths that contain API calls or function definitions."""
        sem_graph = self.analysis.get("semantic_graph", {})
        files = sem_graph.get("files", {})
        return set(files.keys()) | set(self.file_contents.keys())

    async def _process_single(self, rec: dict[str, Any]) -> PatchPlan | None:
        """Legacy single-pass processor — kept for backward compat."""
        action_type = rec.get("action_type", "")
        description = rec.get("description", "")
        library = rec.get("library", "")
        confidence = rec.get("confidence", 0.0)
        risk_score = rec.get("risk_score", 50)
        symbol = rec.get("symbol", "")

        mc = classify_recommendation(action_type, description, library, confidence)

        if mc == MigrationClass.MANUAL_REQUIRED:
            return PatchPlan(mc, symbol, library, "", "", risk_score=risk_score)

        file_path = self._find_affected_file(symbol)
        original_code = self._get_file_content(file_path)
        if not original_code:
            logger.warning(f"No source found for {symbol} in {self.repo_id}")
            return PatchPlan(mc, symbol, library, "", "", risk_score=risk_score)

        if mc == MigrationClass.SAFE_AST:
            return self._apply_safe_ast(rec, file_path, original_code, symbol, library, risk_score)

        return await self._apply_llm_patch(rec, file_path, original_code, symbol, library, confidence, risk_score, mc)

    def _apply_safe_ast(
        self, rec: dict, file_path: str, original_code: str, symbol: str, library: str, risk_score: float
    ) -> PatchPlan:
        action_type = rec.get("action_type", "")
        if action_type == "rewrite_import":
            params = {"old_module": rec.get("symbol", ""), "new_module": rec.get("replacement", "")}
        elif action_type == "rename_symbol":
            params = {"old_name": rec.get("symbol", ""), "new_name": rec.get("replacement", "")}
        elif action_type == "update_api_signature":
            params = {"func_name": rec.get("symbol", ""), "param_changes": rec.get("param_changes", {})}
        else:
            return PatchPlan(MigrationClass.MANUAL_REQUIRED, symbol, library, file_path, original_code, risk_score=risk_score)

        try:
            modified = apply_deterministic_transform(original_code, action_type, params)
        except Exception as e:
            logger.warning(f"AST transform failed for {symbol}: {e}")
            return PatchPlan(MigrationClass.MANUAL_REQUIRED, symbol, library, file_path, original_code, risk_score=risk_score)

        validation = validate_patch(original_code, modified)
        confidence_level = calculate_overall_confidence(
            rec.get("confidence", 0.8), 1.0, validation, risk_score, 1
        )

        return PatchPlan(
            migration_class=MigrationClass.SAFE_AST,
            symbol=symbol, library=library, file_path=file_path,
            original_code=original_code, modified_code=modified,
            explanation=f"Applied deterministic {action_type} transform",
            confidence=rec.get("confidence", 0.8),
            llm_confidence=1.0,
            validation=validation,
            risk_score=risk_score,
            confidence_level=confidence_level,
        )

    async def _apply_llm_patch(
        self, rec: dict, file_path: str, original_code: str,
        symbol: str, library: str, confidence: float, risk_score: float,
        mc: MigrationClass,
    ) -> PatchPlan:
        config = LLMConfig()
        provider = create_llm_provider(config)
        try:
            affected_files = [{"path": file_path, "content": original_code}]
            context = MigrationContext(
                repository=self.repo_id, library=library,
                current_version=rec.get("installed_version", ""),
                target_version=rec.get("latest_version", ""),
                symbol=symbol, replacement=rec.get("replacement", ""),
                affected_files=affected_files,
                confidence=confidence, risk_score=risk_score,
                recommendation=rec,
            )
            generator = LLMPatchGenerator(provider)
            patch = await generator.generate_patch(context)
            validation = validate_patch(original_code, patch.modified_code)
            llm_conf = patch.confidence
            overall = calculate_overall_confidence(confidence, llm_conf, validation, risk_score, len(affected_files))
            return PatchPlan(
                migration_class=mc, symbol=symbol, library=library,
                file_path=file_path, original_code=original_code,
                modified_code=patch.modified_code if validation.valid else None,
                explanation=patch.explanation,
                confidence=confidence, llm_confidence=llm_conf,
                validation=validation, risk_score=risk_score,
                confidence_level=overall,
            )
        except Exception as e:
            logger.error(f"LLM patch generation failed for {symbol}: {e}")
            return PatchPlan(mc, symbol, library, file_path, original_code, risk_score=risk_score)
        finally:
            await provider.close()

    def _find_affected_file(self, symbol: str) -> str:
        sem_graph = self.analysis.get("semantic_graph", {})
        files = sem_graph.get("files", {})
        candidates = []
        for fpath, finfo in files.items():
            for call in finfo.get("calls", []):
                if symbol in call.get("name", ""):
                    candidates.append((fpath, 0))
            for api in finfo.get("apis", []):
                if symbol in api.get("name", ""):
                    candidates.append((fpath, 1))
        if candidates:
            candidates.sort(key=lambda x: x[1])
            return candidates[0][0]
        imports = self.analysis.get("imports", {})
        for fpath in imports.get("files", {}):
            return fpath
        return ""

    def _get_file_content(self, file_path: str) -> str:
        if file_path in self.file_contents:
            return self.file_contents[file_path]
        sem_graph = self.analysis.get("semantic_graph", {})
        files = sem_graph.get("files", {})
        finfo = files.get(file_path, {})
        return finfo.get("source", "")


def classify_patches_by_risk(plans: list[PatchPlan]) -> dict[str, list[PatchPlan]]:
    auto_pr = []
    draft_pr = []
    report_only = []

    for plan in plans:
        if not plan.modified_code or not plan.valid:
            report_only.append(plan)
            continue
        # Risk < 85 → auto-merge. Risk >= 85 → draft PR for human review.
        if plan.risk_score < AUTO_PR_RISK_THRESHOLD:
            auto_pr.append(plan)
        else:
            draft_pr.append(plan)

    return {"auto_pr": auto_pr, "draft_pr": draft_pr, "report_only": report_only}
