"""Real local embedding model: sentence-transformers/all-MiniLM-L6-v2 (ONNX export).

* Weights: ``model.onnx`` (+ ``tokenizer.json``) from the Apache-2.0 repository
  github.com/clems4ever/all-minilm-l6-v2-go (directory ``all_minilm_l6_v2``), an
  ONNX export of sentence-transformers/all-MiniLM-L6-v2 whose graph already
  contains mean pooling (output ``sentence_embedding``, 384 dims).
* Runtime: onnxruntime (CPU).  The BERT WordPiece tokenizer is re-implemented
  below from ``tokenizer.json`` because the ``tokenizers`` package was not
  installable offline; ``scripts/check_embedder.py`` checks it against the
  similarity values published on the model card.
* Query and document are encoded the same way (this model has no prefixes);
  vectors are L2-normalised so cosine distance in pgvector is meaningful.

There is no fallback: if the model files are missing the constructor raises.
"""
from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, question: str) -> list[float]: ...


# ----------------------------------------------------------------- tokenizer
def _is_punct(ch: str) -> bool:
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp: int) -> bool:
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF
            or 0x2A700 <= cp <= 0x2B73F or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF
            or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


class BertWordPiece:
    """BertNormalizer(lowercase, strip accents) + BertPreTokenizer + WordPiece."""

    def __init__(self, tokenizer_json: Path, max_length: int) -> None:
        spec = json.loads(tokenizer_json.read_text(encoding="utf-8"))
        if spec["model"]["type"] != "WordPiece":
            raise ValueError("expected a WordPiece tokenizer.json")
        self.vocab: dict[str, int] = spec["model"]["vocab"]
        self.unk = spec["model"]["unk_token"]
        self.prefix = spec["model"]["continuing_subword_prefix"]
        self.max_chars = spec["model"]["max_input_chars_per_word"]
        self.cls, self.sep = self.vocab["[CLS]"], self.vocab["[SEP]"]
        self.max_length = max_length

    def _normalize(self, text: str) -> str:
        out = []
        for ch in text:
            cp = ord(ch)
            if cp == 0 or cp == 0xFFFD or (unicodedata.category(ch).startswith("C") and ch not in "\t\n\r"):
                continue
            if ch in "\t\n\r" or unicodedata.category(ch) == "Zs":
                out.append(" ")
            elif _is_cjk(cp):
                out.append(f" {ch} ")
            else:
                out.append(ch)
        text = "".join(out).lower()
        text = unicodedata.normalize("NFD", text)
        return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")

    def _pretokenize(self, text: str) -> list[str]:
        words: list[str] = []
        for token in text.split():
            cur = ""
            for ch in token:
                if _is_punct(ch):
                    if cur:
                        words.append(cur)
                        cur = ""
                    words.append(ch)
                else:
                    cur += ch
            if cur:
                words.append(cur)
        return words

    def _wordpiece(self, word: str) -> list[int]:
        if len(word) > self.max_chars:
            return [self.vocab[self.unk]]
        ids, start = [], 0
        while start < len(word):
            end, found = len(word), None
            while start < end:
                sub = word[start:end] if start == 0 else self.prefix + word[start:end]
                if sub in self.vocab:
                    found = self.vocab[sub]
                    break
                end -= 1
            if found is None:
                return [self.vocab[self.unk]]
            ids.append(found)
            start = end
        return ids

    def encode(self, text: str) -> tuple[list[int], bool]:
        ids: list[int] = []
        for word in self._pretokenize(self._normalize(text)):
            ids.extend(self._wordpiece(word))
        truncated = len(ids) > self.max_length - 2
        ids = ids[: self.max_length - 2]
        return [self.cls, *ids, self.sep], truncated


# ----------------------------------------------------------------- embedder
DEFAULT_MODEL_DIR = Path(os.getenv("EMBEDDING_MODEL_DIR", "models/all-MiniLM-L6-v2-onnx"))


class OnnxMiniLMEmbedder:
    model_name = "sentence-transformers/all-MiniLM-L6-v2 (ONNX, onnxruntime CPU)"
    dimensions = 384
    max_length = 256  # sentence-transformers max_seq_length for this model

    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR, batch_size: int = 32) -> None:
        import onnxruntime as ort

        model_dir = Path(model_dir)
        onnx_path, tok_path = model_dir / "model.onnx", model_dir / "tokenizer.json"
        if not onnx_path.exists() or not tok_path.exists():
            raise FileNotFoundError(
                f"Embedding model not found in {model_dir}. See README: download model.onnx and "
                "tokenizer.json (no mock fallback is used).")
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(onnx_path), opts, providers=["CPUExecutionProvider"])
        outputs = {o.name: o.shape for o in self.session.get_outputs()}
        if "sentence_embedding" not in outputs or outputs["sentence_embedding"][-1] != self.dimensions:
            raise ValueError(f"unexpected ONNX outputs: {outputs}")
        self.tokenizer = BertWordPiece(tok_path, self.max_length)
        self.batch_size = batch_size
        self.truncated_inputs = 0

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            encoded = []
            for t in batch:
                ids, truncated = self.tokenizer.encode(t)
                self.truncated_inputs += int(truncated)
                encoded.append(ids)
            width = max(len(e) for e in encoded)
            input_ids = np.zeros((len(batch), width), dtype=np.int64)
            mask = np.zeros_like(input_ids)
            for r, ids in enumerate(encoded):
                input_ids[r, :len(ids)] = ids
                mask[r, :len(ids)] = 1
            out = self.session.run(["sentence_embedding"], {
                "input_ids": input_ids, "attention_mask": mask,
                "token_type_ids": np.zeros_like(input_ids)})[0]
            vectors.append(out)
        mat = np.vstack(vectors).astype(np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        if np.any(norms == 0) or not np.all(np.isfinite(mat)):
            raise ValueError("embedding model returned zero or non-finite vectors")
        return mat / norms

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts).tolist() if texts else []

    def embed_query(self, question: str) -> list[float]:
        return self._encode([question])[0].tolist()


# Backwards-compatible name used by the starter skeleton.
MyEmbedder = OnnxMiniLMEmbedder
