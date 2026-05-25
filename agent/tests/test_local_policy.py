"""Tests for local policy enforcement."""

import time
import pytest

from rp.local_policy import (
    LocalPolicy,
    CommandDecision,
    touch_flag,
    add_to_whitelist,
    remove_from_whitelist,
    show_whitelist,
    get_flag_status,
)


@pytest.fixture
def policy_dir(tmp_path):
    """Create temporary policy directory."""
    return tmp_path / "policy"


@pytest.fixture
def policy(policy_dir):
    """Create LocalPolicy with temporary directory."""
    return LocalPolicy(policy_dir=policy_dir)


# exec_shell tests


def test_exec_shell_prod_no_flag_denies(policy):
    """Prod group without flag should deny exec_shell."""
    decision, reason = policy.evaluate("exec_shell", {}, "prod")
    assert decision == CommandDecision.DENY
    assert "allow-remote-exec" in reason


def test_exec_shell_prod_with_flag_allows(policy, policy_dir):
    """Prod group with flag should allow exec_shell."""
    touch_flag("allow-remote-exec", policy_dir=policy_dir)
    decision, reason = policy.evaluate("exec_shell", {}, "prod")
    assert decision == CommandDecision.ALLOW
    assert "allowed" in reason.lower()


def test_exec_shell_iarq_no_flag_denies(policy):
    """iarq is also sensitive group."""
    decision, reason = policy.evaluate("exec_shell", {}, "iarq")
    assert decision == CommandDecision.DENY


def test_exec_shell_family_allows_default(policy):
    """Family group should allow exec_shell without flag."""
    decision, reason = policy.evaluate("exec_shell", {}, "family")
    assert decision == CommandDecision.ALLOW


def test_exec_shell_default_group_allows(policy):
    """Default group should allow exec_shell."""
    decision, reason = policy.evaluate("exec_shell", {}, "default")
    assert decision == CommandDecision.ALLOW


def test_exec_shell_expired_flag_denies(policy, policy_dir):
    """Expired flag should deny exec_shell."""
    flag_path = policy_dir / "allow-remote-exec"
    policy_dir.mkdir(parents=True, exist_ok=True)
    flag_path.touch()

    # Set mtime to 25 hours ago
    old_time = time.time() - (25 * 3600)
    import os

    os.utime(flag_path, (old_time, old_time))

    decision, reason = policy.evaluate("exec_shell", {}, "prod")
    assert decision == CommandDecision.DENY
    assert "expired" in reason.lower()


# pkg_install tests


def test_pkg_install_prod_requires_approval(policy):
    """Prod group should require approval for pkg_install."""
    decision, reason = policy.evaluate("pkg_install", {"name": "nginx"}, "prod")
    assert decision == CommandDecision.REQUIRE_APPROVAL
    assert "approval" in reason.lower()


def test_pkg_install_family_allows(policy):
    """Family group should allow pkg_install."""
    decision, reason = policy.evaluate("pkg_install", {"name": "nginx"}, "family")
    assert decision == CommandDecision.ALLOW


# service_restart tests


def test_service_restart_prod_whitelist_match_allows(policy, policy_dir):
    """Whitelisted service should be allowed."""
    add_to_whitelist("restart-whitelist", "nginx", policy_dir=policy_dir)

    decision, reason = policy.evaluate(
        "service_restart", {"service_name": "nginx"}, "prod"
    )
    assert decision == CommandDecision.ALLOW
    assert "nginx" in reason


def test_service_restart_prod_not_whitelisted_denies(policy, policy_dir):
    """Non-whitelisted service should be denied."""
    add_to_whitelist("restart-whitelist", "nginx", policy_dir=policy_dir)

    decision, reason = policy.evaluate(
        "service_restart", {"service_name": "apache2"}, "prod"
    )
    assert decision == CommandDecision.DENY
    assert "not in" in reason.lower()


def test_service_restart_prod_no_whitelist_denies(policy):
    """Missing whitelist file should deny."""
    decision, reason = policy.evaluate(
        "service_restart", {"service_name": "nginx"}, "prod"
    )
    assert decision == CommandDecision.DENY


def test_service_restart_family_allows(policy):
    """Family group should allow without whitelist."""
    decision, reason = policy.evaluate(
        "service_restart", {"service_name": "nginx"}, "family"
    )
    assert decision == CommandDecision.ALLOW


