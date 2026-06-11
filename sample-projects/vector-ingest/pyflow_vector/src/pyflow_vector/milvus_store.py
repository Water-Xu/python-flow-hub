"""Milvus 写入（支持 text / image 多模态字段）。"""

from __future__ import annotations

import json
import os
from typing import Any

_CONN = "pyflow_default"


def _milvus_uri() -> str:
    uri = (os.environ.get("MILVUS_URI") or "").strip()
    if not uri:
        raise RuntimeError("未配置 MILVUS_URI")
    return uri


def _connect() -> None:
    from pymilvus import connections

    if _CONN in connections.list_connections():
        return
    connections.connect(alias=_CONN, uri=_milvus_uri())


def _field_names(col) -> set[str]:
    return {f.name for f in col.schema.fields}


def _ensure_collection(name: str, dim: int, metric: str, *, multimodal: bool):
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

    if utility.has_collection(name, using=_CONN):
        col = Collection(name, using=_CONN)
        emb = next(f for f in col.schema.fields if f.name == "embedding")
        if emb.params.get("dim") != dim:
            raise ValueError(f"集合 {name} 维度 {emb.params.get('dim')} != {dim}")
        col.load()
        return col

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="meta_json", dtype=DataType.VARCHAR, max_length=65535),
    ]
    if multimodal:
        fields.extend([
            FieldSchema(name="modality", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="media_url", dtype=DataType.VARCHAR, max_length=2048),
        ])
    col = Collection(name, CollectionSchema(fields), using=_CONN)
    col.create_index("embedding", {"index_type": "AUTOINDEX", "metric_type": metric})
    col.load()
    return col


def _insert_rows(col, payload: dict[str, list[Any]]) -> None:
    names = _field_names(col)
    data = [payload[k] for k in col.schema.fields if k.name in payload and k.name in names]
    col.insert(data)
    col.flush()


def run_write(inputs: dict) -> dict:
    collection_name = str(inputs.get("collection_name") or "").strip()
    texts = inputs.get("texts") or []
    embeddings = inputs.get("embeddings") or []
    ids = inputs.get("ids") or []
    media_urls = inputs.get("media_urls") or [""] * len(texts)
    modalities = inputs.get("modalities") or [str(inputs.get("modality") or "text")] * len(texts)

    if not collection_name or not texts or not embeddings or not ids:
        raise ValueError("collection_name / texts / embeddings / ids 不能为空")
    if not (len(texts) == len(embeddings) == len(ids)):
        raise ValueError("texts、embeddings、ids 长度必须一致")
    if len(media_urls) != len(texts):
        raise ValueError("media_urls 长度必须与 texts 一致")
    if len(modalities) != len(texts):
        raise ValueError("modalities 长度必须与 texts 一致")

    dim = int(inputs.get("vector_dim") or len(embeddings[0]))
    metric = str(inputs.get("metric_type") or "COSINE").upper()
    source = str(inputs.get("source") or "flowhub")
    meta_json = json.dumps(inputs.get("metadata") or {}, ensure_ascii=False)
    multimodal = any(m != "text" or u for m, u in zip(modalities, media_urls))

    _connect()
    col = _ensure_collection(collection_name, dim, metric, multimodal=multimodal)
    names = _field_names(col)

    payload: dict[str, list[Any]] = {
        "id": [str(x) for x in ids],
        "text": [str(x) for x in texts],
        "embedding": embeddings,
        "source": [source] * len(ids),
        "meta_json": [meta_json] * len(ids),
    }
    if "modality" in names:
        payload["modality"] = [str(x) for x in modalities]
    if "media_url" in names:
        payload["media_url"] = [str(x) for x in media_urls]

    _insert_rows(col, payload)

    return {
        "collection_name": collection_name,
        "inserted": len(ids),
        "ids": [str(x) for x in ids],
        "vector_dim": dim,
        "metric_type": metric,
        "modality": inputs.get("modality") or modalities[0],
        "milvus_uri": _milvus_uri(),
    }
