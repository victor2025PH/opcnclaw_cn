"""
Tests for the health check / startup self-check system.
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server.health import HealthChecker, ComponentStatus


class TestHealthChecker:

    def test_init(self):
        hc = HealthChecker()
        assert hc is not None

    def test_check_python_version(self):
        hc = HealthChecker()
        result = hc.check_python()
        assert isinstance(result, ComponentStatus)
        assert result.name == "Python"
        assert result.ok is True
        assert "3." in result.version

    def test_check_packages(self):
        hc = HealthChecker()
        result = hc.check_core_packages()
        assert isinstance(result, ComponentStatus)
        assert result.name == "核心依赖"

    def test_check_ssl(self, tmp_path):
        hc = HealthChecker(base_dir=str(tmp_path))
        result = hc.check_ssl()
        assert isinstance(result, ComponentStatus)
        assert result.name == "SSL 证书"
        assert result.ok is False

        (tmp_path / "ssl").mkdir()
        (tmp_path / "ssl" / "cert.pem").write_text("fake")
        (tmp_path / "ssl" / "key.pem").write_text("fake")
        result2 = hc.check_ssl()
        assert result2.ok is True

    def test_check_config(self, tmp_path):
        hc = HealthChecker(base_dir=str(tmp_path))
        result = hc.check_config()
        assert isinstance(result, ComponentStatus)
        assert result.name == "配置文件"

    def test_run_all(self):
        hc = HealthChecker()
        results = hc.run_all()
        assert isinstance(results, list)
        assert len(results) >= 4
        assert all(isinstance(r, ComponentStatus) for r in results)

    def test_summary(self):
        hc = HealthChecker()
        summary = hc.summary()
        assert isinstance(summary, dict)
        assert "healthy" in summary
        assert "checks" in summary
        assert isinstance(summary["checks"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
