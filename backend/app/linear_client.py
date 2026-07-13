from dataclasses import dataclass
from typing import Any, Literal

import requests

from .config import Settings


LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_REQUEST_TIMEOUT_SECONDS = 15
LINEAR_PAGE_SIZE = 50


@dataclass(frozen=True)
class LinearProviderError:
    code: Literal["not_configured", "authentication", "provider", "malformed_response"]
    message: str
    http_status: int | None = None


@dataclass(frozen=True)
class LinearReadResult:
    records: list[dict[str, Any]]
    error: LinearProviderError | None = None


@dataclass(frozen=True)
class LinearHealthResult:
    state: Literal["not_configured", "connected", "authentication_failure", "provider_failure"]
    error: LinearProviderError | None = None


PROJECTS_QUERY = """
query PcosLinearProjects($first: Int!, $after: String) {
  projects(first: $first, after: $after) {
    nodes {
      id
      name
      state
      url
      priority
      priorityLabel
      startDate
      targetDate
      createdAt
      updatedAt
      completedAt
      canceledAt
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


ISSUES_QUERY = """
query PcosLinearIssues($first: Int!, $after: String, $relationFirst: Int!) {
  issues(first: $first, after: $after, orderBy: updatedAt) {
    nodes {
      id
      identifier
      title
      description
      priority
      priorityLabel
      createdAt
      updatedAt
      completedAt
      canceledAt
      dueDate
      url
      state { id name type }
      project { id name }
      parent { id identifier }
      projectMilestone { id name targetDate }
      assignee { id name email }
      team { id key name }
      relations(first: $relationFirst) {
        nodes {
          id
          type
          relatedIssue { id identifier title state { name type } }
        }
        pageInfo { hasNextPage endCursor }
      }
      inverseRelations(first: $relationFirst) {
        nodes {
          id
          type
          issue { id identifier title state { name type } }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


ISSUE_RELATIONS_QUERY = """
query PcosLinearIssueRelations(
  $id: String!
  $first: Int!
  $relationsAfter: String
  $inverseAfter: String
) {
  issue(id: $id) {
    relations(first: $first, after: $relationsAfter) {
      nodes {
        id
        type
        relatedIssue { id identifier title state { name type } }
      }
      pageInfo { hasNextPage endCursor }
    }
    inverseRelations(first: $first, after: $inverseAfter) {
      nodes {
        id
        type
        issue { id identifier title state { name type } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


VIEWER_QUERY = "query PcosLinearHealth { viewer { id } }"


class LinearClient:
    def __init__(
        self,
        settings: Settings,
        *,
        session: Any = requests,
        timeout_seconds: int = LINEAR_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = getattr(settings, "linear_api_key", None)
        self._session = session
        self._timeout_seconds = timeout_seconds

    def check_health(self) -> LinearHealthResult:
        if not self._api_key:
            return LinearHealthResult(state="not_configured")

        data, error = self._execute(VIEWER_QUERY, {})
        if error:
            state = (
                "authentication_failure"
                if error.code == "authentication"
                else "provider_failure"
            )
            return LinearHealthResult(state=state, error=error)
        viewer = data.get("viewer") if isinstance(data, dict) else None
        if not isinstance(viewer, dict) or not viewer.get("id"):
            return LinearHealthResult(
                state="provider_failure",
                error=_malformed_error("Linear health response did not include a viewer identity."),
            )
        return LinearHealthResult(state="connected")

    def list_projects(self) -> LinearReadResult:
        return self._paginate(PROJECTS_QUERY, "projects", _valid_project)

    def list_issues(self) -> LinearReadResult:
        result = self._paginate(
            ISSUES_QUERY,
            "issues",
            _valid_issue,
            extra_variables={"relationFirst": LINEAR_PAGE_SIZE},
        )
        if result.error:
            return result

        records: list[dict[str, Any]] = []
        for issue in result.records:
            relation_error = self._complete_issue_relations(issue)
            if relation_error:
                return LinearReadResult(records=[], error=relation_error)
            records.append(issue)
        return LinearReadResult(records=records)

    def _paginate(
        self,
        query: str,
        connection_name: str,
        validator,
        *,
        extra_variables: dict[str, Any] | None = None,
    ) -> LinearReadResult:
        if not self._api_key:
            return LinearReadResult(
                records=[],
                error=LinearProviderError(
                    code="not_configured",
                    message="Linear is not configured. Set LINEAR_API_KEY to enable read access.",
                ),
            )

        records: list[dict[str, Any]] = []
        after: str | None = None
        seen_cursors: set[str] = set()
        while True:
            variables = {"first": LINEAR_PAGE_SIZE, "after": after, **(extra_variables or {})}
            data, error = self._execute(query, variables)
            if error:
                return LinearReadResult(records=[], error=error)
            connection = data.get(connection_name) if isinstance(data, dict) else None
            parsed, page_info, error = _parse_connection(connection, connection_name, validator)
            if error:
                return LinearReadResult(records=[], error=error)
            records.extend(parsed)
            if not page_info["hasNextPage"]:
                return LinearReadResult(records=records)
            after = page_info["endCursor"]
            if after in seen_cursors:
                return LinearReadResult(
                    records=[],
                    error=_malformed_error(
                        f"Linear {connection_name} pagination cursor repeated."
                    ),
                )
            seen_cursors.add(after)

    def _complete_issue_relations(self, issue: dict[str, Any]) -> LinearProviderError | None:
        relations = issue["relations"]
        inverse = issue["inverseRelations"]
        relations_after = relations["pageInfo"].get("endCursor") if relations["pageInfo"].get("hasNextPage") else None
        inverse_after = inverse["pageInfo"].get("endCursor") if inverse["pageInfo"].get("hasNextPage") else None
        seen_relations: set[str] = set()
        seen_inverse: set[str] = set()
        if relations_after is not None:
            seen_relations.add(relations_after)
        if inverse_after is not None:
            seen_inverse.add(inverse_after)

        while relations_after is not None or inverse_after is not None:
            data, error = self._execute(
                ISSUE_RELATIONS_QUERY,
                {
                    "id": issue["id"],
                    "first": LINEAR_PAGE_SIZE,
                    "relationsAfter": relations_after,
                    "inverseAfter": inverse_after,
                },
            )
            if error:
                return error
            issue_data = data.get("issue") if isinstance(data, dict) else None
            if not isinstance(issue_data, dict):
                return _malformed_error("Linear issue relation response was incomplete.")
            for name, cursor in (("relations", relations_after), ("inverseRelations", inverse_after)):
                if cursor is None:
                    continue
                parsed, page_info, parse_error = _parse_connection(
                    issue_data.get(name), name, _valid_relation
                )
                if parse_error:
                    return parse_error
                issue[name]["nodes"].extend(parsed)
                next_cursor = page_info["endCursor"] if page_info["hasNextPage"] else None
                if name == "relations":
                    if next_cursor is not None and next_cursor in seen_relations:
                        return _malformed_error(
                            "Linear relations pagination cursor repeated."
                        )
                    if next_cursor is not None:
                        seen_relations.add(next_cursor)
                    relations_after = next_cursor
                else:
                    if next_cursor is not None and next_cursor in seen_inverse:
                        return _malformed_error(
                            "Linear inverseRelations pagination cursor repeated."
                        )
                    if next_cursor is not None:
                        seen_inverse.add(next_cursor)
                    inverse_after = next_cursor
        return None

    def _execute(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> tuple[dict[str, Any], LinearProviderError | None]:
        try:
            response = self._session.post(
                LINEAR_API_URL,
                headers={"Authorization": self._api_key, "Content-Type": "application/json"},
                json={"query": query, "variables": variables},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {401, 403}:
                return {}, LinearProviderError(
                    code="authentication",
                    message="Linear rejected the configured API key or its permissions.",
                    http_status=status,
                )
            return {}, LinearProviderError(
                code="provider",
                message="Linear returned an unsuccessful HTTP response.",
                http_status=status,
            )
        except requests.RequestException as exc:
            return {}, LinearProviderError(
                code="provider",
                message=f"Could not reach Linear: {exc.__class__.__name__}.",
            )

        try:
            payload = response.json()
        except (TypeError, ValueError):
            return {}, _malformed_error("Linear returned a non-JSON response.")
        if not isinstance(payload, dict):
            return {}, _malformed_error("Linear returned an invalid response envelope.")
        errors = payload.get("errors")
        if errors:
            authentication = any(_graphql_auth_error(error) for error in errors if isinstance(error, dict))
            return {}, LinearProviderError(
                code="authentication" if authentication else "provider",
                message=(
                    "Linear rejected the configured API key or its permissions."
                    if authentication
                    else "Linear returned a GraphQL provider error."
                ),
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            return {}, _malformed_error("Linear response did not include GraphQL data.")
        return data, None


def _parse_connection(connection, name: str, validator):
    if not isinstance(connection, dict):
        return [], {}, _malformed_error(f"Linear {name} response was incomplete.")
    nodes = connection.get("nodes")
    page_info = connection.get("pageInfo")
    if not isinstance(nodes, list) or not isinstance(page_info, dict):
        return [], {}, _malformed_error(f"Linear {name} response was incomplete.")
    if not isinstance(page_info.get("hasNextPage"), bool):
        return [], {}, _malformed_error(f"Linear {name} pagination metadata was invalid.")
    if page_info["hasNextPage"] and not page_info.get("endCursor"):
        return [], {}, _malformed_error(f"Linear {name} pagination cursor was missing.")
    if any(not isinstance(node, dict) or not validator(node) for node in nodes):
        return [], {}, _malformed_error(f"Linear {name} contained an incomplete record.")
    return nodes, page_info, None


def _valid_project(project: dict[str, Any]) -> bool:
    return bool(project.get("id") and project.get("name"))


def _valid_issue(issue: dict[str, Any]) -> bool:
    state = issue.get("state")
    return bool(
        issue.get("id")
        and issue.get("identifier")
        and issue.get("title")
        and isinstance(state, dict)
        and state.get("name")
        and state.get("type")
        and _valid_connection(issue.get("relations"))
        and _valid_connection(issue.get("inverseRelations"))
    )


def _valid_relation(relation: dict[str, Any]) -> bool:
    return bool(relation.get("id") and relation.get("type"))


def _valid_connection(connection: Any) -> bool:
    if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
        return False
    page_info = connection.get("pageInfo")
    return bool(
        isinstance(page_info, dict)
        and isinstance(page_info.get("hasNextPage"), bool)
        and (not page_info["hasNextPage"] or page_info.get("endCursor"))
    )


def _graphql_auth_error(error: dict[str, Any]) -> bool:
    extensions = error.get("extensions") if isinstance(error.get("extensions"), dict) else {}
    code = str(extensions.get("code") or "").upper()
    message = str(error.get("message") or "").lower()
    return code in {"AUTHENTICATION_ERROR", "FORBIDDEN", "UNAUTHENTICATED"} or "authentication" in message or "permission" in message


def _malformed_error(message: str) -> LinearProviderError:
    return LinearProviderError(code="malformed_response", message=message)
