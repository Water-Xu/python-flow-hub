"""requirements 白名单与 @gcs/@wheel 解析单测。"""

import pytest

from app.config import Settings
from app.core.k8s.requirements_policy import (
    lookup_requirements_text,
    package_name,
    parse_requirements,
    requirements_path_for_script,
    validate_requirements,
)
from app.errors import BusinessException


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_nested_requirements_path():
    assert "blocks/text_embedder/requirements.txt" in requirements_path_for_script(
        "blocks/text_embedder.py"
    )


def test_lookup_nested_requirements():
    resources = {"blocks/text_embedder/requirements.txt": "fastembed>=0.4\n"}
    assert lookup_requirements_text("blocks/text_embedder.py", resources).startswith("fastembed")


def test_parse_gcs_wheel():
    parsed = parse_requirements("@gcs:pyflow/wheels/foo.whl\nfastembed>=0.4\n")
    assert parsed.wheel_refs[0]["kind"] == "gcs"
    assert "fastembed" in parsed.pypi_lines[0]


def test_whitelist_rejects_unknown():
    s = _settings(pip_require_whitelist=True, pip_allowed_packages="fastembed")
    with pytest.raises(BusinessException):
        validate_requirements("unknown-pkg==1.0\n", s)


def test_whitelist_allows_fastembed():
    s = _settings(pip_require_whitelist=True, pip_allowed_packages="fastembed,pymilvus")
    parsed = validate_requirements("fastembed>=0.4\npymilvus>=2.4\n", s)
    assert len(parsed.pypi_lines) == 2


def test_package_name():
    assert package_name("fastembed>=0.4,<0.7") == "fastembed"