def test_service_restart_glob_pattern_match(policy, policy_dir):
    """Glob patterns in whitelist should work."""
    add_to_whitelist("restart-whitelist", "docker-*", policy_dir=policy_dir)

    decision, reason = policy.evaluate(
        "service_restart", {"service_name": "docker-compose"}, "prod"
    )
    assert decision == CommandDecision.ALLOW


# file_read tests


def test_file_read_prod_glob_match(policy, policy_dir):
    """Matching path should allow file_read."""
    add_to_whitelist("read-allowlist", "/var/log/*.log", policy_dir=policy_dir)

    decision, reason = policy.evaluate(
        "file_read", {"path": "/var/log/syslog.log"}, "prod"
    )
    assert decision == CommandDecision.ALLOW


def test_file_read_prod_no_match_denies(policy, policy_dir):
    """Non-matching path should deny."""
    add_to_whitelist("read-allowlist", "/var/log/*.log", policy_dir=policy_dir)

    decision, reason = policy.evaluate("file_read", {"path": "/etc/passwd"}, "prod")
    assert decision == CommandDecision.DENY


def test_file_read_prod_no_allowlist_denies(policy):
    """Missing allowlist should deny."""
    decision, reason = policy.evaluate(
        "file_read", {"path": "/var/log/test.log"}, "prod"
    )
    assert decision == CommandDecision.DENY


def test_file_read_family_allows(policy):
    """Family group should allow without allowlist."""
    decision, reason = policy.evaluate(
        "file_read", {"path": "/var/log/test.log"}, "family"
    )
    assert decision == CommandDecision.ALLOW


# file_write tests


def test_file_write_prod_no_flag_denies(policy):
    """Prod without flag should deny file_write."""
    decision, reason = policy.evaluate("file_write", {"path": "/etc/rp/test"}, "prod")
    assert decision == CommandDecision.DENY
    assert "allow-remote-write" in reason


def test_file_write_prod_with_flag_safe_path_allows(policy, policy_dir):
    """Prod with flag and safe path should allow."""
    touch_flag("allow-remote-write", policy_dir=policy_dir)

    decision, reason = policy.evaluate("file_write", {"path": "/etc/rp/test"}, "prod")
    assert decision == CommandDecision.ALLOW


def test_file_write_prod_external_path_requires_approval(policy, policy_dir):
    """External path should require approval even with flag."""
    touch_flag("allow-remote-write", policy_dir=policy_dir)

    decision, reason = policy.evaluate(
        "file_write", {"path": "/etc/systemd/test"}, "prod"
    )
    assert decision == CommandDecision.REQUIRE_APPROVAL
    assert "outside" in reason.lower()


def test_file_write_family_safe_path_allows(policy):
    """Family group with safe path should allow."""
    decision, reason = policy.evaluate(
        "file_write", {"path": "/opt/rp/config"}, "family"
    )
    assert decision == CommandDecision.ALLOW


def test_file_write_family_external_path_requires_approval(policy):
    """Family group with external path needs approval."""
    decision, reason = policy.evaluate("file_write", {"path": "/tmp/test"}, "family")
    assert decision == CommandDecision.REQUIRE_APPROVAL


# screen_open tests


def test_screen_open_always_allow(policy):
    """screen_open should always allow."""
    decision, reason = policy.evaluate("screen_open", {"protocol": "rustdesk"}, "prod")
    assert decision == CommandDecision.ALLOW

    decision, reason = policy.evaluate("screen_open", {}, "family")
    assert decision == CommandDecision.ALLOW


# ssh_keys_sync tests


def test_ssh_keys_sync_sha_match_allows(policy, policy_dir):
    """Matching SHA256 should allow."""
    policy_dir.mkdir(parents=True, exist_ok=True)
    sha_file = policy_dir / "groups-yml-sha256"
    sha_file.write_text("abc123def456")

    decision, reason = policy.evaluate(
        "ssh_keys_sync", {"groups_yml_sha256": "abc123def456"}, "prod"
    )
    assert decision == CommandDecision.ALLOW


