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
