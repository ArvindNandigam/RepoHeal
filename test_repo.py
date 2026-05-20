from app.github.client import RepoHealGitHubClient

INSTALLATION_ID = 133948028

client = RepoHealGitHubClient(INSTALLATION_ID)

repo = client.get_repo("ArvindNandigam/Repohealdemo")

branch_name = "repoheal/test-branch"

client.create_branch(
    repo,
    branch_name
)

new_readme_content = """
# RepoHeal Demo

This repository was modified automatically by RepoHeal.
"""


client.commit_file(
    repo=repo,
    branch_name=branch_name,
    file_path="README.md",
    new_content=new_readme_content,
    commit_message="RepoHeal automated README update"
)

client.create_pull_request(
    repo=repo,
    branch_name=branch_name,
    title="RepoHeal automated update",
    body="""

## RepoHeal Automated Update

This PR was created automatically by RepoHeal.

### Changes
- Updated README.md

### Validation
- Pending

### Risk
LOW
"""
)