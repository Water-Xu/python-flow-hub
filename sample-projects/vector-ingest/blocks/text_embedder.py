"""薄 wrapper：文本转向量（逻辑在 pyflow-vector-ingest wheel）。"""

from pyflow_vector import run_embed


def run(inputs: dict) -> dict:
    return run_embed(inputs)
