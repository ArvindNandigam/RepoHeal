import sys
import json
from pathlib import Path

# Add current dir to python path
sys.path.append(str(Path(__file__).parent))

from app.analysis.repository_analyzer import analyze_repository

def main():
    repo_path = str(Path(__file__).parent)
    print(f"Analyzing {repo_path}")
    try:
        analysis = analyze_repository(repo_path)
        print("Analysis complete.")
        print(f"Dependencies detected: {analysis.get('dependencies', {}).get('count')}")
        print("Dependency graph sample:")
        dep_graph = analysis.get('dependency_graph', {})
        for pkg, info in list(dep_graph.items())[:5]:
            print(f"  {pkg}: {info}")
            
        print("Fingerprints sample:")
        fingerprints = analysis.get('fingerprints', {})
        for pkg, info in list(fingerprints.items())[:5]:
            print(f"  {pkg}: version {info.get('version')}, {len(info.get('symbols', []))} symbols")
            
    except Exception as e:
        print(f"Error during analysis: {e}")

if __name__ == "__main__":
    main()
