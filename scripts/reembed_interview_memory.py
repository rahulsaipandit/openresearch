"""
One-time migration: re-embed the interview_memory Chroma collection under a
new embedding function.

Why this exists: chromadb's default embedder (ONNX MiniLM, 384-dim) and
nomic-embed-text-v1.5 (768-dim) can't coexist in the same collection — see
docs/designInterviewTool.md's "Embedding model: nomic-embed-text-v1.5, run
in-process (no server)" section. Switching interview_memory.embedding_model
in config.yaml does NOT retroactively re-embed existing data; run this
first, or every existing candidate's retrieval silently returns nothing
(dimension mismatch) or errors, depending on the chromadb version.

What it does: reads every id/document/metadata triple out of the OLD
collection (at the current config.yaml path) and re-adds them, re-embedded,
into a NEW collection at a separate path — it never touches or deletes the
old collection, so this is safe to run speculatively and re-run if
interrupted. Once you've verified the new path looks right, point
interview_memory.data_dir (or run a one-line manual copy) at it and update
embedding_model to "nomic-embed-text-v1.5".

Usage:
    python scripts/reembed_interview_memory.py [--config config.yaml] [--batch-size 64]
"""

import argparse
import logging

import yaml

from memory.interview_vector_store import InterviewVectorStore
from store.embedding_functions import get_nomic_embedding_function

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    data_dir = cfg.get("interview_memory", {}).get("data_dir", "data")

    old_path = f"{data_dir}/interview_memory_vectors"
    new_path = f"{data_dir}/interview_memory_vectors_nomic"

    logger.info(f"Reading existing collection from {old_path} ...")
    old_store = InterviewVectorStore(old_path)  # default embedder — read-only use here
    all_records = old_store._collection.get()  # ids/documents/metadatas, no embeddings needed
    ids = all_records.get("ids", [])
    documents = all_records.get("documents", [])
    metadatas = all_records.get("metadatas", [])
    total = len(ids)
    logger.info(f"Found {total} records to re-embed.")

    if total == 0:
        logger.info("Nothing to migrate.")
        return

    logger.info(f"Writing re-embedded records to {new_path} (loads the nomic model)...")
    new_store = InterviewVectorStore(new_path, embedding_function=get_nomic_embedding_function())

    batch_size = args.batch_size
    for start in range(0, total, batch_size):
        batch_ids = ids[start : start + batch_size]
        batch_docs = documents[start : start + batch_size]
        batch_meta = metadatas[start : start + batch_size]
        new_store._add_many(batch_ids, batch_docs, batch_meta)
        logger.info(f"  {min(start + batch_size, total)}/{total} re-embedded")

    logger.info(
        f"Done. {total} records re-embedded into {new_path}.\n"
        f"Next steps: verify the new collection looks right, then either move "
        f"{new_path} to {old_path} (replacing it) or update "
        f"interview_memory.data_dir, and set interview_memory.embedding_model "
        f"to \"nomic-embed-text-v1.5\" in {args.config}."
    )


if __name__ == "__main__":
    main()
