#!/usr/bin/env python3
"""oneskill integration tests; all mutable fixtures live under /tmp."""

from __future__ import annotations

import io
import importlib.machinery
import importlib.util
import json
import os
import shlex
import subprocess
import tarfile
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
OSK = ROOT / "bin" / "osk"
CLIENT_PATHS = {
    "claude": (".claude", "skills"),
    "codex": (".codex", "skills"),
    "kimi": (".kimi-code", "skills"),
}


def load_osk_module():
    loader = importlib.machinery.SourceFileLoader("oneskill_cli_test", str(OSK))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("cannot load bin/osk for rollback testing")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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

    def client_backups(self, client: str, name: str) -> list[Path]:
        return list(
            (self.home / ".oneskill" / "backups" / client).glob(
                f"{name}.oneskill-backup-*"
            )
        )

    def assert_no_client_backups(self) -> None:
        for client in CLIENT_PATHS:
            skill_dir = self.home.joinpath(*CLIENT_PATHS[client])
            self.assertEqual(list(skill_dir.glob("*.oneskill-backup*")), [])

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

    def remote_fixture(
        self, name: str = "remote-demo", description: str = "A remote test skill."
    ) -> Path:
        fixture = self.base / "fixtures" / name
        fixture.mkdir(parents=True)
        (fixture / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
        (fixture / "payload.txt").write_text("version one\n", encoding="utf-8")
        return fixture

    def install_remote(self, fixture: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        self.agent.mkdir(parents=True, exist_ok=True)
        return self.run_osk("install", str(fixture), "--yes", *extra)

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

    def test_adopt_merges_duplicate_into_external_backup_without_extra(self) -> None:
        self.write_manifest([])
        source = self.client_path("claude", "duplicate")
        source.mkdir()
        (source / "SKILL.md").write_text("# canonical\n", encoding="utf-8")
        conflict = self.client_path("codex", "duplicate")
        conflict.mkdir()
        (conflict / "SKILL.md").write_text("# redundant\n", encoding="utf-8")

        result = self.run_osk("adopt", str(source), "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        backups = self.client_backups("codex", "duplicate")
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "SKILL.md").read_text(), "# redundant\n")
        self.assert_no_client_backups()
        listing = self.run_osk("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertNotIn("! extra", listing.stdout)
        self.assertIn("0 issues", listing.stdout)

    def test_adopt_failure_restores_external_backup(self) -> None:
        self.write_manifest([])
        source = self.client_path("claude", "rollback")
        source.mkdir()
        (source / "source.txt").write_text("source", encoding="utf-8")
        conflict = self.client_path("codex", "rollback")
        conflict.mkdir()
        (conflict / "conflict.txt").write_text("conflict", encoding="utf-8")
        osk = load_osk_module()
        cfg = {
            "home": self.home,
            "library": self.agent,
            "manifest": self.manifest,
            **{
                client: self.home.joinpath(*parts)
                for client, parts in CLIENT_PATHS.items()
            },
        }
        args = SimpleNamespace(
            path=str(source), vendor=False, scope="shared", yes=True, dry_run=False
        )

        with redirect_stdout(io.StringIO()):
            with mock.patch.object(osk, "write_manifest", side_effect=OSError("forced failure")):
                with self.assertRaises(osk.OneskillError):
                    osk.command_adopt_one(args, cfg)

        self.assertFalse(source.is_symlink())
        self.assertEqual((source / "source.txt").read_text(), "source")
        self.assertFalse(conflict.is_symlink())
        self.assertEqual((conflict / "conflict.txt").read_text(), "conflict")
        self.assertFalse((self.agent / "claude" / "skills" / "rollback").exists())
        self.assertEqual(self.client_backups("codex", "rollback"), [])
        self.assert_no_client_backups()

    def test_adopt_all_adopts_each_name_once_and_cleans_inventory(self) -> None:
        self.agent.mkdir(parents=True)
        fixtures = [
            ("claude", "alpha", "alpha"),
            ("kimi", "beta", "beta"),
            ("claude", "duplicate", "canonical"),
            ("codex", "duplicate", "redundant"),
        ]
        for client, name, content in fixtures:
            path = self.client_path(client, name)
            path.mkdir()
            (path / "SKILL.md").write_text(content, encoding="utf-8")
        scan = self.run_osk("scan", "--write")
        self.assertEqual(scan.returncode, 0, scan.stderr)

        preview = self.run_osk("adopt", "--all", "--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr + preview.stdout)
        self.assertIn("3 skill(s) planned, none applied", preview.stdout)
        self.assertFalse(self.client_path("claude", "alpha").is_symlink())
        self.assertIsNone(
            next(
                item
                for item in json.loads(self.manifest.read_text())["skills"]
                if item["name"] == "alpha"
            )["body"]
        )

        result = self.run_osk("adopt", "--all", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.count("adopted: duplicate"), 1)
        self.assertIn("adopt --all complete: 3 skill(s) adopted", result.stdout)
        listing = self.run_osk("list", "--json")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        payload = json.loads(listing.stdout)
        self.assertEqual(payload["summary"]["skills"], 3)
        self.assertEqual(payload["summary"]["three_client_healthy"], 3)
        self.assertEqual(payload["summary"]["anomalies"], 0)
        self.assert_no_client_backups()
        backups = self.client_backups("codex", "duplicate")
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "SKILL.md").read_text(), "redundant")

    def test_doctor_deduplicates_same_name_unmanaged_suggestion(self) -> None:
        self.agent.mkdir(parents=True)
        for client in ("claude", "codex"):
            path = self.client_path(client, "duplicate")
            path.mkdir()
            (path / "SKILL.md").write_text(client, encoding="utf-8")
        scan = self.run_osk("scan", "--write")
        self.assertEqual(scan.returncode, 0, scan.stderr)

        doctor = self.run_osk("doctor", "--json")
        self.assertEqual(doctor.returncode, 1)
        report = json.loads(doctor.stdout)
        unmanaged = [issue for issue in report["issues"] if issue["type"] == "unmanaged"]
        self.assertEqual(len(unmanaged), 1)
        self.assertEqual(unmanaged[0]["client"], "claude")
        self.assertEqual(unmanaged[0]["duplicate_clients"], ["codex"])
        self.assertIn("will be merged and backed up", unmanaged[0]["message"])
        self.assertEqual(report["summary"]["by_type"]["unmanaged"], 1)

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
        backups = self.client_backups("claude", "conflict")
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "local.txt").read_text(encoding="utf-8"), "keep")
        self.assert_no_client_backups()
        listing = self.run_osk("list")
        self.assertNotIn("! extra", listing.stdout)

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

    def test_prune_backups_keeps_requested_number(self) -> None:
        osk = load_osk_module()
        body = self.body("shared/big-skill")
        stamps = ["20260101-000000", "20260202-000000", "20260303-000000"]
        for stamp in stamps:
            sibling = body.parent / f"{body.name}.oneskill-backup-{stamp}"
            sibling.mkdir()
            (sibling / "SKILL.md").write_text("old", encoding="utf-8")

        removed = osk.prune_backups(body, 1)
        self.assertEqual(len(removed), 2)
        left = sorted(item.name for item in body.parent.glob(f"{body.name}.oneskill-backup-*"))
        self.assertEqual(left, [f"{body.name}.oneskill-backup-20260303-000000"])
        self.assertTrue(body.is_dir(), "pruning must never touch the live body")

    def test_prune_backups_default_zero_removes_all(self) -> None:
        osk = load_osk_module()
        body = self.body("shared/big-skill")
        sibling = body.parent / f"{body.name}.oneskill-backup-20260101-000000"
        sibling.mkdir()
        (sibling / "SKILL.md").write_text("old", encoding="utf-8")

        removed = osk.prune_backups(body, 0)
        self.assertEqual(len(removed), 1)
        self.assertEqual(list(body.parent.glob(f"{body.name}.oneskill-backup-*")), [])
        self.assertTrue(body.is_dir())

    def test_prune_backups_ignores_other_skills(self) -> None:
        osk = load_osk_module()
        body = self.body("shared/alpha")
        other = self.body("shared/alpha-extra")
        mine = body.parent / f"{body.name}.oneskill-backup-20260101-000000"
        mine.mkdir()
        theirs = other.parent / f"{other.name}.oneskill-backup-20260101-000000"
        theirs.mkdir()

        osk.prune_backups(body, 0)
        self.assertFalse(mine.exists())
        self.assertTrue(theirs.exists(), "a different skill's backups must be left alone")

    def test_prune_backups_rejects_negative_keep(self) -> None:
        osk = load_osk_module()
        body = self.body("shared/alpha")
        with self.assertRaises(osk.OneskillError):
            osk.prune_backups(body, -1)

    def test_scan_respects_single_client_ok(self) -> None:
        """A confirmed single-client skill: no review flag, and the marker survives a rewrite."""
        body = self.body("codex/skills/codex-only")
        self.link("codex", "codex-only", body)
        self.write_manifest(
            [
                {
                    "name": "codex-only",
                    "source": "self",
                    "body": str(body),
                    "scope": ["codex"],
                    "single_client_ok": True,
                }
            ]
        )
        result = self.run_osk("scan", "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["skills"] if item["name"] == "codex-only")
        self.assertNotIn("review", entry)
        self.assertIs(entry["single_client_ok"], True)
        doctor = self.run_osk("doctor", "--json")
        self.assertEqual(doctor.returncode, 0, doctor.stdout)

    def test_single_client_ok_expires_when_body_changes(self) -> None:
        """The confirmation is tied to one body; swapping it voids the marker."""
        old_body = self.body("codex/skills/old-impl")
        new_body = self.body("codex/skills/new-impl")
        self.link("codex", "swapped", new_body)
        self.write_manifest(
            [
                {
                    "name": "swapped",
                    "source": "self",
                    "body": str(old_body),
                    "scope": ["codex"],
                    "single_client_ok": True,
                }
            ]
        )
        result = self.run_osk("scan", "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["skills"] if item["name"] == "swapped")
        self.assertNotIn("single_client_ok", entry)
        self.assertIn("needs review", entry["review"])

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
        tokens = next(
            shlex.split(segment)
            for segment in shadow[0]["suggested_command"].split("&&")
            if shlex.split(segment)[:2] == ["ln", "-s"]
        )
        self.assertEqual(tokens[:2], ["ln", "-s"])
        self.assertNotEqual(tokens[2], tokens[3])
        self.assertEqual(Path(tokens[2]), body)

    def test_install_local_directory_links_all_clients_and_records_provenance(self) -> None:
        fixture = self.remote_fixture()
        result = self.install_remote(fixture, "--review")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("BEGIN SKILL.md", result.stdout)
        installed = self.agent / "remote" / "remote-demo"
        self.assertEqual((installed / "payload.txt").read_text(encoding="utf-8"), "version one\n")
        for client in CLIENT_PATHS:
            link = self.client_path(client, "remote-demo")
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), installed.resolve())
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 2)
        entry = payload["skills"][0]
        self.assertEqual(entry["source"], "remote")
        self.assertEqual(entry["scope"], "shared")
        self.assertEqual(entry["provenance"]["source_url"], str(fixture))
        self.assertEqual(entry["provenance"]["ref"], "local")
        self.assertTrue(entry["provenance"]["installed_at"])
        listing = self.run_osk("list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("ref", listing.stdout.splitlines()[0])
        self.assertIn("local", listing.stdout)
        json_listing = json.loads(self.run_osk("list", "--json").stdout)
        row = json_listing["skills"][0]
        for old_key in ("name", "source", "body", "scope", "clients"):
            self.assertIn(old_key, row)
        self.assertIn("provenance", row)

    def test_install_local_tar_gz_fixture(self) -> None:
        source = self.remote_fixture(name="archive-skill")
        archive = self.base / "archive-skill.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(source, arcname="owner-repo-abcdef123456")
        self.agent.mkdir(parents=True)
        result = self.run_osk("install", str(archive), "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        entry = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"][0]
        self.assertEqual(entry["name"], "archive-skill")
        self.assertEqual(entry["provenance"]["ref"], "abcdef123456")

    def test_install_rejects_tar_path_traversal(self) -> None:
        archive = self.base / "unsafe.tar.gz"
        content = b"escape attempt\n"
        with tarfile.open(archive, "w:gz") as handle:
            member = tarfile.TarInfo("../escaped.txt")
            member.size = len(content)
            handle.addfile(member, io.BytesIO(content))
        self.agent.mkdir(parents=True)
        result = self.run_osk("install", str(archive), "--yes")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsafe path in source archive", result.stderr)
        self.assertFalse(self.manifest.exists())

    def test_install_dry_run_changes_nothing(self) -> None:
        fixture = self.remote_fixture(name="install-preview")
        self.agent.mkdir(parents=True)
        result = self.run_osk("install", str(fixture), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("no changes made", result.stdout)
        self.assertFalse(self.manifest.exists())
        self.assertFalse((self.agent / "remote").exists())
        for client in CLIENT_PATHS:
            self.assertFalse(os.path.lexists(self.client_path(client, "install-preview")))

    def test_install_conflicts_are_backed_up_after_confirmation(self) -> None:
        fixture = self.remote_fixture(name="collision")
        target = self.agent / "remote" / "collision"
        target.mkdir(parents=True)
        (target / "old.txt").write_text("old body", encoding="utf-8")
        conflict = self.client_path("claude", "collision")
        conflict.mkdir()
        (conflict / "local.txt").write_text("local copy", encoding="utf-8")
        self.write_manifest([])
        result = self.run_osk("install", str(fixture), "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        body_backups = list(target.parent.glob("collision.oneskill-backup-*"))
        client_backups = self.client_backups("claude", "collision")
        self.assertEqual(len(body_backups), 1)
        self.assertEqual((body_backups[0] / "old.txt").read_text(), "old body")
        self.assertEqual(len(client_backups), 1)
        self.assertEqual((client_backups[0] / "local.txt").read_text(), "local copy")
        self.assertTrue(conflict.is_symlink())
        self.assert_no_client_backups()
        listing = self.run_osk("list")
        self.assertNotIn("! extra", listing.stdout)

    def test_install_conflict_refusal_changes_nothing(self) -> None:
        fixture = self.remote_fixture(name="refused")
        target = self.agent / "remote" / "refused"
        target.mkdir(parents=True)
        marker = target / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        self.write_manifest([])
        before = self.manifest.read_bytes()
        result = self.run_osk("install", str(fixture), input_text="n\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no changes were made", result.stdout)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertEqual(list(target.parent.glob("refused.oneskill-backup-*")), [])

    def test_install_validation_failures_make_no_changes(self) -> None:
        self.agent.mkdir(parents=True)
        missing = self.base / "missing-skill"
        missing.mkdir()
        missing_result = self.run_osk("install", str(missing), "--yes")
        self.assertEqual(missing_result.returncode, 2)
        self.assertIn("must contain SKILL.md", missing_result.stderr)
        no_name = self.base / "no-name"
        no_name.mkdir()
        (no_name / "SKILL.md").write_text(
            "---\ndescription: Missing its name.\n---\n", encoding="utf-8"
        )
        no_name_result = self.run_osk("install", str(no_name), "--yes")
        self.assertEqual(no_name_result.returncode, 2)
        self.assertIn("non-empty name", no_name_result.stderr)
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.agent.iterdir()), [])

    def test_update_no_changes_is_a_noop(self) -> None:
        fixture = self.remote_fixture(name="unchanged")
        installed = self.install_remote(fixture)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target = self.agent / "remote" / "unchanged"
        manifest_before = self.manifest.read_bytes()
        inode_before = target.stat().st_ino
        result = self.run_osk("update", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("already up to date", result.stdout)
        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        self.assertEqual(target.stat().st_ino, inode_before)
        self.assertEqual(list(target.parent.glob("unchanged.oneskill-backup-*")), [])

    def test_update_dry_run_changes_nothing(self) -> None:
        fixture = self.remote_fixture(name="preview-update")
        installed = self.install_remote(fixture)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target = self.agent / "remote" / "preview-update"
        manifest_before = self.manifest.read_bytes()
        (fixture / "payload.txt").write_text("preview only\n", encoding="utf-8")
        result = self.run_osk("update", "preview-update", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("modified: payload.txt", result.stdout)
        self.assertEqual((target / "payload.txt").read_text(), "version one\n")
        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        self.assertEqual(list(target.parent.glob("preview-update.oneskill-backup-*")), [])

    def test_update_leaves_no_backup_by_default(self) -> None:
        # A remote skill records source_url and ref, so the previous version is
        # always refetchable from upstream. Keeping a full copy of every past
        # body just doubles a large skill on disk on every update.
        fixture = self.remote_fixture(name="upgrade-me")
        installed = self.install_remote(fixture)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target = self.agent / "remote" / "upgrade-me"
        links_before = {
            client: os.readlink(self.client_path(client, "upgrade-me"))
            for client in CLIENT_PATHS
        }
        (fixture / "payload.txt").write_text("version two\n", encoding="utf-8")
        (fixture / "new.txt").write_text("added\n", encoding="utf-8")
        result = self.run_osk("update", "upgrade-me", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("added: new.txt", result.stdout)
        self.assertIn("modified: payload.txt", result.stdout)
        self.assertEqual((target / "payload.txt").read_text(), "version two\n")
        self.assertEqual(list(target.parent.glob("upgrade-me.oneskill-backup-*")), [])
        for client, raw_target in links_before.items():
            self.assertEqual(os.readlink(self.client_path(client, "upgrade-me")), raw_target)

    def test_update_keep_backups_retains_previous_body(self) -> None:
        fixture = self.remote_fixture(name="upgrade-me")
        installed = self.install_remote(fixture)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target = self.agent / "remote" / "upgrade-me"
        (fixture / "payload.txt").write_text("version two\n", encoding="utf-8")
        result = self.run_osk("update", "upgrade-me", "--yes", "--keep-backups", "1")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((target / "payload.txt").read_text(), "version two\n")
        backups = list(target.parent.glob("upgrade-me.oneskill-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "payload.txt").read_text(), "version one\n")

    def test_uninstall_unlinks_clients_backs_up_body_and_removes_manifest_entry(self) -> None:
        fixture = self.remote_fixture(name="remove-me")
        installed = self.install_remote(fixture)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target = self.agent / "remote" / "remove-me"
        result = self.run_osk("uninstall", "remove-me", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(target.exists())
        backups = list(target.parent.glob("remove-me.oneskill-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "SKILL.md").is_file())
        for client in CLIENT_PATHS:
            self.assertFalse(os.path.lexists(self.client_path(client, "remove-me")))
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], [])

    def test_uninstall_dry_run_changes_nothing(self) -> None:
        fixture = self.remote_fixture(name="keep-me")
        installed = self.install_remote(fixture)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target = self.agent / "remote" / "keep-me"
        manifest_before = self.manifest.read_bytes()
        result = self.run_osk("uninstall", "keep-me", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("no changes made", result.stdout)
        self.assertTrue(target.is_dir())
        for client in CLIENT_PATHS:
            self.assertTrue(self.client_path(client, "keep-me").is_symlink())
        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        self.assertEqual(list(target.parent.glob("keep-me.oneskill-backup-*")), [])


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

    def test_init_yes_prefers_existing_agents_skills_directory(self) -> None:
        agents = self.home / ".agents" / "skills"
        agents.mkdir(parents=True)
        result = self.run_osk("init", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["library"], str(agents))

    def test_init_interactive_enter_accepts_agents_recommendation(self) -> None:
        agents = self.home / ".agents" / "skills"
        agents.mkdir(parents=True)
        result = self.run_osk("init", input_text="\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("community-shared", result.stdout)
        self.assertIn(str(self.home / ".oneskill" / "library"), result.stdout)
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["library"], str(agents))

    def test_init_interactive_default_without_agents_directory(self) -> None:
        result = self.run_osk("init", input_text="\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("community-shared", result.stdout)
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["library"], str(self.home / ".oneskill" / "library"))

    def test_version_flag(self) -> None:
        for flag in ("--version", "-V"):
            result = self.run_osk(flag)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "oneskill 0.3.0")


class OneskillNetworkTest(unittest.TestCase):
    """outdated/search tests; all network access is mocked, fixtures live under /tmp."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="oneskill-net-test-", dir="/tmp")
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.library = self.base / "library"
        self.manifest = self.base / "skills.json"
        for parts in CLIENT_PATHS.values():
            self.home.joinpath(*parts).mkdir(parents=True)
        self.library.mkdir(parents=True)
        self.env = os.environ.copy()
        self.env.pop("GITHUB_TOKEN", None)
        self.env.update(
            ONESKILL_HOME=str(self.home),
            ONESKILL_LIBRARY=str(self.library),
            ONESKILL_MANIFEST=str(self.manifest),
        )
        self.osk = load_osk_module()
        self.cfg = {
            "home": self.home,
            "library": self.library,
            "manifest": self.manifest,
            **{
                client: self.home.joinpath(*parts)
                for client, parts in CLIENT_PATHS.items()
            },
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_remote_manifest(
        self, ref: str = "abc123def456", source_url: str = "gh:owner/repo/skills/demo@main"
    ) -> Path:
        body = self.library / "remote" / "demo"
        body.mkdir(parents=True)
        (body / "SKILL.md").write_text("# demo\n", encoding="utf-8")
        self.manifest.write_text(
            json.dumps(
                {
                    "version": 2,
                    "skills": [
                        {
                            "name": "demo",
                            "source": "remote",
                            "body": str(body),
                            "scope": "shared",
                            "description": "A demo skill.",
                            "provenance": {
                                "source_url": source_url,
                                "ref": ref,
                                "installed_at": "2026-01-01T00:00:00+00:00",
                            },
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return body

    def run_outdated(self, payload: object, json_mode: bool = False) -> tuple[int, str]:
        args = SimpleNamespace(name=None, json=json_mode)
        with mock.patch.object(self.osk, "http_get_json", return_value=payload):
            out = io.StringIO()
            with redirect_stdout(out):
                code = self.osk.command_outdated(args, self.cfg)
        return code, out.getvalue()

    def test_outdated_reports_up_to_date(self) -> None:
        self.write_remote_manifest()
        code, out = self.run_outdated([{"sha": "abc123def4567890aaaa"}])
        self.assertEqual(code, 0)
        self.assertIn("up to date", out)
        self.assertIn("1 remote skill · 0 updates available", out)
        cache = json.loads((self.base / "update-cache.json").read_text(encoding="utf-8"))
        entry = cache["skills"]["demo"]
        self.assertEqual(entry["latest_ref"], "abc123def4567890aaaa")
        self.assertFalse(entry["update_available"])
        self.assertTrue(entry["checked_at"])

    def test_outdated_reports_update_available(self) -> None:
        self.write_remote_manifest()
        code, out = self.run_outdated([{"sha": "fff000111222333444"}])
        self.assertEqual(code, 0)
        self.assertIn("update available", out)
        self.assertIn("1 remote skill · 1 update available", out)
        self.assertIn("osk update <name>", out)
        cache = json.loads((self.base / "update-cache.json").read_text(encoding="utf-8"))
        self.assertTrue(cache["skills"]["demo"]["update_available"])

    def test_outdated_rate_limit_message(self) -> None:
        self.write_remote_manifest()

        def raise_403(request: object, timeout: int = 0) -> None:
            raise urllib.error.HTTPError(
                "https://api.github.com/repos/owner/repo/commits",
                403,
                "Forbidden",
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"},
                None,
            )

        with mock.patch("urllib.request.urlopen", side_effect=raise_403):
            with self.assertRaises(self.osk.OneskillError) as context:
                self.osk.command_outdated(SimpleNamespace(name=None, json=False), self.cfg)
        message = str(context.exception)
        self.assertIn("rate limit", message)
        self.assertIn("GITHUB_TOKEN", message)
        self.assertFalse((self.base / "update-cache.json").exists())

    def test_list_marks_cached_updates_without_network(self) -> None:
        body = self.write_remote_manifest()
        code, _ = self.run_outdated([{"sha": "fff000111222333444"}])
        self.assertEqual(code, 0)
        for client in CLIENT_PATHS:
            self.home.joinpath(*CLIENT_PATHS[client], "demo").symlink_to(
                body, target_is_directory=True
            )

        def no_network(request: object, timeout: int = 0) -> None:
            raise AssertionError("osk list must not touch the network")

        with mock.patch.dict(os.environ, self.env):
            with mock.patch("urllib.request.urlopen", side_effect=no_network):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = self.osk.main(["list"])
                self.assertEqual(code, 0)
                text = out.getvalue()
                self.assertIn("abc123def456 ↑", text)
                self.assertIn("↑ = update available (as of ", text)
                self.assertIn("run `osk outdated` to refresh", text)
                out = io.StringIO()
                with redirect_stdout(out):
                    code = self.osk.main(["list", "--json"])
                self.assertEqual(code, 0)
        rows = {row["name"]: row for row in json.loads(out.getvalue())["skills"]}
        self.assertTrue(rows["demo"]["update_available"])

    def test_search_renders_results(self) -> None:
        payload = {
            "query": "pdf",
            "searchType": "keyword",
            "count": 1,
            "duration_ms": 7,
            "skills": [
                {
                    "id": "anthropics/skills/pdf",
                    "skillId": "pdf",
                    "name": "pdf",
                    "installs": 174085,
                    "source": "anthropics/skills",
                }
            ],
        }
        with mock.patch.object(self.osk, "http_get_json", return_value=payload):
            out = io.StringIO()
            with redirect_stdout(out):
                code = self.osk.command_search(
                    SimpleNamespace(query="pdf", limit=20, json=False)
                )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("pdf", text)
        self.assertIn("anthropics/skills", text)
        self.assertIn("174.1k", text)
        self.assertIn("gh:anthropics/skills/pdf@main", text)
        self.assertIn("--dry-run --review", text)

    def test_search_rejects_malformed_response(self) -> None:
        for payload in ({"query": "pdf"}, {"skills": "oops"}, ["not", "a", "dict"]):
            with mock.patch.object(self.osk, "http_get_json", return_value=payload):
                with self.assertRaises(self.osk.OneskillError) as context:
                    self.osk.command_search(SimpleNamespace(query="pdf", limit=20, json=False))
            self.assertIn("missing the skills array", str(context.exception))

    def test_search_skips_malformed_entries(self) -> None:
        clean = {
            "id": "anthropics/skills/pdf",
            "skillId": "pdf",
            "name": "pdf",
            "installs": 174085,
            "source": "anthropics/skills",
        }
        dirty = [
            {"name": "no-other-fields"},
            {"id": "a/b/c", "skillId": "", "name": "x", "installs": 3, "source": "a/b"},
            {"id": "a/b/d", "skillId": "d", "name": "d", "installs": "many", "source": "a/b"},
            "not-an-object",
        ]
        payload = {"query": "pdf", "skills": [dirty[0], clean, *dirty[1:]]}
        with mock.patch.object(self.osk, "http_get_json", return_value=payload):
            out = io.StringIO()
            with redirect_stdout(out):
                code = self.osk.command_search(SimpleNamespace(query="pdf", limit=20, json=False))
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("gh:anthropics/skills/pdf@main", text)
        self.assertIn("skipped 4 malformed entries from skills.sh", text)
        self.assertIn("--dry-run --review", text)

        with mock.patch.object(self.osk, "http_get_json", return_value=payload):
            out = io.StringIO()
            with redirect_stdout(out):
                code = self.osk.command_search(SimpleNamespace(query="pdf", limit=20, json=True))
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["skipped"], 4)
        self.assertEqual([item["name"] for item in report["results"]], ["pdf"])

        with mock.patch.object(self.osk, "http_get_json", return_value={"query": "x", "skills": dirty}):
            with self.assertRaises(self.osk.OneskillError) as context:
                self.osk.command_search(SimpleNamespace(query="x", limit=20, json=False))
        self.assertIn("no usable entries", str(context.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
