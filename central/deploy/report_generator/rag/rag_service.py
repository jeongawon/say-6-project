"""RAG Service - FAISS-based retrieval from MIMIC clinical notes."""
import logging
import os
import json
import boto3
import numpy as np

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Lazy imports for heavy dependencies
faiss = None
sentence_transformers = None


class RAGService:
    """
    RAG service using FAISS for similarity search.
    
    Index sources:
    - MIMIC-NOTE: Clinical notes
    - MIMIC-CXR: Radiology reports
    """
    
    def __init__(self, rag_bucket):
        self.rag_bucket = rag_bucket
        self.s3 = boto3.client('s3')
        self.index = None
        self.documents = None
        self.encoder = None
        
        # Load index and encoder
        self._load_index()
        self._load_encoder()
    
    def _load_index(self):
        """Load FAISS index from S3."""
        global faiss
        
        try:
            if faiss is None:
                import faiss as faiss_module
                faiss = faiss_module
            
            # Download index from S3
            index_path = '/tmp/faiss_index.bin'
            docs_path = '/tmp/documents.json'
            
            self.s3.download_file(
                self.rag_bucket,
                'indices/faiss_index.bin',
                index_path
            )
            
            self.s3.download_file(
                self.rag_bucket,
                'indices/documents.json',
                docs_path
            )
            
            # Load index
            self.index = faiss.read_index(index_path)
            
            # Load documents
            with open(docs_path, 'r') as f:
                self.documents = json.load(f)
            
            logger.info(f"FAISS index loaded: {self.index.ntotal} vectors")
            
        except Exception as e:
            logger.error(f"Failed to load FAISS index: {e}")
            raise
    
    def _load_encoder(self):
        """Load sentence transformer model."""
        global sentence_transformers
        
        try:
            if sentence_transformers is None:
                from sentence_transformers import SentenceTransformer
                sentence_transformers = SentenceTransformer
            
            # Use lightweight model
            self.encoder = sentence_transformers('sentence-transformers/all-MiniLM-L6-v2')
            logger.info("Sentence encoder loaded")
            
        except Exception as e:
            logger.error(f"Failed to load encoder: {e}")
            raise
    
    def search(self, query, top_k=5):
        """
        Search for relevant clinical notes.
        
        Args:
            query: Search query string
            top_k: Number of results to return
        
        Returns:
            List of relevant documents with scores
        """
        if not self.index or not self.encoder:
            logger.warning("RAG service not properly initialized")
            return []
        
        try:
            # Encode query
            query_vector = self.encoder.encode([query])[0]
            query_vector = np.array([query_vector], dtype='float32')
            
            # Search
            distances, indices = self.index.search(query_vector, top_k)
            
            # Retrieve documents
            results = []
            for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
                if idx < len(self.documents):
                    doc = self.documents[idx]
                    results.append({
                        'text': doc.get('text', ''),
                        'source': doc.get('source', 'unknown'),
                        'score': float(1 / (1 + dist)),  # Convert distance to similarity
                        'metadata': doc.get('metadata', {})
                    })
            
            logger.info(f"RAG search returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"RAG search failed: {e}")
            return []
