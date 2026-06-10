import ast
import astor
import re
from typing import Any


SYMBOL_TO_KNOWN_IMPORTS: dict[str, str] = {}


def _resolve_alias_to_import(alias_node: ast.alias) -> tuple[str, str]:
    name = alias_node.name
    asname = alias_node.asname or name
    return name, asname


def _known_import_symbols(tree: ast.Module, source: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name, asname = _resolve_alias_to_import(alias)
                result[name] = name
                if asname != name:
                    result[asname] = name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name, asname = _resolve_alias_to_import(alias)
                fqn = f"{module}.{name}" if module else name
                result[name] = fqn
                if asname != name:
                    result[asname] = fqn
    return result


class ImportRewriter(ast.NodeTransformer):
    def __init__(self, old_module: str, new_module: str):
        self.old_module = old_module
        self.new_module = new_module
        self._old_parts = old_module.split(".")

    def visit_Import(self, node: ast.Import):
        new_names = []
        for alias in node.names:
            if alias.name == self.old_module or alias.name.startswith(self.old_module + "."):
                suffix = alias.name[len(self.old_module):]
                new_name = self.new_module + suffix
                new_names.append(ast.alias(name=new_name, asname=alias.asname))
            else:
                new_names.append(alias)
        node.names = new_names
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module and (node.module == self.old_module or node.module.startswith(self.old_module + ".")):
            suffix = node.module[len(self.old_module):]
            node.module = self.new_module + suffix
        return node


class SymbolRenamer(ast.NodeTransformer):
    def __init__(self, old_name: str, new_name: str, module_scope: str | None = None):
        self.old_name = old_name
        self.new_name = new_name
        self.module_scope = module_scope

    def visit_Name(self, node: ast.Name):
        if node.id == self.old_name:
            node.id = self.new_name
        return node

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr == self.old_name:
            node.attr = self.new_name
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom):
        new_names = []
        for alias in node.names:
            if alias.name == self.old_name:
                new_names.append(ast.alias(name=self.new_name, asname=alias.asname))
            else:
                new_names.append(alias)
        node.names = new_names
        return node


class ApiSignatureUpdater(ast.NodeTransformer):
    def __init__(self, func_name: str, param_changes: dict[str, Any]):
        self.func_name = func_name
        self.param_changes = param_changes

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == self.func_name:
            self._apply_changes(node)
        elif isinstance(func, ast.Attribute) and func.attr == self.func_name:
            self._apply_changes(node)
        return node

    def _apply_changes(self, node: ast.Call):
        changes = self.param_changes
        if "rename" in changes:
            rename_map = changes["rename"]
            new_args = []
            for kw in node.keywords:
                if kw.arg in rename_map:
                    kw.arg = rename_map[kw.arg]
                new_args.append(kw)
            node.keywords = new_args
        if "add" in changes:
            for name, default in changes["add"].items():
                existing = any(kw.arg == name for kw in node.keywords)
                if not existing:
                    node.keywords.append(ast.keyword(arg=name, value=ast.Constant(value=default)))
        if "remove" in changes:
            node.keywords = [kw for kw in node.keywords if kw.arg not in changes["remove"]]


def rewrite_import(source: str, old_module: str, new_module: str) -> str:
    tree = ast.parse(source)
    transformer = ImportRewriter(old_module, new_module)
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    return astor.to_source(tree)


def rename_symbol(source: str, old_name: str, new_name: str) -> str:
    tree = ast.parse(source)
    transformer = SymbolRenamer(old_name, new_name)
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    return astor.to_source(tree)


def update_api_signature(source: str, func_name: str, param_changes: dict[str, Any]) -> str:
    tree = ast.parse(source)
    transformer = ApiSignatureUpdater(func_name, param_changes)
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    return astor.to_source(tree)


_TRANSFORM_MAP = {
    "rewrite_import": rewrite_import,
    "rename_symbol": rename_symbol,
    "update_api_signature": update_api_signature,
}


def apply_deterministic_transform(source: str, action_type: str, params: dict[str, Any]) -> str:
    fn = _TRANSFORM_MAP.get(action_type)
    if not fn:
        raise ValueError(f"Unknown deterministic transform: {action_type}")
    return fn(source, **params)