def test_ssh_keys_sync_sha_mismatch_denies(policy, policy_dir):
    """Mismatched SHA256 should deny."""
    policy_dir.mkdir(parents=True, exist_ok=True)
    sha_file = policy_dir / "groups-yml-sha256"
    sha_file.write_text("abc123def456")

    decision, reason = policy.evaluate(
        "ssh_keys_sync", {"groups_yml_sha256": "wrong_sha"}, "prod"
    )
    assert decision == CommandDecision.DENY
    assert "mismatch" in reason.lower()


def test_ssh_keys_sync_no_reference_denies(policy):
    """Missing reference SHA should deny."""
    decision, reason = policy.evaluate(
        "ssh_keys_sync", {"groups_yml_sha256": "test"}, "prod"
    )
    assert decision == CommandDecision.DENY


# agent_upgrade tests


def test_agent_upgrade_major_version_requires_approval(policy):
    """Major version change should require approval."""
    decision, reason = policy.evaluate("agent_upgrade", {"version": "1.0.0"}, "prod")
    # Current version is 0.1.0, upgrading to 1.x.x
    assert decision == CommandDecision.REQUIRE_APPROVAL
    assert "major version" in reason.lower()


def test_agent_upgrade_minor_bump_allows(policy):
    """Minor bump should allow."""
    decision, reason = policy.evaluate("agent_upgrade", {"version": "0.2.0"}, "prod")
    # Current version is 0.1.0, upgrading to 0.2.0
    assert decision == CommandDecision.ALLOW


def test_agent_upgrade_invalid_version_denies(policy):
    """Invalid version format should deny."""
    decision, reason = policy.evaluate("agent_upgrade", {"version": "invalid"}, "prod")
    assert decision == CommandDecision.DENY
    assert "invalid" in reason.lower()


# reboot tests


def test_reboot_prod_requires_approval(policy):
    """Prod group should require approval for reboot."""
    decision, reason = policy.evaluate("reboot", {"delay_s": 30}, "prod")
    assert decision == CommandDecision.REQUIRE_APPROVAL
    assert "double-confirm" in reason.lower()


def test_reboot_family_requires_approval(policy):
    """Family group should also require approval."""
    decision, reason = policy.evaluate("reboot", {"delay_s": 30}, "family")
    assert decision == CommandDecision.REQUIRE_APPROVAL


# unknown command tests


def test_unknown_command_default_deny(policy):
    """Unknown command should always deny."""
    decision, reason = policy.evaluate("mystery_command", {}, "prod")
    assert decision == CommandDecision.DENY
    assert "unknown" in reason.lower()

    decision, reason = policy.evaluate("mystery_command", {}, "family")
    assert decision == CommandDecision.DENY


# Flag file helpers tests


def test_flag_file_ttl_expiry(policy_dir):
    """Flag should expire after TTL."""
    policy_dir.mkdir(parents=True, exist_ok=True)
    flag_path = policy_dir / "test-flag"
    flag_path.touch()

    # Set to 25 hours ago
    old_time = time.time() - (25 * 3600)
    import os

    os.utime(flag_path, (old_time, old_time))

    status = get_flag_status("test-flag", policy_dir=policy_dir)
    assert status["expired"] is True
    assert status["age_hours"] > 24


def test_flag_file_not_expired(policy_dir):
    """Recent flag should not be expired."""
    touch_flag("test-flag", policy_dir=policy_dir)

    status = get_flag_status("test-flag", policy_dir=policy_dir)
    assert status["expired"] is False
    assert status["age_hours"] < 1


def test_flag_file_missing(policy_dir):
    """Missing flag should return not exists."""
    status = get_flag_status("missing-flag", policy_dir=policy_dir)
    assert status["exists"] is False


# Whitelist helpers tests


def test_whitelist_add_remove(policy_dir):
    """Add and remove from whitelist."""
    add_to_whitelist("test-whitelist", "item1", policy_dir=policy_dir)
    add_to_whitelist("test-whitelist", "item2", policy_dir=policy_dir)

    items = show_whitelist("test-whitelist", policy_dir=policy_dir)
    assert "item1" in items
    assert "item2" in items

    removed = remove_from_whitelist("test-whitelist", "item1", policy_dir=policy_dir)
    assert removed is True

    items = show_whitelist("test-whitelist", policy_dir=policy_dir)
    assert "item1" not in items
    assert "item2" in items


