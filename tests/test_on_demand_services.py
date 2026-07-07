from eigsep_field import cli
from eigsep_field._services import RoleConfig, services_for_role


def _manifest():
    return {
        "packages": {},
        "services": {
            "redis": {"unit": "redis-server.service", "activation": "always"},
            "picomanager": {
                "unit": "picomanager.service",
                "activation": "role",
                "role": "panda",
            },
            "cmtvna": {
                "unit": "cmtvna.service",
                "activation": "on-demand",
                "role": "panda",
            },
        },
    }


def test_services_for_role_includes_on_demand_for_matching_role():
    services = _manifest()["services"]
    names = {n for n, _ in services_for_role(services, "panda")}
    assert "cmtvna" in names  # controllable + visible on the panda
    assert "picomanager" in names
    assert "redis" in names


def test_services_for_role_excludes_on_demand_for_other_role():
    services = _manifest()["services"]
    names = {n for n, _ in services_for_role(services, "backend")}
    assert "cmtvna" not in names
    assert "picomanager" not in names
    assert "redis" in names  # always-services are on every role


def test_check_services_reports_on_demand_present_not_failed(monkeypatch):
    # unit_health must NOT decide on-demand health (stopped is normal).
    # Other activations (always/role) still legitimately call unit_health,
    # so only fail if it's asked about the on-demand unit specifically.
    def fail_if_called(unit):
        if unit == "cmtvna.service":
            raise AssertionError("unit_health called for an on-demand unit")
        return True, "active"

    monkeypatch.setattr(cli, "unit_health", fail_if_called)
    ok, problems = cli._check_services(_manifest(), RoleConfig("panda"))
    assert problems == []
    assert any("cmtvna.service" in line and "on-demand" in line for line in ok)


def test_check_services_skips_on_demand_on_other_role(monkeypatch):
    monkeypatch.setattr(cli, "unit_health", lambda _u: (True, "active"))
    ok, problems = cli._check_services(_manifest(), RoleConfig("backend"))
    assert problems == []
    assert any("cmtvna.service" in line and "skipped" in line for line in ok)


def _capture_systemctl(monkeypatch, module):
    seen = []

    def fake(*args):
        seen.append(tuple(args))
        return 0, ""

    monkeypatch.setattr(module, "systemctl", fake)
    return seen


def test_enable_always_skips_on_demand(monkeypatch):
    from eigsep_field import _image_install

    monkeypatch.setattr(_image_install, "load_manifest", _manifest)
    seen = _capture_systemctl(monkeypatch, _image_install)
    assert _image_install._cmd_enable_always(None) == 0
    # Only the always-service (redis) is enabled at build time.
    assert seen == [("enable", "redis-server.service")]
    assert not any("cmtvna.service" in c for c in seen)


def test_apply_role_does_not_enable_on_demand(monkeypatch, tmp_path):
    from eigsep_field import cli
    from eigsep_field._services import RoleConfig

    monkeypatch.setattr(cli, "load_manifest", _manifest)
    # Neutralize the non-service side effects of apply-role.
    monkeypatch.setattr(cli, "_apply_role_static_ip", lambda _c: 0)
    monkeypatch.setattr(cli, "_apply_role_hostname", lambda _c: 0)
    monkeypatch.setattr(cli, "_apply_chrony_snippet", lambda _c: 0)
    monkeypatch.setattr(cli, "_apply_redis_snippet", lambda _c: 0)
    monkeypatch.setattr(cli, "_write_role_file", lambda _c: None)
    monkeypatch.setattr(cli, "parse_role_file", lambda _p: RoleConfig("panda"))
    seen = _capture_systemctl(monkeypatch, cli)

    role_conf_path = tmp_path / "eigsep-role.conf"
    role_conf_path.write_text("role = panda\n")

    class Args:
        role_conf = str(role_conf_path)

    assert cli._cmd_apply_role(Args()) == 0
    # picomanager (role) is enabled; cmtvna (on-demand) is NOT.
    assert ("enable", "--now", "picomanager.service") in seen
    assert not any("cmtvna.service" in c for c in seen)
