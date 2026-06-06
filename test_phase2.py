import asyncio
from unittest.mock import MagicMock

from app.intelligence.webtool_client import WebtoolClient
from app.intelligence.pipeline import MigrationPipeline
from app.models.migration_models import HealthReport
from app.intelligence.correlator import MigrationCorrelator

async def run_test():
    print("Testing pipeline initialization...")
    webtool_client = MagicMock(spec=WebtoolClient)
    github_client = MagicMock()
    
    pipeline = MigrationPipeline(webtool_client, github_client)
    print("Migration pipeline instantiated successfully.")
    
    # Mock analysis dict
    mock_analysis = {
        "fingerprints": {
            "flask": {
                "version": "1.1.2",
                "symbols": ["flask.Flask.before_request"]
            }
        },
        "dependency_graph": {
            "flask": {"version": "1.1.2", "latest_version": "3.0.0"}
        },
        "semantic_graph": {
            "files": {
                "main.py": {
                    "apis": [{"name": "app.before_request", "function": "setup", "line": 10}]
                }
            }
        }
    }
    
    # Mock webtool response
    async def mock_get_symbol_intelligence(library, symbols):
        return {
            "library": library,
            "results": [{
                "symbol": symbols[0],
                "relationships": [{
                    "relation": "deprecated_in_favor_of",
                    "target": "flask.Flask.before_app_request",
                    "status": "verified"
                }]
            }]
        }
        
    webtool_client.get_symbol_intelligence.side_effect = mock_get_symbol_intelligence
    
    print("Running pipeline with mock data...")
    report = await pipeline.run(mock_analysis, "test/repo", MagicMock())
    
    print(f"Health Score: {report.overall_health_score}")
    print(f"Deprecated APIs: {len(report.deprecated_apis)}")
    print(f"Recommended Actions: {len(report.recommended_actions)}")
    
    if report.deprecated_apis:
        print(f"Found deprecated: {report.deprecated_apis[0].symbol}")

if __name__ == "__main__":
    asyncio.run(run_test())
