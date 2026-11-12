import httpx

from app.github_client import GitHubClient


def test_client_lists_failed_runs_and_has_no_merge():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.params["status"] == "failure"
        return httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 9,
                        "name": "CI",
                        "conclusion": "failure",
                        "html_url": "https://github.com/acme/app/actions/runs/9",
                        "head_branch": "main",
                        "head_sha": "abc",
                        "created_at": "2024-11-01T00:00:00Z",
                    }
                ]
            },
        )

    client = GitHubClient(
        "token",
        client=httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(handler),
        ),
    )
    runs = client.list_failed_runs("acme/app", limit=5)
    assert runs[0]["id"] == 9
    assert not hasattr(client, "merge")
    assert not hasattr(GitHubClient, "merge_pull_request")
