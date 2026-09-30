"""Contracts for the standalone live-integration check, without starting servers."""

from fnmatch import fnmatchcase
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[4]


class LiveIntegrationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # BaseLoader preserves GitHub's YAML `on` key rather than YAML 1.1 booleans.
        cls.workflow = yaml.load(
            (ROOT / ".github/workflows/live-integration.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )

    def test_changed_workflow_and_relevant_application_paths_trigger(self):
        paths = self.workflow["on"]["pull_request"]["paths"]
        # All patterns used here are exact paths or positive prefix globs.
        for changed in (
            ".github/workflows/live-integration.yml",
            "apps/api/routes/build_public.py",
            "apps/api/routes/runtime_settings.py",
            "packages/story_core/opening_build/execution.py",
            "packages/story_core/file_project_store.py",
            "apps/web/app/projects/[id]/build/page.tsx",
            "apps/web/app/projects/[id]/write/page.tsx",
            "apps/web/app/projects/new/page.tsx",
            "apps/web/components/ws/WorkspaceShell.tsx",
            "apps/web/lib/api.ts",
            "apps/web/playwright.integration.config.ts",
            "apps/web/tests/integration/seed_end_of_volume.py",
            "tests/story_core/test_ongoing_planning.py",
            "tests/story_core/test_opening_build.py",
            "tests/story_core/test_world_build_graph.py",
            "tests/story_core/test_outline_planning.py",
            "apps/web/package-lock.json",
            "uv.lock",
        ):
            with self.subTest(changed=changed):
                self.assertTrue(any(fnmatchcase(changed, pattern) for pattern in paths))

    def test_docs_only_and_unrelated_tests_do_not_trigger(self):
        paths = self.workflow["on"]["pull_request"]["paths"]
        for changed in (
            "README.md",
            "docs/architecture.md",
            "docs/live-api-browser-integration.md",
            "tests/story_core/test_unrelated_feature.py",
            "apps/web/tests/config-page.spec.ts",
        ):
            with self.subTest(changed=changed):
                self.assertFalse(any(fnmatchcase(changed, pattern) for pattern in paths))

    def test_main_has_same_risk_filter_and_pr_cancellation_is_separate(self):
        events = self.workflow["on"]
        self.assertEqual(events["push"]["branches"], ["main"])
        self.assertEqual(events["push"]["paths"], events["pull_request"]["paths"])
        self.assertNotIn("pull_request_target", events)
        self.assertEqual(
            self.workflow["concurrency"]["cancel-in-progress"],
            "${{ github.event_name == 'pull_request' }}",
        )
        self.assertIn("github.run_id", self.workflow["concurrency"]["group"])

    def test_check_runs_only_dedicated_suite_and_propagates_failure(self):
        self.assertEqual(set(self.workflow["jobs"]), {"live-integration"})
        job = self.workflow["jobs"]["live-integration"]
        self.assertNotIn("continue-on-error", job)
        self.assertNotIn("env", self.workflow)
        self.assertEqual(job["env"]["NOVELFLOW_E2E_SYNTHETIC"], "1")
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        runs = [step["run"] for step in job["steps"] if "run" in step]
        for step in job["steps"]:
            self.assertNotIn("continue-on-error", step)
        command = next(run for run in runs if "playwright test" in run)
        self.assertIn("uv run --project ../..", command)
        self.assertIn("--config=playwright.integration.config.ts", command)
        self.assertNotIn("||", command)
        self.assertNotIn("pytest", "\n".join(runs))
        self.assertNotIn("npm run build", "\n".join(runs))
        self.assertNotIn("secrets.", str(self.workflow))

    def test_run_root_and_existing_server_guards_are_preserved(self):
        steps = self.workflow["jobs"]["live-integration"]["steps"]
        allocation = next(step["run"] for step in steps if "mktemp" in step.get("run", ""))
        self.assertIn("RUNNER_TEMP", allocation)
        self.assertIn("INTEGRATION_RUN_ROOT", allocation)
        self.assertIn("GITHUB_ENV", allocation)
        artifact = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertIn("always()", artifact["if"])
        self.assertIn("/logs/", artifact["with"]["path"])
        self.assertIn("/playwright-output/", artifact["with"]["path"])
        config = (ROOT / "apps/web/playwright.integration.config.ts").read_text(encoding="utf-8")
        self.assertEqual(config.count("reuseExistingServer: false"), 2)


if __name__ == "__main__":
    unittest.main()
