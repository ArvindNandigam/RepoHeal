from github import Github

from app.github.auth import get_installation_token


class RepoHealGitHubClient:

    def __init__(self, installation_id):
        token = get_installation_token(installation_id)

        self.github = Github(token)

    def get_repo(self, full_repo_name):
        return self.github.get_repo(full_repo_name)

    def create_branch(self, repo, new_branch_name):

        default_branch = repo.get_branch(repo.default_branch)

        repo.create_git_ref(
            ref=f"refs/heads/{new_branch_name}",
            sha=default_branch.commit.sha
        )

        print(f"Branch created: {new_branch_name}")
    def commit_file(
        self,
        repo,
        branch_name,
        file_path,
        new_content,
        commit_message
    ):

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

        print(f"Updated file: {file_path}")
    def create_pull_request(
        self,
        repo,
        branch_name,
        title,
        body
    ):

        pr = repo.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base=repo.default_branch
        )

        print(f"PR created: {pr.html_url}")

        return pr