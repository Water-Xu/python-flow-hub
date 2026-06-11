"""薄 wrapper：Milvus 写入（逻辑在 pyflow-vector-ingest wheel）。"""

from pyflow_vector import run_write


def run(inputs: dict) -> dict:
    return run_write(inputs)
