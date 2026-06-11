"""Embedding + MinIO 模型缓存（文本 / 图片 / 统一入口）。"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from pyflow_vector.image_loader import auto_ids as _auto_image_ids
from pyflow_vector.image_loader import load_images_to_temp, _normalize_urls

_DEFAULT_TEXT_MODEL = "BAAI/bge-small-zh-v1.5"
_DEFAULT_IMAGE_MODEL = "openai/clip-vit-base-patch32"
_CACHE_DIR = os.environ.get("FASTEMBED_CACHE_PATH", "/tmp/fastembed_cache")

_model_cache: dict[str, Any] = {}


def _sync_model_from_minio(model_name: str, cache_dir: str) -> None:
    """若配置了 PYFLOW_VECTOR_MODEL_PREFIX，从 MinIO 同步 fastembed 模型目录（仅一次）。"""
    prefix = (os.environ.get("PYFLOW_VECTOR_MODEL_PREFIX") or "").strip().rstrip("/")
    if not prefix:
        return
    try:
        from minio import Minio
    except ImportError:
        return

    endpoint = os.environ.get("MINIO_ENDPOINT", "")
    ak = os.environ.get("MINIO_ACCESS_KEY", "")
    sk = os.environ.get("MINIO_SECRET_KEY", "")
    if not endpoint or not ak:
        return

    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
    bucket, _, obj_prefix = prefix.partition("/")
    if not bucket:
        return
    client = Minio(endpoint, access_key=ak, secret_key=sk, secure=secure)
    target = os.path.join(cache_dir, "models", model_name.replace("/", "--"))
    os.makedirs(target, exist_ok=True)
    obj_prefix = f"{obj_prefix}/{model_name}".lstrip("/")
    for obj in client.list_objects(bucket, prefix=obj_prefix, recursive=True):
        if obj.is_dir:
            continue
        rel = obj.object_name[len(obj_prefix):].lstrip("/")
        local = os.path.join(target, rel)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        if not os.path.isfile(local):
            client.fget_object(bucket, obj.object_name, local)


def _normalize_texts(raw: Any) -> list[str]:
    if raw is None:
        raise ValueError("inputs.texts 不能为空")
    if isinstance(raw, str):
        items = [raw.strip()]
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        raise ValueError("inputs.texts 必须是 string 或 string[]")
    if not items:
        raise ValueError("inputs.texts 解析后为空")
    return items


def _get_text_embedder(model_name: str):
    key = f"text:{model_name}"
    if key in _model_cache:
        return _model_cache[key]
    os.makedirs(_CACHE_DIR, exist_ok=True)
    _sync_model_from_minio(model_name, _CACHE_DIR)
    from fastembed import TextEmbedding

    embedder = TextEmbedding(model_name=model_name, cache_dir=_CACHE_DIR)
    _model_cache[key] = embedder
    return embedder


def _get_image_embedder(model_name: str):
    key = f"image:{model_name}"
    if key in _model_cache:
        return _model_cache[key]
    os.makedirs(_CACHE_DIR, exist_ok=True)
    _sync_model_from_minio(model_name, _CACHE_DIR)
    from fastembed import ImageEmbedding

    embedder = ImageEmbedding(model_name=model_name, cache_dir=_CACHE_DIR)
    _model_cache[key] = embedder
    return embedder


def _auto_text_ids(texts: list[str]) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest()[:32] for t in texts]


def _as_vectors(raw_vectors: Any) -> tuple[list[list[float]], int]:
    vectors = [v.tolist() if hasattr(v, "tolist") else list(v) for v in raw_vectors]
    if not vectors:
        raise ValueError("embedding 结果为空")
    return vectors, len(vectors[0])


def _resolve_captions(captions: Any, urls: list[str]) -> list[str]:
    if captions is None:
        return list(urls)
    if isinstance(captions, str):
        items = [captions.strip() or urls[0]]
    elif isinstance(captions, list):
        items = [str(x).strip() or urls[i] for i, x in enumerate(captions)]
    else:
        raise ValueError("inputs.captions 必须是 string 或 string[]")
    if len(items) != len(urls):
        raise ValueError("inputs.captions 长度必须与 image_urls 一致")
    return items


def run_embed_text(inputs: dict) -> dict:
    """纯文本向量（BGE 等 TextEmbedding 模型）。"""
    texts = _normalize_texts(inputs.get("texts"))
    collection_name = str(inputs.get("collection_name") or "").strip()
    if not collection_name:
        raise ValueError("inputs.collection_name 不能为空")

    model_name = str(inputs.get("model") or _DEFAULT_TEXT_MODEL)
    ids = inputs.get("ids")
    if ids is not None:
        ids = [str(x) for x in ids]
        if len(ids) != len(texts):
            raise ValueError("inputs.ids 长度必须与 texts 一致")

    vectors, dim = _as_vectors(list(_get_text_embedder(model_name).embed(texts)))

    return {
        "modality": "text",
        "modalities": ["text"] * len(texts),
        "texts": texts,
        "media_urls": [""] * len(texts),
        "embeddings": vectors,
        "vector_dim": dim,
        "model": model_name,
        "collection_name": collection_name,
        "ids": ids or _auto_text_ids(texts),
        "source": str(inputs.get("source") or "flowhub"),
        "metadata": inputs.get("metadata") or {},
        "count": len(texts),
    }


def run_embed_image(inputs: dict) -> dict:
    """图片 URL / MinIO / base64 转向量（CLIP 等 ImageEmbedding 模型）。"""
    urls = _normalize_urls(inputs.get("image_urls"))
    collection_name = str(inputs.get("collection_name") or "").strip()
    if not collection_name:
        raise ValueError("inputs.collection_name 不能为空")

    model_name = str(inputs.get("model") or _DEFAULT_IMAGE_MODEL)
    captions = _resolve_captions(inputs.get("captions"), urls)
    ids = inputs.get("ids")
    if ids is not None:
        ids = [str(x) for x in ids]
        if len(ids) != len(urls):
            raise ValueError("inputs.ids 长度必须与 image_urls 一致")

    paths, tmp = load_images_to_temp(urls)
    try:
        vectors, dim = _as_vectors(list(_get_image_embedder(model_name).embed(paths)))
    finally:
        tmp.cleanup()

    return {
        "modality": "image",
        "modalities": ["image"] * len(urls),
        "texts": captions,
        "media_urls": urls,
        "embeddings": vectors,
        "vector_dim": dim,
        "model": model_name,
        "collection_name": collection_name,
        "ids": ids or _auto_image_ids(urls),
        "source": str(inputs.get("source") or "flowhub"),
        "metadata": inputs.get("metadata") or {},
        "count": len(urls),
    }


def run_embed(inputs: dict) -> dict:
    """统一入口：modality=text|image|auto（默认 auto 按字段推断）。"""
    modality = str(inputs.get("modality") or "auto").strip().lower()
    has_text = inputs.get("texts") not in (None, "", [])
    has_image = inputs.get("image_urls") not in (None, "", [])

    if modality == "auto":
        if has_text and has_image:
            raise ValueError("modality=auto 时不能同时传 texts 与 image_urls，请显式指定 modality")
        if has_image:
            modality = "image"
        elif has_text:
            modality = "text"
        else:
            raise ValueError("请提供 texts（文本）或 image_urls（图片 URL）")

    if modality == "image":
        return run_embed_image(inputs)
    if modality == "text":
        return run_embed_text(inputs)
    raise ValueError("modality 仅支持 text、image 或 auto")
