import ast
import re


class ValidationResult:
    def __init__(self):
        self.valid = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.syntax_valid = False
        self.ast_valid = False
        self.imports_resolved = True
        self.no_empty_files = True
        self.no_truncated = True
        self.no_unexpected_deletions = True
        self.has_changed = False

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "syntax_valid": self.syntax_valid,
            "ast_valid": self.ast_valid,
            "imports_resolved": self.imports_resolved,
            "no_empty_files": self.no_empty_files,
            "no_truncated": self.no_truncated,
            "no_unexpected_deletions": self.no_unexpected_deletions,
            "has_changed": self.has_changed,
        }


def validate_patch(original_code: str, modified_code: str) -> ValidationResult:
    result = ValidationResult()

    if not modified_code or not modified_code.strip():
        result.errors.append("Modified code is empty")
        result.no_empty_files = False
        result.valid = False
        return result

    if modified_code.strip() == original_code.strip():
        result.warnings.append("No changes made to file")

    try:
        ast.parse(modified_code)
        result.syntax_valid = True
        result.ast_valid = True
    except SyntaxError as e:
        result.errors.append(f"Python syntax error: {e}")
        result.valid = False
        return result

    _validate_no_truncation(modified_code, result)
    _validate_imports(modified_code, result)

    if result.errors:
        result.valid = False

    return result


def _validate_no_truncation(code: str, result: ValidationResult):
    lines = code.split("\n")
    truncation_patterns = [
        r"\.\.\.\s*$",
        r"#\s*\.\.\.\s*$",
        r"/\*\s*\.\.\.\s*\*/",
        r"<!--\s*\.\.\.\s*-->",
    ]
    for i, line in enumerate(lines):
        for pattern in truncation_patterns:
            if re.search(pattern, line.strip()):
                result.errors.append(f"Possible truncation at line {i+1}: '{line.strip()}'")
                result.no_truncated = False
                return

    if len(lines) > 3 and all(not l.strip() for l in lines[-2:]):
        if lines[-3].strip() and not lines[-3].strip().endswith(("}", ")", "]", "'", '"')):
            result.warnings.append("File may be truncated (ends with blank lines)")


def _validate_imports(code: str, result: ValidationResult):
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name or not alias.name.replace(".", "").isidentifier():
                        result.warnings.append(f"Suspicious import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if not node.module or not node.module.replace(".", "").isidentifier():
                    result.warnings.append(f"Suspicious from-import: {node.module}")
    except SyntaxError:
        pass
