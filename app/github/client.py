import json
from datetime import datetime, timezone

import requests

from github import Github
from github.GithubException import GithubException

from app.github.auth import get_installation_token
from app.utils.logger import get_logger


logger = get_logger(__name__)

REPOHEAL_BASE_URL = "https://repoheal.onrender.com"
REPOHEAL_METADATA_BRANCH = "repoheal.meta"


class RepoHealGitHubClient:

    def __init__(self, installation_id):

        try:
            self.installation_token = get_installation_token(installation_id)

            self.github = Github(self.installation_token)

            logger.info(
                "GitHub client initialized successfully"
            )

        except Exception as e:

            logger.error(
                f"Failed to initialize GitHub client: {e}"
            )

            raise

    def list_installation_repositories(self):

        repositories = []
        seen_repository_ids = set()
        page = 1

        while True:

            response = requests.get(
                "https://api.github.com/installation/repositories",
                headers={
                    "Authorization": (
                        f"Bearer {self.installation_token}"
                    ),
                    "Accept": (
                        "application/vnd.github+json"
                    )
                },
                params={
                    "per_page": 100,
                    "page": page
                },
                timeout=15
            )

            response.raise_for_status()

            page_repositories = response.json().get("repositories", [])

            if not page_repositories:
                break

            for repository in page_repositories:

                repository_id = repository.get("id")

                if repository_id in seen_repository_ids:
                    continue

                seen_repository_ids.add(repository_id)
                repositories.append(repository)

            page += 1

        return repositories

    def get_repo(self, full_repo_name):

        try:
            repo = self.github.get_repo(full_repo_name)

            logger.info(
                f"Connected to repository: {repo.full_name}"
            )

            return repo

        except GithubException as e:

            logger.error(
                f"GitHub API error while fetching repo: {e}"
            )

            raise

        except Exception as e:

            logger.error(
                f"Unexpected error while fetching repo: {e}"
            )

            raise

    def ensure_branch(self, repo, branch_name):

        try:
            repo.get_branch(branch_name)

            logger.info(
                f"Branch already exists: {branch_name}"
            )

            return

        except GithubException as e:

            if e.status != 404:
                logger.error(
                    f"GitHub API error while checking branch: {e}"
                )
                raise

        default_branch = repo.get_branch(
            repo.default_branch
        )

        repo.create_git_ref(
            ref=f"refs/heads/{branch_name}",
            sha=default_branch.commit.sha
        )

        logger.info(
            f"Branch created: {branch_name}"
        )

    def upsert_file(
        self,
        repo,
        branch_name,
        file_path,
        content,
        commit_message
    ):

        try:
            contents = repo.get_contents(
                file_path,
                ref=branch_name
            )

            repo.update_file(
                path=contents.path,
                message=commit_message,
                content=content,
                sha=contents.sha,
                branch=branch_name
            )

            logger.info(
                f"Updated file: {file_path}"
            )

        except GithubException as e:

            if e.status != 404:
                logger.error(
                    f"GitHub API error while writing file: {e}"
                )
                raise

            repo.create_file(
                path=file_path,
                message=commit_message,
                content=content,
                branch=branch_name
            )

            logger.info(
                f"Created file: {file_path}"
            )

    def bootstrap_metadata_branch(self, repo):

        repo_full_name = repo.full_name
        workspace_url = (
            f"{REPOHEAL_BASE_URL}/workspace/{repo.owner.login}/{repo.name}"
        )

        self.ensure_branch(
            repo,
            REPOHEAL_METADATA_BRANCH
        )

        metadata_readme = (
            "# RepoHeal Metadata Branch\n\n"
            "This branch stores:\n"
            "- dependency intelligence\n"
            "- graph snapshots\n"
            "- analysis metadata\n"
            "- RepoHeal reports\n\n"
            "Do not modify manually.\n\n"
            "Open RepoHeal:\n\n"
            f"{workspace_url}\n"
        )

        metadata_json = json.dumps(
            {
                "schema_version": 1,
                "repository": repo_full_name,
                "branch": REPOHEAL_METADATA_BRANCH,
                "workspace_url": workspace_url,
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "artifacts": []
            },
            indent=2
        ) + "\n"

        self.upsert_file(
            repo,
            REPOHEAL_METADATA_BRANCH,
            "repoheal.meta/README.md",
            metadata_readme,
            "Initialize RepoHeal metadata branch"
        )

        self.upsert_file(
            repo,
            REPOHEAL_METADATA_BRANCH,
            "repoheal.meta/metadata.json",
            metadata_json,
            "Initialize RepoHeal metadata manifest"
        )

        for placeholder_path in (
            "repoheal.meta/analysis/.gitkeep",
            "repoheal.meta/graphs/.gitkeep",
            "repoheal.meta/reports/.gitkeep",
            "repoheal.meta/sessions/.gitkeep"
        ):

            self.upsert_file(
                repo,
                REPOHEAL_METADATA_BRANCH,
                placeholder_path,
                "RepoHeal metadata directory\n",
                f"Initialize {placeholder_path}"
            )

    def bootstrap_installation_metadata(self):

        repositories = []

        for repository_info in self.list_installation_repositories():

            full_name = repository_info.get("full_name")

            if not full_name:
                continue

            repo = self.get_repo(full_name)

            self.bootstrap_metadata_branch(repo)
            repositories.append(full_name)

        logger.info(
            f"Bootstrapped RepoHeal metadata for {len(repositories)} repositories"
        )

        return repositories

    def create_branch(self, repo, new_branch_name):

        try:
            default_branch = repo.get_branch(
                repo.default_branch
            )

            repo.create_git_ref(
                ref=f"refs/heads/{new_branch_name}",
                sha=default_branch.commit.sha
            )

            logger.info(
                f"Branch created: {new_branch_name}"
            )

        except GithubException as e:

            logger.error(
                f"GitHub API error while creating branch: {e}"
            )

            raise

        except Exception as e:

            logger.error(
                f"Unexpected error while creating branch: {e}"
            )

            raise

    def commit_file(
        self,
        repo,
        branch_name,
        file_path,
        new_content,
        commit_message
    ):

        try:
            contents = repo.get_contents(
                file_path,
                ref=branch_name
            )

            repo.update_file(
                path=contents.path,
                message=commit_message,
                content=new_content,
                sha=contents.sha,
                branch=branch_name
            )

            logger.info(
                f"Updated file: {file_path}"
            )

        except GithubException as e:

            logger.error(
                f"GitHub API error while updating file: {e}"
            )

            raise

        except Exception as e:

            logger.error(
                f"Unexpected error while updating file: {e}"
            )

            raise

    def create_pull_request(
        self,
        repo,
        branch_name,
        title,
        body
    ):

        try:
            pr = repo.create_pull(
                title=title,
                body=body,
                head=branch_name,
                base=repo.default_branch
            )

            logger.info(
                f"PR created: {pr.html_url}"
            )

            return pr

        except GithubException as e:

            logger.error(
                f"GitHub API error while creating PR: {e}"
            )

            raise

        except Exception as e:

            logger.error(
                f"Unexpected error while creating PR: {e}"
            )

            raise