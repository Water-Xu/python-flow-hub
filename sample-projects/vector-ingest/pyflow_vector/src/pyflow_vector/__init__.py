"""向量入库共享库（pyflowhub_pack 方案：逻辑在 wheel，块为薄 wrapper）。"""

from pyflow_vector.embedder import run_embed, run_embed_image, run_embed_text
from pyflow_vector.milvus_store import run_write

__all__ = ["run_embed", "run_embed_text", "run_embed_image", "run_write"]
