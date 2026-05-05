# tools/git_tools.py
# Git integration tools for HERMES.
# Uses GitPython (import git) - never calls subprocess directly.
# GITHUB_TOKEN is read ONLY from environment variables.
# Never log or print the token value. Always mask it in any output.

import os
import time
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from tools.base import BaseTool, ToolResult
from tools.registry import tool

try:
    import git

    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False


@tool(
    name="git_init",
    description="Initialise a new Git repository in a directory, or verify one already exists.",
    permissions=["filesystem_write"],
    risk_score=0.2,
    blocked_in=["safe"],
)
class GitInitTool(BaseTool):
    """Initialise a Git repository or report that one already exists."""

    class Input(BaseModel):
        """Validated input for GitInitTool."""

        directory: str = Field(
            default=".",
            description="Directory to initialise as a git repo, relative to project root",
        )
        initial_branch: str = Field(
            default="main",
            description="Name of the initial branch",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Initialise a Git repository and create a Python .gitignore if needed."""
        start_time = time.monotonic()
        if not GIT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="GitPython is not installed. Run: pip install gitpython",
                exit_code=1,
            )

        try:
            dir_path = Path(inp.directory).resolve()
            dir_path.mkdir(parents=True, exist_ok=True)

            try:
                existing_repo = git.Repo(dir_path, search_parent_directories=False)
                duration = time.monotonic() - start_time
                logger.info("git_init | existing_repo={} | duration={:.2f}s", dir_path, duration)
                return ToolResult(
                    success=True,
                    output=(
                        f"Git repository already exists at {dir_path} "
                        f"(branch: {existing_repo.active_branch.name})"
                    ),
                    exit_code=0,
                    duration_seconds=duration,
                )
            except git.InvalidGitRepositoryError:
                pass

            git.Repo.init(dir_path, initial_branch=inp.initial_branch)

            gitignore_path = Path(dir_path) / ".gitignore"
            if not gitignore_path.exists():
                gitignore_path.write_text(
                    "__pycache__/\n*.pyc\n*.pyo\n.env\nvenv/\n.venv/\n*.egg-info/\ndist/\nbuild/\n",
                    encoding="utf-8",
                )

            duration = time.monotonic() - start_time
            logger.info("git_init | repo={} | branch={} | duration={:.2f}s", dir_path, inp.initial_branch, duration)
            return ToolResult(
                success=True,
                output=f"Git repository initialised at {dir_path} on branch '{inp.initial_branch}'",
                exit_code=0,
                duration_seconds=duration,
            )
        except git.GitCommandError as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Git error: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Git error: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )


@tool(
    name="git_add_commit",
    description="Stage all changes and create a commit in an existing Git repository.",
    permissions=["filesystem_write"],
    risk_score=0.3,
    blocked_in=["safe"],
)
class GitAddCommitTool(BaseTool):
    """Stage changes and create a commit in an existing Git repository."""

    class Input(BaseModel):
        """Validated input for GitAddCommitTool."""

        directory: str = Field(
            default=".",
            description="Path to the Git repository, relative to project root",
        )
        message: str = Field(
            ...,
            description="Commit message - must be descriptive and non-empty",
            min_length=5,
            max_length=500,
        )
        add_all: bool = Field(
            default=True,
            description="If True, stage all changes (git add -A). If False, only stage already-tracked files.",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Stage changes and create a commit with the provided message."""
        start_time = time.monotonic()
        if not GIT_AVAILABLE:
            return ToolResult(
                success=False,
                output="",
                error="GitPython is not installed. Run: pip install gitpython",
                exit_code=1,
            )

        try:
            try:
                repo = git.Repo(inp.directory, search_parent_directories=True)
            except git.InvalidGitRepositoryError:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"No git repository found at or above: {inp.directory}. Run git_init first.",
                    exit_code=1,
                )

            if inp.add_all:
                repo.git.add(A=True)
            else:
                repo.git.add(update=True)

            if not repo.is_dirty(index=True, working_tree=False):
                duration = time.monotonic() - start_time
                logger.info("git_add_commit | clean_repo={} | duration={:.2f}s", repo.working_tree_dir, duration)
                return ToolResult(
                    success=True,
                    output="Nothing to commit - working tree is clean.",
                    exit_code=0,
                    duration_seconds=duration,
                )

            commit = repo.index.commit(inp.message)
            files_changed = len(commit.stats.files)
            duration = time.monotonic() - start_time
            logger.info(
                "git_add_commit | repo={} | files={} | sha={} | duration={:.2f}s",
                repo.working_tree_dir,
                files_changed,
                commit.hexsha[:8],
                duration,
            )
            return ToolResult(
                success=True,
                output=f"Committed {files_changed} file(s): '{inp.message}' (SHA: {commit.hexsha[:8]})",
                exit_code=0,
                duration_seconds=duration,
            )
        except git.GitCommandError as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Git error: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Git error: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )


@tool(name="git_push", description="Push committed changes to a remote GitHub repository. Requires GITHUB_TOKEN in environment.", permissions=["network_write"], risk_score=0.7, blocked_in=["safe", "plan"])
class GitPushTool(BaseTool):
    class Input(BaseModel):
        directory: str = Field(default=".", description="Path to the git repository")
        remote: str = Field(default="origin", description="Remote name to push to")
        branch: str = Field(default="main", description="Branch to push")
        github_token: str = Field(default="", description="Leave empty — read from GITHUB_TOKEN env var")

    def execute(self, inp: Input) -> ToolResult:
        if not GIT_AVAILABLE:
            return ToolResult(success=False, output="", error="GitPython not installed", exit_code=1, duration_seconds=0.0)
        
        import os
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return ToolResult(success=False, output="", error="GITHUB_TOKEN environment variable is not set. Set it before using git_push.", exit_code=1, duration_seconds=0.0)
        
        # NEVER log the token value
        logger.info(f"git_push: pushing {inp.directory} to {inp.remote}/{inp.branch} [token=REDACTED]")
        
        try:
            repo = git.Repo(inp.directory, search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            return ToolResult(success=False, output="", error=f"No git repo found at: {inp.directory}", exit_code=1, duration_seconds=0.0)
        
        try:
            # Get remote URL and inject token for HTTPS auth
            remote = repo.remote(inp.remote)
            original_url = remote.url
            
            # Inject token into URL if it's a github.com HTTPS URL
            if "github.com" in original_url and original_url.startswith("https://"):
                authed_url = original_url.replace("https://", f"https://{token}@")
                remote.set_url(authed_url)
            
            push_info = remote.push(refspec=f"{inp.branch}:{inp.branch}")
            
            # Restore original URL immediately (never leave token in config)
            if "github.com" in original_url and original_url.startswith("https://"):
                remote.set_url(original_url)
            
            # Check for push errors
            for info in push_info:
                if info.flags & info.ERROR:
                    return ToolResult(success=False, output="", error=f"Push failed: {info.summary}", exit_code=1, duration_seconds=0.0)
            
            return ToolResult(success=True, output=f"Pushed to {inp.remote}/{inp.branch} successfully", exit_code=0, duration_seconds=0.0)
        
        except git.GitCommandError as e:
            # Mask token in error messages
            error_msg = str(e).replace(token, "[GITHUB_TOKEN]") if token else str(e)
            return ToolResult(success=False, output="", error=f"Git push failed: {error_msg}", exit_code=1, duration_seconds=0.0)
        except Exception as e:
            error_msg = str(e).replace(token, "[GITHUB_TOKEN]") if token else str(e)
            return ToolResult(success=False, output="", error=str(error_msg), exit_code=1, duration_seconds=0.0)
