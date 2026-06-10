import json
import re
from app.llm.base import BaseLLMProvider
from app.llm.context_builder import MigrationContext
from app.utils.logger import get_logger

logger = get_logger(__name__)

MIGRATION_PROMPT_TEMPLATE = """You are generating a migration patch for a Python codebase.

Requirements:
- Preserve original behavior.
- Update deprecated APIs to their recommended replacements.
- Minimize code changes — only change what is necessary.
- Return only valid, complete Python code.
- Explain each change.
- Identify any uncertainties.

Migration Guidance:
Library: {library}
Current Version: {current_version}
Target Version: {target_version}
Symbol: {symbol}
Replacement: {replacement}

Affected Files:
{affected_code}

Return a JSON object with these fields:
{{
  "explanation": "step-by-step explanation of changes",
  "confidence": 0.0-1.0,
  "modified_code": "the complete modified file content"
}}
"""


class PatchResult:
    def __init__(self, file_path: str, explanation: str, confidence: float, modified_code: str):
        self.file_path = file_path
        self.explanation = explanation
        self.confidence = confidence
        self.modified_code = modified_code

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "modified_code": self.modified_code,
        }


class LLMPatchGenerator:
    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider

    async def generate_patch(self, context: MigrationContext) -> PatchResult:
        context_dict = context.to_dict()
        affected_code = ""
        for f in context_dict.get("affected_files", []):
            header = f"--- {f['path']} (lines {f.get('start_line', 1)}-{f.get('end_line', 1)}) ---"
            affected_code += f"\n{header}\n{f.get('code', '')}\n"

        prompt = MIGRATION_PROMPT_TEMPLATE.format(
            library=context.library,
            current_version=context.current_version,
            target_version=context.target_version,
            symbol=context.symbol,
            replacement=context.replacement,
            affected_code=affected_code,
        )

        raw = await self.provider.generate(prompt, max_tokens=4096)
        return self._parse_response(raw, context)

    def _parse_response(self, raw: str, context: MigrationContext) -> PatchResult:
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                data = self._fallback_parse(raw)
        else:
            data = self._fallback_parse(raw)

        first_file = context.affected_files[0] if context.affected_files else {"path": "unknown.py"}
        return PatchResult(
            file_path=data.get("file_path", first_file.get("path", "unknown.py")),
            explanation=data.get("explanation", raw[:500]),
            confidence=float(data.get("confidence", 0.5)),
            modified_code=data.get("modified_code", raw),
        )

    def _fallback_parse(self, raw: str) -> dict:
        lines = raw.strip().split("\n")
        code_lines = []
        in_code = False
        for line in lines:
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                code_lines.append(line)
        modified = "\n".join(code_lines) if code_lines else raw
        return {
            "explanation": raw[:300],
            "confidence": 0.5,
            "modified_code": modified,
        }
