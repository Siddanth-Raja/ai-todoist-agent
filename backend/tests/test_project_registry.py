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
            item for item in resolved["provider_mappings"] if item["provider"] == "linear"
        )
        self.assertEqual(mapping["metadata"], {"workspace": "siddanths-workspace"})

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
