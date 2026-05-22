"""
Metadata storage - manages persistent artifact layer.

Stores analysis snapshots in .repoheal directory with structured format:

.repoheal/
├── graphs/
│   ├── dependency_graph.json
│   └── module_graph.json
├── analysis/
│   ├── imports.json
│   ├── packages.json
│   └── repo_summary.json
├── reports/
│   └── dependency_risk_report.json
└── config/
    └── repoheal.yaml
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MetadataStore:
    """
    Persistent metadata storage for repository analysis.
    Creates .repoheal directory structure for durable snapshots.
    """
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self.meta_dir = self.repo_path / ".repoheal"
        self._init_directories()
    
    def _init_directories(self) -> None:
        """Initialize .repoheal directory structure"""
        directories = [
            self.meta_dir,
            self.meta_dir / "graphs",
            self.meta_dir / "analysis",
            self.meta_dir / "snapshots",
            self.meta_dir / "reports",
            self.meta_dir / "config"
        ]
        
        for dir_path in directories:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory: {dir_path}")
    
    def save_dependency_graph(self, graph: Dict) -> None:
        """Save dependency graph to durable storage"""
        path = self.meta_dir / "graphs" / "dependency_graph.json"
        self._write_json(path, graph)
        logger.info(f"Saved dependency graph to {path}")
    
    def save_module_graph(self, graph: Dict) -> None:
        """Save module import graph to durable storage"""
        path = self.meta_dir / "graphs" / "module_graph.json"
        self._write_json(path, graph)
        logger.info(f"Saved module graph to {path}")
    
    def save_imports(self, imports: Dict) -> None:
        """Save detailed import data"""
        path = self.meta_dir / "analysis" / "imports.json"
        self._write_json(path, imports)
        logger.info(f"Saved imports to {path}")
    
    def save_packages(self, packages: Dict) -> None:
        """Save package analysis"""
        path = self.meta_dir / "analysis" / "packages.json"
        self._write_json(path, packages)
        logger.info(f"Saved packages to {path}")
    
    def save_repo_summary(self, summary: Dict) -> None:
        """Save repository analysis summary"""
        path = self.meta_dir / "analysis" / "repo_summary.json"
        # Add metadata
        summary_with_meta = {
            **summary,
            "saved_at": datetime.utcnow().isoformat(),
            "version": "1.0"
        }
        self._write_json(path, summary_with_meta)
        logger.info(f"Saved repo summary to {path}")
    
    def save_risk_report(self, report: Dict) -> None:
        """Save dependency risk assessment report"""
        path = self.meta_dir / "reports" / "dependency_risk_report.json"
        self._write_json(path, report)
        logger.info(f"Saved risk report to {path}")
    
    def save_analysis_snapshot(self, analysis: Dict) -> None:
        """
        Save complete analysis snapshot.
        This is the full portable artifact.
        """
        snapshot_fingerprint = hashlib.sha1(
            json.dumps(
                analysis,
                sort_keys=True,
                default=str
            ).encode("utf-8")
        ).hexdigest()[:10]

        snapshot = {
            "repository": str(self.repo_path),
            "analyzed_at": datetime.utcnow().isoformat(),
            "analysis": analysis,
            "version": "1.0"
        }

        snapshot_path = (
            self.meta_dir
            / "snapshots"
            / f"analysis_{snapshot_fingerprint}.json"
        )

        graph_snapshot_path = (
            self.meta_dir
            / "snapshots"
            / f"graph_{snapshot_fingerprint}.json"
        )

        summary_snapshot_path = (
            self.meta_dir
            / "snapshots"
            / f"summary_{snapshot_fingerprint}.json"
        )

        self._write_json(snapshot_path, snapshot)

        if "dependency_graph" in analysis:
            self._write_json(
                graph_snapshot_path,
                analysis["dependency_graph"]
            )
        
        # Save individual components
        if "imports" in analysis:
            self.save_imports(analysis["imports"])
        if "dependency_graph" in analysis:
            self.save_dependency_graph(analysis["dependency_graph"])
        if "dependencies" in analysis:
            self.save_packages(analysis["dependencies"])
        
        # Save summary
        summary = {
            "imports_summary": analysis.get("imports", {}).get("summary", {}),
            "dependencies_count": analysis.get("dependencies", {}).get("count", 0),
            "issues": analysis.get("issues", {}),
            "hashes": analysis.get("hashes", {})
        }
        self.save_repo_summary(summary)
        self._write_json(summary_snapshot_path, summary)
        
        logger.info(f"Saved analysis snapshot to {self.meta_dir}")

    def _latest_snapshot_file(self, prefix: str) -> Optional[Path]:
        """Return the most recently written immutable snapshot file."""
        snapshot_dir = self.meta_dir / "snapshots"

        if not snapshot_dir.exists():
            return None

        candidates = list(snapshot_dir.glob(f"{prefix}_*.json"))

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda path: path.stat().st_mtime
        )
    
    def load_analysis_snapshot(self) -> Optional[Dict]:
        """Load most recent analysis snapshot"""
        path = self._latest_snapshot_file("summary")

        if not path:
            path = self.meta_dir / "analysis" / "repo_summary.json"

        return self._read_json(path)
    
    def load_dependency_graph(self) -> Optional[Dict]:
        """Load dependency graph"""
        path = self._latest_snapshot_file("graph")

        if not path:
            path = self.meta_dir / "graphs" / "dependency_graph.json"

        return self._read_json(path)
    
    def load_module_graph(self) -> Optional[Dict]:
        """Load module graph"""
        path = self.meta_dir / "graphs" / "module_graph.json"
        return self._read_json(path)
    
    def load_imports(self) -> Optional[Dict]:
        """Load imports data"""
        path = self.meta_dir / "analysis" / "imports.json"
        return self._read_json(path)

    def load_packages(self) -> Optional[Dict]:
        """Load package analysis"""
        path = self.meta_dir / "analysis" / "packages.json"
        return self._read_json(path)
    
    def clear_snapshots(self) -> None:
        """Clear all stored snapshots"""
        import shutil
        try:
            shutil.rmtree(self.meta_dir)
            self._init_directories()
            logger.info(f"Cleared snapshots at {self.meta_dir}")
        except Exception as e:
            logger.error(f"Error clearing snapshots: {e}")
    
    def _write_json(self, path: Path, data: Dict) -> None:
        """Write data to JSON file with error handling"""
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error writing to {path}: {e}")
            raise
    
    def _read_json(self, path: Path) -> Optional[Dict]:
        """Read JSON file with error handling"""
        if not path.exists():
            return None
        
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading {path}: {e}")
            return None


def save_analysis_to_metadata(repo_path: str, analysis: Dict) -> None:
    """Convenience function to save analysis snapshot"""
    store = MetadataStore(repo_path)
    store.save_analysis_snapshot(analysis)