def test_whitelist_idempotent_add(policy_dir):
    """Adding same item twice should be idempotent."""
    add_to_whitelist("test-whitelist", "item1", policy_dir=policy_dir)
    add_to_whitelist("test-whitelist", "item1", policy_dir=policy_dir)

    items = show_whitelist("test-whitelist", policy_dir=policy_dir)
    assert items.count("item1") == 1


def test_whitelist_missing_file(policy_dir):
    """Show whitelist for missing file should return empty."""
    items = show_whitelist("missing-whitelist", policy_dir=policy_dir)
    assert items == []


def test_whitelist_ignore_comments(policy_dir):
    """Whitelist should ignore comment lines."""
    policy_dir.mkdir(parents=True, exist_ok=True)
    whitelist_path = policy_dir / "test-whitelist"
    whitelist_path.write_text("# comment\nitem1\n  # another comment\nitem2\n")

    items = show_whitelist("test-whitelist", policy_dir=policy_dir)
    assert items == ["item1", "item2"]


# Group tier tests


def test_group_default_uses_lenient_rules(policy):
    """Default group should use lenient rules."""
    # exec_shell allowed
    decision, _ = policy.evaluate("exec_shell", {}, "default")
    assert decision == CommandDecision.ALLOW

    # pkg_install allowed
    decision, _ = policy.evaluate("pkg_install", {}, "default")
    assert decision == CommandDecision.ALLOW

    # service_restart allowed
    decision, _ = policy.evaluate(
        "service_restart", {"service_name": "test"}, "default"
    )
    assert decision == CommandDecision.ALLOW


def test_group_custom_non_sensitive_lenient(policy):
    """Custom non-sensitive group should be lenient."""
    decision, _ = policy.evaluate("exec_shell", {}, "custom-group")
    assert decision == CommandDecision.ALLOW


# Dry-run tests


def test_evaluate_dry_run_no_side_effects(policy, policy_dir):
    """Evaluation should not modify state."""
    # Evaluate multiple times
    policy.evaluate("exec_shell", {}, "prod")
    policy.evaluate("exec_shell", {}, "prod")

    # Policy dir should still be empty (no auto-creation of files)
    if policy_dir.exists():
        assert len(list(policy_dir.iterdir())) == 0


# Edge cases


def test_empty_command_type(policy):
    """Empty command type should deny."""
    decision, reason = policy.evaluate("", {}, "prod")
    assert decision == CommandDecision.DENY


def test_empty_payload(policy):
    """Empty payload should be handled gracefully."""
    decision, _ = policy.evaluate("exec_shell", {}, "family")
    assert decision == CommandDecision.ALLOW


def test_missing_payload_fields(policy, policy_dir):
    """Missing payload fields should not crash."""
    add_to_whitelist("restart-whitelist", "nginx", policy_dir=policy_dir)

    # Missing service_name
    decision, reason = policy.evaluate("service_restart", {}, "prod")
    assert decision == CommandDecision.DENY


def test_case_sensitive_group_names(policy):
    """Group names should be case-sensitive."""
    decision, _ = policy.evaluate("exec_shell", {}, "PROD")
    # PROD != prod, so should be lenient
    assert decision == CommandDecision.ALLOW

    decision, _ = policy.evaluate("exec_shell", {}, "prod")
    # prod is sensitive
    assert decision == CommandDecision.DENY


def test_multiple_glob_patterns(policy, policy_dir):
    """Multiple glob patterns should all be checked."""
    add_to_whitelist("read-allowlist", "/var/log/*.log", policy_dir=policy_dir)
    add_to_whitelist("read-allowlist", "/etc/rp/*", policy_dir=policy_dir)
    add_to_whitelist("read-allowlist", "/tmp/*.txt", policy_dir=policy_dir)

    decision, _ = policy.evaluate("file_read", {"path": "/etc/rp/config.toml"}, "prod")
    assert decision == CommandDecision.ALLOW

    decision, _ = policy.evaluate("file_read", {"path": "/tmp/test.txt"}, "prod")
    assert decision == CommandDecision.ALLOW

    decision, _ = policy.evaluate("file_read", {"path": "/home/user/file"}, "prod")
    assert decision == CommandDecision.DENY
