from github import Github
from github.GithubException import GithubException

from app.github.auth import get_installation_token


class RepoHealGitHubClient:

    def __init__(self, installation_id):

        try:
            token = get_installation_token(installation_id)

            self.github = Github(token)

            print("[INFO] GitHub client initialized successfully")

        except Exception as e:
            print(f"[ERROR] Failed to initialize GitHub client: {e}")

            raise

    def get_repo(self, full_repo_name):

        try:
            repo = self.github.get_repo(full_repo_name)

            print(f"[INFO] Connected to repository: {repo.full_name}")

            return repo

        except GithubException as e:
            print(f"[ERROR] GitHub API error while fetching repo: {e}")

            raise

        except Exception as e:
            print(f"[ERROR] Unexpected error while fetching repo: {e}")

            raise

    def create_branch(self, repo, new_branch_name):

        try:
            default_branch = repo.get_branch(repo.default_branch)

            repo.create_git_ref(
                ref=f"refs/heads/{new_branch_name}",
                sha=default_branch.commit.sha
            )

            print(f"[INFO] Branch created: {new_branch_name}")

        except GithubException as e:
            print(f"[ERROR] GitHub API error while creating branch: {e}")

            raise

        except Exception as e:
            print(f"[ERROR] Unexpected error while creating branch: {e}")

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

            print(f"[INFO] Updated file: {file_path}")

        except GithubException as e:
            print(f"[ERROR] GitHub API error while updating file: {e}")

            raise

        except Exception as e:
            print(f"[ERROR] Unexpected error while updating file: {e}")

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

            print(f"[INFO] PR created: {pr.html_url}")

            return pr

        except GithubException as e:
            print(f"[ERROR] GitHub API error while creating PR: {e}")

            raise

        except Exception as e:
            print(f"[ERROR] Unexpected error while creating PR: {e}")

            raise