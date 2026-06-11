"""薄 wrapper：统一向量编码（文本 / 图片 URL，逻辑在 pyflow-vector-ingest wheel）。"""

from pyflow_vector import run_embed


def run(inputs: dict) -> dict:
    return run_embed(inputs)
