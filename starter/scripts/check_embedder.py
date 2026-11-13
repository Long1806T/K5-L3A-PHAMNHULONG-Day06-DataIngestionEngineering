"""Sanity checks for the local ONNX embedder (run from starter/: python -m scripts.check_embedder).

1. Reference similarities: the all-MiniLM-L6-v2 model card example
   ("The weather is lovely today." / "It's so sunny outside!" / "He drove to the stadium.")
   reports cosine similarities of about 0.6660 (0-1) and 0.1046 (0-2).
2. Padding invariance: a text embedded alone == the same text inside a padded batch.
3. Determinism: two runs give identical vectors.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.embeddings import OnnxMiniLMEmbedder  # noqa: E402

emb = OnnxMiniLMEmbedder()
s = ["The weather is lovely today.", "It's so sunny outside!", "He drove to the stadium."]
v = np.array(emb.embed_documents(s))
sim = v @ v.T
print(f"model={emb.model_name} dims={len(v[0])}")
print(f"sim(0,1)={sim[0,1]:.4f} (card ~0.6660)  sim(0,2)={sim[0,2]:.4f} (card ~0.1046)  sim(1,2)={sim[1,2]:.4f} (card ~0.1411)")
alone = np.array(emb.embed_query(s[0]))
long_batch = np.array(emb.embed_documents([s[0], "word " * 200]))[0]
print(f"padding invariance max|diff|={np.abs(alone - long_batch).max():.2e}")
print(f"determinism max|diff|={np.abs(alone - np.array(emb.embed_query(s[0]))).max():.2e}")
ok = abs(sim[0, 1] - 0.6660) < 0.01 and abs(sim[0, 2] - 0.1046) < 0.01 and np.abs(alone - long_batch).max() < 1e-4
print("Embedder OK" if ok else "Embedder check FAILED")
sys.exit(0 if ok else 1)
