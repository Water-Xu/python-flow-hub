"""image_builder 单测（Phase 4b：分层缓存键 + 供应链加固步骤）。"""

from __future__ import annotations

from app.core.k8s import image_builder


def test_dependency_image_tag_cpu_and_gpu():
    cpu = image_builder.dependency_image_tag("a" * 40)
    assert ":dep-" in cpu and "aaaa" in cpu
    gpu = image_builder.dependency_image_tag("b" * 40, gpu=True, cuda_version="12.4")
    assert "dep-124-" in gpu  # CUDA 维度入键（决策 11 GPU 分层）


def test_cloudbuild_config_supplychain():
    cfg = image_builder.build_cloudbuild_config("fastembed>=0.4\n", "img:dep-x")
    audit = any("pip-audit" in " ".join(s.get("args", [])) for s in cfg["steps"])
    assert audit
    assert "pyflow-builder@" in cfg["serviceAccount"]
    assert "install_deps.sh" in cfg["_dockerfile"]
    assert "storageSource" in cfg["source"]
    assert cfg["images"] == ["img:dep-x"]
