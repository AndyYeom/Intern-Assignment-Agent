"""Tests for stable applicant IDs, stored on candidate records."""
from __future__ import annotations

import json

from generator.github import ids, normalize, sampler


def test_ids_are_zero_padded_and_sequential():
    registry = ids.assign(["zed", "amy", "bob"])
    assert registry == {"zed": "applicant0001", "amy": "applicant0002", "bob": "applicant0003"}


def test_ids_never_change_once_assigned():
    """A reference to applicant0002 must stay valid across rebuilds."""
    ids.assign(["zed", "amy"])
    registry = ids.assign(["new", "amy", "zed", "another"])
    assert registry["zed"] == "applicant0001"
    assert registry["amy"] == "applicant0002"
    assert registry["new"] == "applicant0003"
    assert registry["another"] == "applicant0004"


def test_id_lookup():
    ids.assign(["amy"])
    assert ids.id_for("amy") == "applicant0001"
    assert ids.id_for("nobody") is None


def test_ids_are_stored_on_candidate_records():
    sampler.write_state({"candidates": [{"login": "amy", "selected": True}], "consumed": {}})
    ids.assign(["amy"])
    candidate = sampler.load_state()["candidates"][0]
    assert candidate["login"] == "amy"
    assert candidate["applicant_id"] == "applicant0001"


def test_ids_are_not_reused_after_a_profile_file_is_deleted():
    """Deleting bob's profile must not hand applicant0002 to the next person."""
    ids.assign(["amy", "bob"])
    normalize.PROFILES_DIR.mkdir(parents=True)
    profile = normalize.PROFILES_DIR / "applicant0002.json"
    profile.write_text("{}")
    profile.unlink()

    assert ids.assign(["cat"])["cat"] == "applicant0003"
    assert ids.id_for("bob") == "applicant0002"


def test_legacy_registry_is_migrated_without_renumbering():
    sampler.write_state({"candidates": [{"login": "amy", "selected": True},
                                        {"login": "bob", "selected": True}], "consumed": {}})
    ids._LEGACY_REGISTRY.write_text(json.dumps({"bob": "applicant0007"}))

    registry = ids.assign(["amy", "bob"])
    assert registry["bob"] == "applicant0007"
    assert registry["amy"] == "applicant0008"
    assert not ids._LEGACY_REGISTRY.exists()


def test_stale_login_named_profiles_are_removed():
    normalize.PROFILES_DIR.mkdir(parents=True)
    (normalize.PROFILES_DIR / "applicant0001.json").write_text("{}")
    (normalize.PROFILES_DIR / "17jhagan.json").write_text("{}")

    assert normalize.remove_stale_profiles() == ["17jhagan.json"]
    assert (normalize.PROFILES_DIR / "applicant0001.json").exists()
