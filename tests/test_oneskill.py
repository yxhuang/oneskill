#!/usr/bin/env python3
"""oneskill integration tests; all mutable fixtures live under /tmp."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OSK = ROOT / "bin" / "osk"
CLIENT_PATHS = {
    "claude": (".claude", "skills"),
    "codex": (".codex", "skills"),
    "kimi": (".kimi-code", "skills"),
}


class OneskillIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="oneskill-test-", dir="/tmp")
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.agent = self.base / "agent-env"
        self.manifest = self.base / "skills.json"
        for parts in CLIENT_PATHS.values():
            self.home.joinpath(*parts).mkdir(parents=True)
        (self.home / ".agents" / "skills").mkdir(parents=True)
        self.env = os.environ.copy()
        self.env.update(
            ONESKILL_HOME=str(self.home),
            ONESKILL_LIBRARY=str(self.agent),
            ONESKILL_MANIFEST=str(self.manifest),
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

    def run_osk(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(OSK), *args],
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
        result = self.run_osk("list", "--json")
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
        result = self.run_osk("doctor", "--json")
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
        result = self.run_osk("adopt", str(source), "--yes")
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
        result = self.run_osk("adopt", str(source), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(source.is_dir())
        self.assertFalse(source.is_symlink())
        self.assertEqual(json.loads(self.manifest.read_text())["skills"], [])

    def test_adopt_refusal_aborts_before_any_change(self) -> None:
        self.write_manifest([])
        source = self.client_path("claude", "refuse")
        source.mkdir()
        (source / "SKILL.md").write_text("# keep\n", encoding="utf-8")
        result = self.run_osk("adopt", str(source), input_text="y\nn\n")
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
        first = self.run_osk("sync", "--yes")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertIn("2 changes applied", first.stdout)
        second = self.run_osk("sync", "--yes")
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
        result = self.run_osk("sync", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(conflict.is_symlink())
        backups = list(conflict.parent.glob("conflict.oneskill-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "local.txt").read_text(encoding="utf-8"), "keep")

    def test_list_json_is_clean_json(self) -> None:
        body = self.body("claude/skills/one")
        self.link("claude", "one", body)
        self.write_manifest(
            [{"name": "one", "source": "self", "body": str(body), "scope": ["claude"]}]
        )
        result = self.run_osk("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsInstance(json.loads(result.stdout), dict)
        self.assertEqual(result.stderr, "")

    def test_scan_marks_single_client_for_review(self) -> None:
        body = self.body("kimi/skills/kimi-only")
        self.link("kimi", "kimi-only", body)
        result = self.run_osk("scan", "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["skills"] if item["name"] == "kimi-only")
        self.assertEqual(entry["scope"], ["kimi"])
        self.assertIn("needs review", entry["review"])
        doctor = self.run_osk("doctor", "--json")
        self.assertEqual(doctor.returncode, 1)
        issues = json.loads(doctor.stdout)["issues"]
        self.assertTrue(any(issue["type"] == "scope_review" for issue in issues))

    def test_list_groups_shared_and_attention_sections(self) -> None:
        self.build_audit_fixture()
        result = self.run_osk("list")
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
        result = self.run_osk("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SHARED (all three clients)", result.stdout)
        self.assertNotIn("NEEDS ATTENTION", result.stdout)
        self.assertIn("0 issues", result.stdout)

    def make_unmanaged_fixture(self) -> Path:
        self.agent.mkdir(parents=True, exist_ok=True)  # empty library, as after `osk init`
        real = self.client_path("claude", "my-skill")
        real.mkdir()
        (real / "SKILL.md").write_text("# mine\n", encoding="utf-8")
        return real

    def test_unmanaged_real_dir_suggests_adopt(self) -> None:
        real = self.make_unmanaged_fixture()
        scan = self.run_osk("scan", "--write")
        self.assertEqual(scan.returncode, 0, scan.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["skills"] if item["name"] == "my-skill")
        self.assertIsNone(entry["body"])
        listing = self.run_osk("list", "--json")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        rows = {row["name"]: row for row in json.loads(listing.stdout)["skills"]}
        self.assertEqual(rows["my-skill"]["clients"]["claude"]["state"], "unmanaged")
        doctor = self.run_osk("doctor", "--json")
        self.assertEqual(doctor.returncode, 1)
        issues = json.loads(doctor.stdout)["issues"]
        unmanaged = [issue for issue in issues if issue["type"] == "unmanaged"]
        self.assertEqual(len(unmanaged), 1)
        self.assertIn("osk adopt", unmanaged[0]["suggested_command"])
        self.assertIn(str(real), unmanaged[0]["suggested_command"])
        text_listing = self.run_osk("list")
        self.assertIn("NEEDS ATTENTION", text_listing.stdout)

    def test_doctor_never_suggests_self_referential_link(self) -> None:
        self.build_audit_fixture()
        self.make_unmanaged_fixture()
        doctor = self.run_osk("doctor", "--json")
        self.assertEqual(doctor.returncode, 1)
        issues = json.loads(doctor.stdout)["issues"]
        self.assertTrue(issues)
        for issue in issues:
            for segment in issue["suggested_command"].split("&&"):
                tokens = shlex.split(segment)
                if tokens[:2] == ["ln", "-s"]:
                    self.assertNotEqual(
                        tokens[2],
                        tokens[3],
                        f"self-referential symlink suggested for {issue['skill']}: {segment}",
                    )

    def test_real_shadow_still_reports_real_directory(self) -> None:
        body = self.body("vendor/shadowed")
        self.client_path("claude", "shadowed").mkdir()
        self.link("codex", "shadowed", body)
        self.link("kimi", "shadowed", body)
        self.write_manifest(
            [{"name": "shadowed", "source": "vendor", "body": str(body), "scope": "shared"}]
        )
        doctor = self.run_osk("doctor", "--json")
        self.assertEqual(doctor.returncode, 1)
        issues = json.loads(doctor.stdout)["issues"]
        shadow = [issue for issue in issues if issue["type"] == "real_directory"]
        self.assertEqual(len(shadow), 1)
        self.assertEqual(shadow[0]["client"], "claude")
        self.assertIn("ln -s", shadow[0]["suggested_command"])
        tokens = shlex.split(shadow[0]["suggested_command"].split("&&")[1])
        self.assertEqual(tokens[:2], ["ln", "-s"])
        self.assertNotEqual(tokens[2], tokens[3])
        self.assertEqual(Path(tokens[2]), body)


class OneskillConfigTest(unittest.TestCase):
    """Config-file resolution tests; everything lives under /tmp."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="oneskill-config-test-", dir="/tmp")
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.library = self.base / "library"
        self.manifest = self.base / "skills.json"
        self.config_path = self.home / ".config" / "oneskill" / "config.json"
        for parts in CLIENT_PATHS.values():
            self.home.joinpath(*parts).mkdir(parents=True)
        self.env = os.environ.copy()
        for key in ("ONESKILL_LIBRARY", "ONESKILL_MANIFEST"):
            self.env.pop(key, None)
        self.env["ONESKILL_HOME"] = str(self.home)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_osk(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(OSK), *args],
            env=self.env,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )

    def make_fixture(self, library: Path, manifest: Path) -> None:
        body = library / "claude" / "skills" / "demo"
        body.mkdir(parents=True)
        (body / "SKILL.md").write_text("# demo\n", encoding="utf-8")
        for parts in CLIENT_PATHS.values():
            self.home.joinpath(*parts, "demo").symlink_to(body, target_is_directory=True)
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "skills": [
                        {"name": "demo", "source": "self", "body": str(body), "scope": "shared"}
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_config(self, library: Path, manifest: Path) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps({"library": str(library), "manifest": str(manifest)}) + "\n",
            encoding="utf-8",
        )

    def test_config_file_is_used_when_env_vars_absent(self) -> None:
        self.make_fixture(self.library, self.manifest)
        self.write_config(self.library, self.manifest)
        result = self.run_osk("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["manifest"], str(self.manifest))
        rows = {row["name"]: row for row in payload["skills"]}
        self.assertTrue(all(v["state"] == "healthy" for v in rows["demo"]["clients"].values()))

    def test_env_vars_override_config_file(self) -> None:
        self.make_fixture(self.library, self.manifest)
        # config file points at paths that do not exist; env vars must win
        self.write_config(self.base / "bogus-library", self.base / "bogus-manifest.json")
        self.env["ONESKILL_LIBRARY"] = str(self.library)
        self.env["ONESKILL_MANIFEST"] = str(self.manifest)
        result = self.run_osk("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["manifest"], str(self.manifest))

    def test_missing_library_error_points_to_init(self) -> None:
        self.env["ONESKILL_LIBRARY"] = str(self.base / "no-such-library")
        self.env["ONESKILL_MANIFEST"] = str(self.manifest)
        result = self.run_osk("list")
        self.assertEqual(result.returncode, 2)
        self.assertIn("osk init", result.stderr)

    def test_init_yes_writes_config_with_defaults(self) -> None:
        result = self.run_osk("init", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        default_library = self.home / ".oneskill" / "library"
        self.assertEqual(payload["library"], str(default_library))
        self.assertEqual(
            payload["manifest"], str(self.home / ".config" / "oneskill" / "skills.json")
        )
        self.assertTrue(default_library.is_dir())

    def test_init_refuses_to_overwrite_existing_config(self) -> None:
        self.write_config(self.library, self.manifest)
        before = self.config_path.read_text(encoding="utf-8")
        result = self.run_osk("init", input_text="n\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("left unchanged", result.stdout)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
