"""薄 wrapper：图片 URL 转向量（等价于 vector_embedder + modality=image）。"""

from pyflow_vector import run_embed_image


def run(inputs: dict) -> dict:
    return run_embed_image(inputs)
