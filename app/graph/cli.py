import argparse
import sys
from app.github.client import RepoHealGitHubClient
from app.graph.rebuilder import GraphRebuilder


def rebuild_command():
    parser = argparse.ArgumentParser(description="RepoHeal Graph Rebuild CLI")
    parser.add_argument("repo", help="Repository in format owner/name")
    parser.add_argument("--installation-id", type=int, required=True, help="GitHub App installation ID")
    parser.add_argument("--analysis-id", help="Specific analysis ID to rebuild from")
    parser.add_argument("--branch", help="Branch filter")
    parser.add_argument("--commit", help="Commit SHA filter")

    args = parser.parse_args()

    client = RepoHealGitHubClient(args.installation_id)
    rebuilder = GraphRebuilder(client)
    result = rebuilder.rebuild(
        args.repo,
        analysis_id=args.analysis_id,
        branch=args.branch,
        commit=args.commit
    )

    print(f"Status: {result['status']}")
    print(f"Nodes created: {result['nodes_created']}")
    print(f"Edges created: {result['edges_created']}")
    print(f"Message: {result['message']}")
    sys.exit(0 if result['status'] == 'completed' else 1)


if __name__ == "__main__":
    rebuild_command()
