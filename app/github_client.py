"""GitHub REST wrapper. This client can open pull requests. It cannot merge them."""

from __future__ import annotations

import base64
from typing import Any

import httpx


class GitHubError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def split_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise GitHubError(f"repository must be owner/name, got {repo!r}")
    owner, name = repo.split("/", 1)
    return owner, name


class GitHubClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ci-remediation-agent",
        }
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.base_url, headers=headers, timeout=30.0)
        if client is not None:
            self._client.headers.update(headers)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub {method} {path} failed ({response.status_code}): {response.text[:400]}",
                response.status_code,
            )
        if not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.content

    def list_failed_runs(self, repo: str, limit: int = 10) -> list[dict[str, Any]]:
        owner, name = split_repo(repo)
        payload = self._request(
            "GET",
            f"/repos/{owner}/{name}/actions/runs",
            params={"status": "failure", "per_page": max(1, min(limit, 50))},
        )
        runs = []
        for run in payload.get("workflow_runs", [])[:limit]:
            runs.append(
                {
                    "id": run["id"],
                    "name": run.get("name") or run.get("display_title") or "",
                    "html_url": run.get("html_url") or "",
                    "conclusion": run.get("conclusion") or "failure",
                    "head_branch": run.get("head_branch") or "",
                }
            )
        return runs

    def download_logs(self, repo: str, run_id: int) -> bytes:
        owner, name = split_repo(repo)
        response = self._client.get(
            f"/repos/{owner}/{name}/actions/runs/{run_id}/logs",
            follow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise GitHubError("log download redirect was missing a location", response.status_code)
            fetched = httpx.get(location, timeout=60.0, follow_redirects=True)
            if fetched.status_code >= 400:
                raise GitHubError(
                    f"log archive download failed ({fetched.status_code})",
                    fetched.status_code,
                )
            return fetched.content
        if response.status_code >= 400:
            raise GitHubError(
                f"log download failed ({response.status_code}): {response.text[:400]}",
                response.status_code,
            )
        return response.content

    def fetch_log_text(self, repo: str, run_id: int) -> str:
        from app.logs import failed_job_text

        data = self.download_logs(repo, run_id)
        if data[:2] == b"PK":
            return failed_job_text(data)
        return data.decode("utf-8", errors="replace")

    def get_branch_sha(self, repo: str, branch: str = "main") -> str:
        owner, name = split_repo(repo)
        payload = self._request("GET", f"/repos/{owner}/{name}/git/ref/heads/{branch}")
        return payload["object"]["sha"]

    def get_file(self, repo: str, path: str, ref: str = "main") -> str:
        owner, name = split_repo(repo)
        payload = self._request(
            "GET",
            f"/repos/{owner}/{name}/contents/{path}",
            params={"ref": ref},
        )
        if isinstance(payload, list) or "content" not in payload:
            raise GitHubError(f"{path} is not a file")
        return base64.b64decode(payload["content"]).decode("utf-8")

    def _file_sha(self, repo: str, path: str, ref: str) -> str | None:
        owner, name = split_repo(repo)
        try:
            payload = self._request(
                "GET",
                f"/repos/{owner}/{name}/contents/{path}",
                params={"ref": ref},
            )
        except GitHubError as exc:
            if exc.status_code == 404:
                return None
            raise
        if isinstance(payload, dict):
            return payload.get("sha")
        return None

    def open_pull_request(
        self,
        repo: str,
        path: str,
        content: str,
        branch: str,
        title: str,
        body: str,
        base: str = "main",
        commit_message: str | None = None,
    ) -> str:
        owner, name = split_repo(repo)
        base_sha = self.get_branch_sha(repo, base)
        self._request(
            "POST",
            f"/repos/{owner}/{name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        file_sha = self._file_sha(repo, path, base)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        put_body: dict[str, Any] = {
            "message": commit_message or title,
            "content": encoded,
            "branch": branch,
        }
        if file_sha:
            put_body["sha"] = file_sha
        self._request("PUT", f"/repos/{owner}/{name}/contents/{path}", json=put_body)
        pull = self._request(
            "POST",
            f"/repos/{owner}/{name}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        return pull["html_url"]
