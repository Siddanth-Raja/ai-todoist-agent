from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.storage as storage  # noqa: E402
from app.project_registry import project_registry_service  # noqa: E402


LINEAR_PROJECT_MAPPINGS = {
    "pcos": "8622937e-f05d-48b7-ba54-43604a8aa733",
    "xo": "6752d640-2f40-423f-b86f-ef11e0c4deda",
    "nebulo": "d9fdfe44-3e66-4dc0-b564-b2bcb646e635",
    "freelance": "2bde590c-a8ab-4f4e-81eb-f7a8da8c1833",
}


class ProjectRegistryStorageTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "app.sqlite3")
        self.env_patch = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        storage.ensure_database()

    def test_seeded_registry_is_idempotent_and_excludes_system_state(self):
        first = storage.list_canonical_projects(include_disabled=True)
        first_ids = {project["key"]: project["id"] for project in first}
        first_counts = self._registry_table_counts()
        storage.update_canonical_project(
            first_ids["nebulo"],
            {"display_name": "Nebulo Custom"},
        )

        storage._INITIALIZED_PATHS.discard(self.db_path)
        storage.ensure_database()

        second = storage.list_canonical_projects(include_disabled=True)
        self.assertEqual(first_ids, {project["key"]: project["id"] for project in second})
        self.assertEqual(first_counts, self._registry_table_counts())
        self.assertEqual(
            storage.get_canonical_project("nebulo")["display_name"],
            "Nebulo Custom",
        )
        self.assertEqual(
            list(first_ids),
            ["pcos-ai-todoist-agent", "nebulo", "xo", "freelance", "am", "personal"],
        )
        self.assertNotIn("needs-classification", first_ids)

        snapshot = project_registry_service.snapshot()
        needs_classification = snapshot.get_project_definition("Needs Classification")
        self.assertTrue(needs_classification["system_state"])
        self.assertIsNone(needs_classification["canonical_project_id"])

    def test_create_update_and_alias_resolution_support_future_projects(self):
        created = storage.create_canonical_project(
            key="Studio Launch",
            display_name="Studio Launch",
            description="A future normal project.",
            aliases=["studio", "launch work"],
            classification_hints=[
                {"type": "keyword", "value": "studio launch"},
                {"type": "person", "value": "Taylor"},
            ],
            provider_mappings=[
                {
                    "provider": "github",
                    "resource_type": "repository",
                    "provider_ref": "Siddanth-Raja/studio-launch",
                    "metadata": {"default_branch": "main"},
                }
            ],
        )

        self.assertEqual(created["key"], "studio-launch")
        self.assertTrue(created["enabled"])
        self.assertEqual(storage.get_canonical_project("studio")["id"], created["id"])
        self.assertEqual(
            storage.resolve_canonical_project_provider_mapping(
                provider="github",
                resource_type="repository",
                provider_ref="Siddanth-Raja/studio-launch",
            )["id"],
            created["id"],
        )
        snapshot = project_registry_service.snapshot()
        self.assertEqual(snapshot.resolve_key("launch work"), "studio-launch")
        self.assertEqual(
            snapshot.get_project_definition("studio")["people"],
            ("Taylor",),
        )

        updated = storage.update_canonical_project(created["id"], {"enabled": False})
        self.assertFalse(updated["enabled"])
        self.assertNotIn(
            "studio-launch",
            [project["key"] for project in storage.list_canonical_projects()],
        )
        self.assertIn(
            "studio-launch",
            [
                project["key"]
                for project in storage.list_canonical_projects(include_disabled=True)
            ],
        )

    def test_provider_mapping_resolves_to_durable_project_reference(self):
        pcos = storage.get_canonical_project("pcos")
        with_linear = storage.add_canonical_project_provider_mapping(
            pcos["id"],
            provider="linear",
            resource_type="project",
            provider_ref="linear-project-pcos",
            metadata={"workspace": "siddanths-workspace"},
        )
        with_repository = storage.add_canonical_project_provider_mapping(
            pcos["id"],
            provider="github",
            resource_type="repository",
            provider_ref="Siddanth-Raja/ai-todoist-agent",
        )

        self.assertEqual(with_linear["id"], pcos["id"])
        self.assertEqual(with_repository["id"], pcos["id"])
        resolved = storage.resolve_canonical_project_provider_mapping(
            provider="linear",
            resource_type="project",
            provider_ref="linear-project-pcos",
        )
        self.assertEqual(resolved["id"], pcos["id"])
        mapping = next(
            item
            for item in resolved["provider_mappings"]
            if item["provider"] == "linear"
            and item["provider_ref"] == "linear-project-pcos"
        )
        self.assertEqual(mapping["metadata"], {"workspace": "siddanths-workspace"})

    def test_exact_linear_project_mappings_are_seeded_and_resolve(self):
        snapshot = project_registry_service.snapshot()
        for canonical_reference, linear_uuid in LINEAR_PROJECT_MAPPINGS.items():
            project = storage.get_canonical_project(canonical_reference)
            self.assertIsNotNone(project)
            self.assertEqual(
                storage.resolve_canonical_project_provider_mapping(
                    provider="linear",
                    resource_type="project",
                    provider_ref=linear_uuid,
                )["id"],
                project["id"],
            )
            self.assertEqual(
                snapshot.resolve_provider_project_id(
                    provider="linear",
                    resource_type="project",
                    provider_ref=linear_uuid,
                ),
                project["id"],
            )
            diagnostic = snapshot.diagnose_provider_mapping(
                provider="linear",
                resource_type="project",
                provider_ref=linear_uuid,
            )
            self.assertEqual(diagnostic.status, "mapped")
            self.assertEqual(diagnostic.canonical_project_id, project["id"])
            canonical_diagnostic = snapshot.diagnose_canonical_project_mapping(
                canonical_reference,
                provider="linear",
                resource_type="project",
            )
            self.assertEqual(canonical_diagnostic.status, "mapped")
            self.assertEqual(canonical_diagnostic.provider_ref, linear_uuid)

        linear_mappings = [
            mapping
            for project in storage.list_canonical_projects(include_disabled=True)
            for mapping in project["provider_mappings"]
            if mapping["provider"] == "linear"
            and mapping["resource_type"] == "project"
        ]
        self.assertEqual(len(linear_mappings), 4)

    def test_linear_mapping_edit_is_durable_and_seed_initialization_is_idempotent(self):
        original_uuid = LINEAR_PROJECT_MAPPINGS["pcos"]
        pcos = storage.get_canonical_project("pcos")
        mapping = next(
            item
            for item in pcos["provider_mappings"]
            if item["provider"] == "linear" and item["resource_type"] == "project"
        )
        replacement_uuid = "00000000-0000-4000-8000-000000000134"
        updated = storage.update_canonical_project_provider_mapping(
            mapping["id"],
            {
                "provider_ref": replacement_uuid,
                "metadata": {"source": "user-edit"},
            },
        )
        self.assertEqual(updated["provider_ref"], replacement_uuid)
        self.assertEqual(updated["metadata"], {"source": "user-edit"})
        self.assertIsNone(
            storage.resolve_canonical_project_provider_mapping(
                provider="linear",
                resource_type="project",
                provider_ref=original_uuid,
            )
        )
        self.assertEqual(
            storage.resolve_canonical_project_provider_mapping(
                provider="linear",
                resource_type="project",
                provider_ref=replacement_uuid,
            )["id"],
            pcos["id"],
        )

        before_counts = self._registry_table_counts()
        storage._INITIALIZED_PATHS.discard(self.db_path)
        storage.ensure_database()
        self.assertEqual(before_counts, self._registry_table_counts())
        persisted = storage.get_canonical_project_provider_mapping(mapping["id"])
        self.assertEqual(persisted["provider_ref"], replacement_uuid)
        self.assertEqual(persisted["metadata"], {"source": "user-edit"})

    def test_linear_mapping_resolution_uses_uuid_not_project_name(self):
        snapshot = project_registry_service.snapshot()
        pcos = storage.get_canonical_project("pcos")
        renamed_provider_project = {
            "id": LINEAR_PROJECT_MAPPINGS["pcos"],
            "name": "Renamed after mapping",
        }
        duplicate_name_provider_project = {
            "id": "00000000-0000-4000-8000-000000000999",
            "name": "PCOS / ai todoist agent",
        }

        self.assertEqual(
            snapshot.resolve_provider_project_id(
                provider="linear",
                resource_type="project",
                provider_ref=renamed_provider_project["id"],
            ),
            pcos["id"],
        )
        self.assertIsNone(
            snapshot.resolve_provider_project_id(
                provider="linear",
                resource_type="project",
                provider_ref=duplicate_name_provider_project["id"],
            )
        )
        self.assertEqual(len(storage.list_canonical_projects(include_disabled=True)), 6)

    def test_linear_mapping_diagnostics_distinguish_unknown_states(self):
        snapshot = project_registry_service.snapshot()
        unmapped_uuid = "00000000-0000-4000-8000-000000000000"
        unmapped = snapshot.diagnose_provider_mapping(
            provider="linear",
            resource_type="project",
            provider_ref=unmapped_uuid,
        )
        self.assertEqual(unmapped.status, "unmapped_provider_ref")
        self.assertIsNone(unmapped.canonical_project_id)

        unknown = snapshot.diagnose_canonical_project_mapping(
            "does-not-exist",
            provider="linear",
            resource_type="project",
        )
        self.assertEqual(unknown.status, "unknown_canonical_project")

        for project_reference in ("am", "personal"):
            project = storage.get_canonical_project(project_reference)
            self.assertFalse(
                any(
                    mapping["provider"] == "linear"
                    for mapping in project["provider_mappings"]
                )
            )
            diagnostic = snapshot.diagnose_canonical_project_mapping(
                project_reference,
                provider="linear",
                resource_type="project",
            )
            self.assertEqual(diagnostic.status, "canonical_project_unmapped")
        needs_classification = snapshot.diagnose_canonical_project_mapping(
            "Needs Classification",
            provider="linear",
            resource_type="project",
        )
        self.assertEqual(
            needs_classification.status,
            "unknown_canonical_project",
        )

    def test_existing_todoist_mappings_remain_intact(self):
        expected = {
            "Nebulo": "nebulo",
            "XO Collective": "xo",
            "Freelance Web Design": "freelance",
            "College": "am",
            "Personal": "personal",
        }
        snapshot = project_registry_service.snapshot()
        for section, canonical_reference in expected.items():
            project = storage.get_canonical_project(canonical_reference)
            self.assertEqual(
                snapshot.resolve_provider_project_id(
                    provider="todoist",
                    resource_type="section",
                    provider_ref=section,
                ),
                project["id"],
            )

    def test_needs_classification_cannot_be_created_as_normal_project(self):
        with self.assertRaisesRegex(ValueError, "system state"):
            storage.create_canonical_project(
                key="needs-classification",
                display_name="Needs Classification",
            )

    def _registry_table_counts(self) -> dict[str, int]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "canonical_projects",
                    "canonical_project_aliases",
                    "canonical_project_classification_hints",
                    "canonical_project_provider_mappings",
                )
            }


if __name__ == "__main__":
    unittest.main()
