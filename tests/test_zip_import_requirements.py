"""zip 导入 requirements.txt 关联单测。"""

from app.core.flow.zip_import import lookup_requirements_text, requirements_path_for_script


def test_requirements_path_for_script():
    paths = requirements_path_for_script("embed/text_embedder.py")
    assert "embed/text_embedder/requirements.txt" in paths
    assert "embed/requirements.txt" in paths


def test_lookup_requirements_text():
    resources = {
        "embed/text_embedder/requirements.txt": "fastembed>=0.4.0\n",
        "data/sample.json": "{}",
    }
    assert lookup_requirements_text("embed/text_embedder.py", resources) == "fastembed>=0.4.0\n"
    assert lookup_requirements_text("store/milvus_writer.py", resources) == ""
