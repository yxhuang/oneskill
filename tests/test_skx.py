#!/usr/bin/env python3
"""skx integration tests; all mutable fixtures live under /tmp."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKX = ROOT / "bin" / "skx"
CLIENT_PATHS = {
    "claude": (".claude", "skills"),
    "codex": (".codex", "skills"),
    "kimi": (".kimi-code", "skills"),
}


class SkxIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="skx-test-", dir="/tmp")
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.agent = self.base / "agent-env"
        self.manifest = self.base / "skills.json"
        for parts in CLIENT_PATHS.values():
            self.home.joinpath(*parts).mkdir(parents=True)
        (self.home / ".agents" / "skills").mkdir(parents=True)
        self.env = os.environ.copy()
        self.env.update(
            SKX_HOME=str(self.home),
            SKX_AGENT_ENV=str(self.agent),
            SKX_MANIFEST=str(self.manifest),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def client_path(self, client: str, name: str) -> Path:
        return self.home.joinpath(*CLIENT_PATHS[client], name)

    def body(self, relative: str) -> Path:
        path = self.agent / relative
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"# {path.name}\n", encoding="utf-8")
        return path

    def link(self, client: str, name: str, target: Path) -> None:
        self.client_path(client, name).symlink_to(target, target_is_directory=True)

    def write_manifest(self, entries: list[dict[str, object]]) -> None:
        self.manifest.write_text(
            json.dumps({"version": 1, "skills": entries}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_skx(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SKX), *args],
            env=self.env,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )

    def build_audit_fixture(self) -> None:
        healthy = self.body("claude/skills/healthy")
        missing = self.body("claude/skills/missing")
        shadow = self.body("vendor/shadow")
        broken_expected = self.body("claude/skills/broken")
        for client in CLIENT_PATHS:
            self.link(client, "healthy", healthy)
        self.link("claude", "missing", missing)
        self.client_path("claude", "shadow").mkdir()
        self.link("codex", "shadow", shadow)
        self.link("kimi", "shadow", shadow)
        nonexistent = self.base / "does-not-exist"
        self.link("claude", "broken", nonexistent)
        self.link("codex", "broken", broken_expected)
        self.link("kimi", "broken", broken_expected)
        self.client_path("codex", "unmanaged").mkdir()
        self.write_manifest(
            [
                {"name": "healthy", "source": "self", "body": str(healthy), "scope": "shared"},
                {"name": "missing", "source": "self", "body": str(missing), "scope": "shared"},
                {"name": "shadow", "source": "vendor", "body": str(shadow), "scope": "shared"},
                {"name": "broken", "source": "self", "body": str(broken_expected), "scope": "shared"},
            ]
        )

    def test_list_covers_healthy_missing_shadow_and_broken(self) -> None:
        self.build_audit_fixture()
        result = self.run_skx("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        rows = {row["name"]: row for row in payload["skills"]}
        self.assertTrue(all(v["state"] == "healthy" for v in rows["healthy"]["clients"].values()))
        self.assertEqual(rows["missing"]["clients"]["codex"]["state"], "missing")
        self.assertEqual(rows["missing"]["clients"]["kimi"]["state"], "missing")
        self.assertEqual(rows["shadow"]["clients"]["claude"]["state"], "real_directory")
        self.assertEqual(rows["broken"]["clients"]["claude"]["state"], "orphan_link")

    def test_doctor_detects_required_anomalies(self) -> None:
        self.build_audit_fixture()
        result = self.run_skx("doctor", "--json")
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        kinds = {issue["type"] for issue in report["issues"]}
        self.assertTrue({"missing", "real_directory", "orphan_link", "extra"} <= kinds)
        self.assertTrue(all(issue["suggested_command"] for issue in report["issues"]))

    def test_adopt_moves_links_and_updates_manifest(self) -> None:
        self.write_manifest([])
        source = self.client_path("codex", "new-skill")
        source.mkdir()
        (source / "SKILL.md").write_text("# new\n", encoding="utf-8")
        result = self.run_skx("adopt", str(source), "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        body = self.agent / "codex" / "skills" / "new-skill"
        self.assertTrue((body / "SKILL.md").is_file())
        for client in CLIENT_PATHS:
            link = self.client_path(client, "new-skill")
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), body.resolve())
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"][0]["name"], "new-skill")
        self.assertEqual(manifest["skills"][0]["scope"], "shared")

    def test_adopt_dry_run_changes_nothing(self) -> None:
        self.write_manifest([])
        source = self.client_path("claude", "dry")
        source.mkdir()
        result = self.run_skx("adopt", str(source), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(source.is_dir())
        self.assertFalse(source.is_symlink())
        self.assertEqual(json.loads(self.manifest.read_text())["skills"], [])

    def test_adopt_refusal_aborts_before_any_change(self) -> None:
        self.write_manifest([])
        source = self.client_path("claude", "refuse")
        source.mkdir()
        (source / "SKILL.md").write_text("# keep\n", encoding="utf-8")
        result = self.run_skx("adopt", str(source), input_text="y\nn\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no changes were made", result.stdout)
        self.assertTrue(source.is_dir())
        self.assertFalse(source.is_symlink())
        self.assertFalse((self.agent / "claude" / "skills" / "refuse").exists())
        self.assertEqual(json.loads(self.manifest.read_text())["skills"], [])

    def test_sync_is_idempotent(self) -> None:
        body = self.body("vendor/sync-me")
        self.link("claude", "sync-me", body)
        self.write_manifest(
            [{"name": "sync-me", "source": "vendor", "body": str(body), "scope": "shared"}]
        )
        first = self.run_skx("sync", "--yes")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertIn("2 changes applied", first.stdout)
        second = self.run_skx("sync", "--yes")
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertIn("no changes", second.stdout)

    def test_sync_backs_up_real_directory_after_confirmation(self) -> None:
        body = self.body("vendor/conflict")
        conflict = self.client_path("claude", "conflict")
        conflict.mkdir()
        (conflict / "local.txt").write_text("keep", encoding="utf-8")
        self.write_manifest(
            [{"name": "conflict", "source": "vendor", "body": str(body), "scope": ["claude"]}]
        )
        result = self.run_skx("sync", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(conflict.is_symlink())
        backups = list(conflict.parent.glob("conflict.skx-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "local.txt").read_text(encoding="utf-8"), "keep")

    def test_list_json_is_clean_json(self) -> None:
        body = self.body("claude/skills/one")
        self.link("claude", "one", body)
        self.write_manifest(
            [{"name": "one", "source": "self", "body": str(body), "scope": ["claude"]}]
        )
        result = self.run_skx("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsInstance(json.loads(result.stdout), dict)
        self.assertEqual(result.stderr, "")

    def test_scan_marks_single_client_for_review(self) -> None:
        body = self.body("kimi/skills/kimi-only")
        self.link("kimi", "kimi-only", body)
        result = self.run_skx("scan", "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["skills"] if item["name"] == "kimi-only")
        self.assertEqual(entry["scope"], ["kimi"])
        self.assertIn("needs review", entry["review"])
        doctor = self.run_skx("doctor", "--json")
        self.assertEqual(doctor.returncode, 1)
        issues = json.loads(doctor.stdout)["issues"]
        self.assertTrue(any(issue["type"] == "scope_review" for issue in issues))

    def test_list_groups_shared_and_attention_sections(self) -> None:
        self.build_audit_fixture()
        result = self.run_skx("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("SHARED (all three clients)", out)
        self.assertIn("NEEDS ATTENTION", out)
        shared_pos = out.index("SHARED (all three clients)")
        attention_pos = out.index("NEEDS ATTENTION")
        self.assertLess(shared_pos, attention_pos)
        shared_section = out[shared_pos:attention_pos]
        attention_section = out[attention_pos:]
        self.assertIn("healthy", shared_section)
        self.assertNotIn("shadow", shared_section)
        self.assertIn("shadow", attention_section)
        self.assertIn("broken", attention_section)

    def test_list_hides_attention_section_when_clean(self) -> None:
        body = self.body("claude/skills/tidy")
        for client in CLIENT_PATHS:
            self.link(client, "tidy", body)
        self.write_manifest(
            [{"name": "tidy", "source": "self", "body": str(body), "scope": "shared"}]
        )
        result = self.run_skx("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SHARED (all three clients)", result.stdout)
        self.assertNotIn("NEEDS ATTENTION", result.stdout)
        self.assertIn("0 issues", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
