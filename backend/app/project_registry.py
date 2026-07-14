from dataclasses import dataclass
import re
from typing import Any, Literal

from .storage import list_canonical_projects


NEEDS_CLASSIFICATION_KEY = "needs-classification"
NEEDS_CLASSIFICATION_ALIASES = (
    "needs-classification",
    "needs classification",
    "uncategorized",
)


@dataclass(frozen=True)
class ProviderMappingDiagnostic:
    status: Literal[
        "mapped",
        "unmapped_provider_ref",
        "canonical_project_unmapped",
        "unknown_canonical_project",
    ]
    provider: str
    resource_type: str
    provider_ref: str | None = None
    canonical_project_id: str | None = None
    canonical_project_key: str | None = None
    mapping_id: str | None = None


@dataclass(frozen=True)
class ProjectRegistrySnapshot:
    projects: tuple[dict[str, Any], ...]
    aliases: dict[str, str]

    def resolve_key(self, project_reference: str) -> str:
        normalized = normalize_project_reference(project_reference)
        return self.aliases.get(normalized, normalized)

    def get_project_definition(self, project_reference: str) -> dict[str, Any] | None:
        canonical_key = self.resolve_key(project_reference)
        return next(
            (project for project in self.projects if project["key"] == canonical_key),
            None,
        )

    def resolve_provider_project_id(
        self,
        *,
        provider: str,
        resource_type: str,
        provider_ref: str,
    ) -> str | None:
        for project in self.projects:
            canonical_project_id = project.get("canonical_project_id")
            if canonical_project_id is None:
                continue
            for mapping in project.get("provider_mappings", ()):
                if not mapping.get("enabled", True):
                    continue
                if _mapping_matches(
                    mapping,
                    provider=provider,
                    resource_type=resource_type,
                    provider_ref=provider_ref,
                ):
                    return str(canonical_project_id)
        return None

    def diagnose_provider_mapping(
        self,
        *,
        provider: str,
        resource_type: str,
        provider_ref: str,
    ) -> ProviderMappingDiagnostic:
        for project in self.projects:
            canonical_project_id = project.get("canonical_project_id")
            if canonical_project_id is None:
                continue
            for mapping in project.get("provider_mappings", ()):
                if not mapping.get("enabled", True):
                    continue
                if _mapping_matches(
                    mapping,
                    provider=provider,
                    resource_type=resource_type,
                    provider_ref=provider_ref,
                ):
                    return ProviderMappingDiagnostic(
                        status="mapped",
                        provider=provider,
                        resource_type=resource_type,
                        provider_ref=provider_ref,
                        canonical_project_id=str(canonical_project_id),
                        canonical_project_key=str(project["key"]),
                        mapping_id=str(mapping["id"]),
                    )
        return ProviderMappingDiagnostic(
            status="unmapped_provider_ref",
            provider=provider,
            resource_type=resource_type,
            provider_ref=provider_ref,
        )

    def diagnose_canonical_project_mapping(
        self,
        project_reference: str,
        *,
        provider: str,
        resource_type: str,
    ) -> ProviderMappingDiagnostic:
        project = self.get_project_definition(project_reference)
        if project is None or project.get("canonical_project_id") is None:
            return ProviderMappingDiagnostic(
                status="unknown_canonical_project",
                provider=provider,
                resource_type=resource_type,
                canonical_project_key=self.resolve_key(project_reference),
            )
        for mapping in project.get("provider_mappings", ()):
            if not mapping.get("enabled", True):
                continue
            if _mapping_matches(
                mapping,
                provider=provider,
                resource_type=resource_type,
            ):
                return ProviderMappingDiagnostic(
                    status="mapped",
                    provider=provider,
                    resource_type=resource_type,
                    provider_ref=str(mapping["provider_ref"]),
                    canonical_project_id=str(project["canonical_project_id"]),
                    canonical_project_key=str(project["key"]),
                    mapping_id=str(mapping["id"]),
                )
        return ProviderMappingDiagnostic(
            status="canonical_project_unmapped",
            provider=provider,
            resource_type=resource_type,
            canonical_project_id=str(project["canonical_project_id"]),
            canonical_project_key=str(project["key"]),
        )


class ProjectRegistryService:
    def snapshot(self) -> ProjectRegistrySnapshot:
        stored_projects = list_canonical_projects()
        definitions = tuple(self._project_definition(project) for project in stored_projects)
        projects = (*definitions, self._needs_classification_definition())
        aliases: dict[str, str] = {
            normalize_project_reference(project["key"]): project["key"]
            for project in projects
        }
        for project in stored_projects:
            for alias in project["aliases"]:
                aliases[str(alias["normalized_alias"])] = str(project["key"])
        for alias in NEEDS_CLASSIFICATION_ALIASES:
            aliases[normalize_project_reference(alias)] = NEEDS_CLASSIFICATION_KEY
        return ProjectRegistrySnapshot(projects=projects, aliases=aliases)

    @staticmethod
    def _project_definition(project: dict[str, Any]) -> dict[str, Any]:
        hints_by_type: dict[str, list[str]] = {
            "life_area": [],
            "keyword": [],
            "person": [],
        }
        for hint in project["classification_hints"]:
            hints_by_type[str(hint["type"])].append(str(hint["value"]))
        life_areas = hints_by_type["life_area"]
        return {
            "canonical_project_id": project["id"],
            "key": project["key"],
            "name": project["display_name"],
            "description": project["description"],
            "life_area": life_areas[0] if life_areas else None,
            "keywords": tuple(hints_by_type["keyword"]),
            "people": tuple(hints_by_type["person"]),
            "provider_mappings": tuple(project["provider_mappings"]),
            "system_state": False,
        }

    @staticmethod
    def _needs_classification_definition() -> dict[str, Any]:
        return {
            "canonical_project_id": None,
            "key": NEEDS_CLASSIFICATION_KEY,
            "name": "Needs Classification",
            "description": "Unclassified Todoist work that needs a project decision before it can be safely hidden or routed.",
            "life_area": "Misc",
            "keywords": (),
            "people": (),
            "provider_mappings": (),
            "classification_bucket": True,
            "system_state": True,
        }


def normalize_project_reference(value: str) -> str:
    text = value.lower().replace("&", " and ")
    text = text.replace("_", " ").replace("-", " ")
    return "-".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _mapping_matches(
    mapping: dict[str, Any],
    *,
    provider: str,
    resource_type: str,
    provider_ref: str | None = None,
) -> bool:
    if str(mapping.get("provider") or "").lower() != provider.lower():
        return False
    if str(mapping.get("resource_type") or "").lower() != resource_type.lower():
        return False
    return provider_ref is None or str(mapping.get("provider_ref") or "") == provider_ref


project_registry_service = ProjectRegistryService()
