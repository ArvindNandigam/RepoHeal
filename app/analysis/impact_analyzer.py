from typing import Dict, List, Any, Set
from collections import defaultdict, deque

from app.models.migration_models import (
    SymbolAssessment, ImpactReport, AffectedFile, AffectedFunction
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

class ImpactAnalyzer:
    def analyze(self, semantic_graph: Dict[str, Any], assessments: List[SymbolAssessment]) -> List[ImpactReport]:
        files = semantic_graph.get("files", {})
        total_files = len(files)
        
        call_graph = self._build_call_graph(files)
        
        reports = []
        for assessment in assessments:
            if assessment.status in ("deprecated", "at_risk", "breaking"):
                report = self._analyze_symbol(assessment, files, call_graph, total_files)
                assessment.files_using = [file.path for file in report.affected_files]
                assessment.functions_using = [
                    function.name
                    for function in report.affected_functions
                    if function.call_chain_depth == 1
                ]
                reports.append(report)
        return reports
    
    def _build_call_graph(self, files: Dict[str, Any]) -> Dict[str, List[str]]:
        """Build adjacency list: function_name -> list of functions it calls"""
        call_graph = defaultdict(list)
        for file_path, data in files.items():
            for call in data.get("calls", []):
                caller = call.get("function")
                callee = call.get("name")
                if caller and callee:
                    call_graph[caller].append(callee)
        return call_graph
        
    def _build_reverse_call_graph(self, call_graph: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Build adjacency list: callee -> list of callers"""
        reverse_graph = defaultdict(list)
        for caller, callees in call_graph.items():
            for callee in callees:
                reverse_graph[callee].append(caller)
        return reverse_graph

    def _analyze_symbol(self, assessment: SymbolAssessment, files: Dict[str, Any], call_graph: Dict[str, List[str]], total_files: int) -> ImpactReport:
        symbol = assessment.symbol
        affected_files_dict: Dict[str, List[int]] = defaultdict(list)
        affected_functions_dict: Dict[str, AffectedFunction] = {}
        affected_classes: Set[str] = set()
        function_locations: Dict[str, str] = {}
        
        symbol_parts = symbol.split(".")
        symbol_base = symbol_parts[-1] if symbol_parts else symbol
        
        direct_callers = set()
        version_gap = "@" in symbol and "→" in symbol

        for file_path, data in files.items():
            for func in data.get("functions", []):
                fname = func.get("name")
                if fname:
                    function_locations.setdefault(fname, file_path)
        
        # First pass: find direct impacts
        for file_path, data in files.items():
            # For version-gap assessments (e.g. "numpy@1.19.0 → 2.0.0"),
            # match by checking if the library appears in the file's imports
            if version_gap:
                imports = data.get("imports", [])
                if isinstance(imports, list):
                    for imp in imports:
                        if isinstance(imp, dict):
                            lib_name = imp.get("module", "") or imp.get("name", "")
                        else:
                            lib_name = str(imp)
                        if assessment.library.lower() in lib_name.lower():
                            affected_files_dict[file_path].append(0)
                            break
                elif isinstance(imports, dict):
                    norm = imports.get("normalized", [])
                    if isinstance(norm, list) and assessment.library in norm:
                        affected_files_dict[file_path].append(0)
                        break
                    raw = imports.get("raw", [])
                    if isinstance(raw, list):
                        for imp in raw:
                            if assessment.library.lower() in imp.lower():
                                affected_files_dict[file_path].append(0)
                                break
                continue

            for api in data.get("apis", []):
                api_name = api.get("name", "")
                matches = self._matches_symbol(
                    api_name, api.get("package"), assessment.library, symbol, symbol_base
                )
                if matches:
                    line = api.get("line")
                    if line:
                        affected_files_dict[file_path].append(line)
                    
                    function = api.get("function")
                    if function:
                        direct_callers.add(function)
                        if function not in affected_functions_dict:
                            affected_functions_dict[function] = AffectedFunction(
                                name=function,
                                file_path=file_path,
                                line_start=None,
                                line_end=None,
                                call_chain_depth=1
                            )
                            
            for cls in data.get("classes", []):
                bases = cls.get("bases", [])
                for base in bases:
                    if self._matches_symbol(base, None, assessment.library, symbol, symbol_base):
                        affected_classes.add(cls.get("name"))
                        line = cls.get("line_start")
                        if line:
                            affected_files_dict[file_path].append(line)

        # Enhance function details
        for file_path, data in files.items():
            for func in data.get("functions", []):
                fname = func.get("name")
                if fname in affected_functions_dict:
                    af = affected_functions_dict[fname]
                    af.line_start = func.get("line_start")
                    af.line_end = func.get("line_end")

        # Trace depth
        reverse_graph = self._build_reverse_call_graph(call_graph)
        max_depth = 1 if direct_callers else 0
        
        queue = deque([(caller, 1) for caller in direct_callers])
        visited = set(direct_callers)
        
        while queue:
            current, depth = queue.popleft()
            max_depth = max(max_depth, depth)
            
            for parent in reverse_graph.get(current, []):
                if parent not in visited:
                    visited.add(parent)
                    queue.append((parent, depth + 1))
                    if parent not in affected_functions_dict:
                        parent_file_path = function_locations.get(parent, "unknown")
                        affected_functions_dict[parent] = AffectedFunction(
                            name=parent,
                            file_path=parent_file_path,
                            call_chain_depth=depth + 1
                        )
                        
        affected_files_list = [
            AffectedFile(path=path, lines=sorted(list(set(lines))))
            for path, lines in affected_files_dict.items()
        ]
        
        impact_breadth = (len(affected_files_list) / total_files * 100) if total_files > 0 else 0.0
        
        return ImpactReport(
            symbol=symbol,
            affected_files=affected_files_list,
            affected_functions=list(affected_functions_dict.values()),
            affected_classes=list(affected_classes),
            impact_breadth=impact_breadth,
            impact_depth=max_depth
        )

    def _matches_symbol(
        self,
        candidate: str,
        candidate_package: str | None,
        library: str,
        symbol: str,
        symbol_base: str
    ) -> bool:
        if not candidate:
            return False

        candidate_parts = candidate.split(".")
        if candidate == symbol or candidate.endswith(f".{symbol}"):
            return True

        if symbol_base not in candidate_parts:
            return False

        if candidate_package and library:
            return candidate_package == library

        return True
