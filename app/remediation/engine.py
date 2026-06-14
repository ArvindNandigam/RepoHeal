import ast
import astor
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class RemediationEngine:
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.tree = ast.parse(source_code)
        self.modified = False

    def rewrite_import(self, old_module: str, new_module: str):
        """Rewrite 'from old_module import ...' to 'from new_module import ...'"""
        class ImportRewriter(ast.NodeTransformer):
            def __init__(self, old, new):
                self.old = old
                self.new = new
                self.modified = False

            def visit_ImportFrom(self, node):
                if node.module == self.old:
                    node.module = self.new
                    self.modified = True
                return node

        rewriter = ImportRewriter(old_module, new_module)
        self.tree = rewriter.visit(self.tree)
        if rewriter.modified:
            self.modified = True
        return rewriter.modified

    def rename_symbol(self, old_name: str, new_name: str):
        """Rename all occurrences of a symbol.

        Handles dotted new_names (e.g. 'pd.concat') by building
        nested Attribute nodes instead of a flat attribute string.
        """
        new_parts = new_name.split(".") if "." in new_name else [new_name]

        def _build_attr_expr(parts):
            if len(parts) == 1:
                return ast.Name(id=parts[0])
            return ast.Attribute(value=_build_attr_expr(parts[:-1]), attr=parts[-1])

        class SymbolRenamer(ast.NodeTransformer):
            def __init__(self, old, new_parts):
                self.old = old
                self.new_parts = new_parts
                self.new_expr = _build_attr_expr(new_parts) if len(new_parts) > 1 else None
                self.new_name = ".".join(new_parts)
                self.modified = False

            def visit_Name(self, node):
                if node.id == self.old:
                    self.modified = True
                    if self.new_expr:
                        return self.new_expr
                    node.id = self.new_name
                return node

            def visit_Attribute(self, node):
                self.generic_visit(node)
                if node.attr == self.old:
                    if self.new_expr:
                        node.attr = self.new_parts[-1]
                        node.value = _build_attr_expr(self.new_parts[:-1])
                    else:
                        node.attr = self.new_name
                    self.modified = True
                return node

        renamer = SymbolRenamer(old_name, new_parts)
        self.tree = renamer.visit(self.tree)
        if renamer.modified:
            self.modified = True
        return renamer.modified

    def rewrite_import_path(self, old_path: str, new_path: str):
        """Rewrite sub-module import paths (e.g. sklearn.cross_validation → sklearn.model_selection).
        Handles both 'from ... import' and 'import ...' statements.
        """
        class ImportPathRewriter(ast.NodeTransformer):
            def __init__(self, old, new):
                self.old = old
                self.new = new
                self.modified = False

            def visit_Import(self, node):
                for alias in node.names:
                    if alias.name == self.old or alias.name.startswith(self.old + "."):
                        alias.name = self.new + alias.name[len(self.old):]
                        self.modified = True
                return node

            def visit_ImportFrom(self, node):
                if node.module == self.old or (node.module and node.module.startswith(self.old + ".")):
                    node.module = self.new + node.module[len(self.old):]
                    self.modified = True
                return node

        rewriter = ImportPathRewriter(old_path, new_path)
        self.tree = rewriter.visit(self.tree)
        if rewriter.modified:
            self.modified = True
        return rewriter.modified

    def update_api_signature(self, function_name: str, new_kwargs: Dict[str, Any]):
        """Add or update keyword arguments in function calls."""
        class SignatureUpdater(ast.NodeTransformer):
            def __init__(self, func_name, kwargs):
                self.func_name = func_name
                self.kwargs = kwargs
                self.modified = False

            def visit_Call(self, node):
                self.generic_visit(node)
                # Check if it's the target function
                is_target = False
                if isinstance(node.func, ast.Name) and node.func.id == self.func_name:
                    is_target = True
                elif isinstance(node.func, ast.Attribute) and node.func.attr == self.func_name:
                    is_target = True
                
                if is_target:
                    for key, value in self.kwargs.items():
                        # Check if kwarg already exists
                        existing = next((k for k in node.keywords if k.arg == key), None)
                        if existing:
                            existing.value = ast.Constant(value=value)
                        else:
                            node.keywords.append(ast.keyword(arg=key, value=ast.Constant(value=value)))
                        self.modified = True
                return node

        updater = SignatureUpdater(function_name, new_kwargs)
        self.tree = updater.visit(self.tree)
        if updater.modified:
            self.modified = True
        return updater.modified

    def get_modified_source(self) -> str:
        if not self.modified:
            return self.source_code
        # Convert AST back to source code
        return astor.to_source(self.tree)

    def validate(self) -> bool:
        """Validate that the modified source is still valid Python."""
        try:
            ast.parse(self.get_modified_source())
            return True
        except SyntaxError:
            return False

    def generate_diff(self) -> str:
        import difflib
        old_lines = self.source_code.splitlines(keepends=True)
        new_lines = self.get_modified_source().splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile='original', tofile='modified')
        return "".join(diff)
