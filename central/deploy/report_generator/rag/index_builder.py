"""
Index builder for RAG system.

This script builds FAISS index from MIMIC-NOTE and MIMIC-CXR data.
Run this separately to prepare the RAG index before deployment.

Usage:
    python index_builder.py --mimic-note-path <path> --mimic-cxr-path <path> --output-dir <dir>
"""
import argparse
import json
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_index(mimic_note_path, mimic_cxr_path, output_dir):
    """
    Build FAISS index from MIMIC data.
    
    Args:
        mimic_note_path: Path to MIMIC-NOTE data
        mimic_cxr_path: Path to MIMIC-CXR radiology reports
        output_dir: Output directory for index files
    """
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.error("Please install: pip install faiss-cpu sentence-transformers")
        return
    
    logger.info("Loading sentence transformer...")
    encoder = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    
    # Load documents
    logger.info("Loading MIMIC documents...")
    documents = []
    
    # Load MIMIC-NOTE
    if mimic_note_path and Path(mimic_note_path).exists():
        documents.extend(load_mimic_notes(mimic_note_path))
    
    # Load MIMIC-CXR
    if mimic_cxr_path and Path(mimic_cxr_path).exists():
        documents.extend(load_mimic_cxr(mimic_cxr_path))
    
    logger.info(f"Loaded {len(documents)} documents")
    
    # Encode documents
    logger.info("Encoding documents...")
    texts = [doc['text'] for doc in documents]
    embeddings = encoder.encode(texts, show_progress_bar=True)
    embeddings = np.array(embeddings, dtype='float32')
    
    # Build FAISS index
    logger.info("Building FAISS index...")
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)
    
    # Save index
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    index_file = output_path / 'faiss_index.bin'
    docs_file = output_path / 'documents.json'
    
    faiss.write_index(index, str(index_file))
    
    with open(docs_file, 'w') as f:
        json.dump(documents, f)
    
    logger.info(f"Index saved to {output_dir}")
    logger.info(f"Total vectors: {index.ntotal}")


def load_mimic_notes(path):
    """Load MIMIC-NOTE data."""
    # Placeholder - implement based on your MIMIC-NOTE format
    logger.info(f"Loading MIMIC-NOTE from {path}")
    documents = []
    
    # Example structure:
    # documents.append({
    #     'text': note_text,
    #     'source': 'MIMIC-NOTE',
    #     'metadata': {'note_id': ..., 'category': ...}
    # })
    
    return documents


def load_mimic_cxr(path):
    """Load MIMIC-CXR radiology reports."""
    # Placeholder - implement based on your MIMIC-CXR format
    logger.info(f"Loading MIMIC-CXR from {path}")
    documents = []
    
    # Example structure:
    # documents.append({
    #     'text': report_text,
    #     'source': 'MIMIC-CXR',
    #     'metadata': {'study_id': ..., 'subject_id': ...}
    # })
    
    return documents


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build RAG index from MIMIC data')
    parser.add_argument('--mimic-note-path', help='Path to MIMIC-NOTE data')
    parser.add_argument('--mimic-cxr-path', help='Path to MIMIC-CXR data')
    parser.add_argument('--output-dir', required=True, help='Output directory for index')
    
    args = parser.parse_args()
    
    build_index(args.mimic_note_path, args.mimic_cxr_path, args.output_dir)
