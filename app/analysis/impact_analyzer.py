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
                report = self._analyze_symbol(assessment.symbol, files, call_graph, total_files)
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

    def _analyze_symbol(self, symbol: str, files: Dict[str, Any], call_graph: Dict[str, List[str]], total_files: int) -> ImpactReport:
        affected_files_dict: Dict[str, List[int]] = defaultdict(list)
        affected_functions_dict: Dict[str, AffectedFunction] = {}
        affected_classes: Set[str] = set()
        
        symbol_parts = symbol.split(".")
        symbol_base = symbol_parts[-1] if symbol_parts else symbol
        
        direct_callers = set()
        
        # First pass: find direct impacts
        for file_path, data in files.items():
            for api in data.get("apis", []):
                api_name = api.get("name", "")
                if symbol_base in api_name.split("."):
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
                    if symbol_base in base.split("."):
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
                        affected_functions_dict[parent] = AffectedFunction(
                            name=parent,
                            file_path="unknown",
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
