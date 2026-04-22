# RAG Setup Guide

## 개요

RAG (Retrieval-Augmented Generation) 시스템은 MIMIC-NOTE와 MIMIC-CXR 데이터베이스에서 유사한 임상 케이스를 검색하여 리포트 생성에 활용합니다.

## 아키텍처

```
MIMIC Data → Index Builder → FAISS Index → S3
                                              ↓
                                         RAG Service
                                              ↓
                                    Bedrock Report Generator
```

## 사전 준비

### 1. 필요한 데이터

- **MIMIC-NOTE**: 임상 노트 데이터
- **MIMIC-CXR**: 방사선 리포트 데이터

MIMIC 데이터 접근: https://physionet.org/content/mimiciv/

### 2. Python 환경

```bash
pip install faiss-cpu sentence-transformers pandas numpy
```

## Index 구축

### 1. 데이터 준비

#### MIMIC-NOTE 처리

```python
import pandas as pd

# Load MIMIC-NOTE data
notes_df = pd.read_csv('mimic-iv/note/discharge.csv.gz')

# Filter relevant notes
clinical_notes = notes_df[
    notes_df['note_type'].isin(['Discharge summary', 'Radiology', 'ECG'])
]

# Extract text
documents = []
for idx, row in clinical_notes.iterrows():
    documents.append({
        'text': row['text'],
        'source': 'MIMIC-NOTE',
        'metadata': {
            'note_id': row['note_id'],
            'subject_id': row['subject_id'],
            'note_type': row['note_type']
        }
    })
```

#### MIMIC-CXR 처리

```python
# Load MIMIC-CXR reports
cxr_df = pd.read_csv('mimic-cxr/mimic-cxr-reports.csv.gz')

# Extract findings and impressions
for idx, row in cxr_df.iterrows():
    # Combine findings and impression
    text = f"FINDINGS: {row['findings']}\nIMPRESSION: {row['impression']}"
    
    documents.append({
        'text': text,
        'source': 'MIMIC-CXR',
        'metadata': {
            'study_id': row['study_id'],
            'subject_id': row['subject_id']
        }
    })
```

### 2. Index 빌드

```bash
cd deploy/report_generator/rag

python index_builder.py \
  --mimic-note-path /path/to/mimic-note \
  --mimic-cxr-path /path/to/mimic-cxr \
  --output-dir ./indices
```

이 스크립트는 다음을 생성합니다:
- `faiss_index.bin`: FAISS 인덱스 파일
- `documents.json`: 문서 메타데이터

### 3. S3 업로드

```bash
# RAG 버킷 이름 확인
RAG_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name emergency-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`RagBucketName`].OutputValue' \
  --output text)

# 인덱스 파일 업로드
aws s3 cp ./indices/faiss_index.bin s3://$RAG_BUCKET/indices/
aws s3 cp ./indices/documents.json s3://$RAG_BUCKET/indices/
```

## Index Builder 커스터마이징

### 데이터 필터링

특정 조건의 케이스만 포함:

```python
def load_mimic_notes(path):
    notes_df = pd.read_csv(f'{path}/discharge.csv.gz')
    
    # Filter by note type
    notes_df = notes_df[notes_df['note_type'] == 'Discharge summary']
    
    # Filter by length (너무 짧거나 긴 노트 제외)
    notes_df = notes_df[
        (notes_df['text'].str.len() > 100) &
        (notes_df['text'].str.len() < 10000)
    ]
    
    documents = []
    for idx, row in notes_df.iterrows():
        documents.append({
            'text': row['text'],
            'source': 'MIMIC-NOTE',
            'metadata': {
                'note_id': row['note_id'],
                'subject_id': row['subject_id']
            }
        })
    
    return documents
```

### 텍스트 전처리

```python
import re

def preprocess_text(text):
    """Clean and normalize clinical text."""
    
    # Remove PHI placeholders
    text = re.sub(r'\[\*\*.*?\*\*\]', '[REDACTED]', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove special characters
    text = re.sub(r'[^\w\s\.\,\:\;\-]', '', text)
    
    return text.strip()

# Apply preprocessing
documents = []
for doc in raw_documents:
    doc['text'] = preprocess_text(doc['text'])
    documents.append(doc)
```

### 청크 분할

긴 문서를 작은 청크로 분할:

```python
def chunk_text(text, chunk_size=500, overlap=50):
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    
    for i in range(0, len(words), chunk_size - overlap):
        chunk = ' '.join(words[i:i + chunk_size])
        chunks.append(chunk)
    
    return chunks

# Apply chunking
chunked_documents = []
for doc in documents:
    chunks = chunk_text(doc['text'])
    for i, chunk in enumerate(chunks):
        chunked_documents.append({
            'text': chunk,
            'source': doc['source'],
            'metadata': {
                **doc['metadata'],
                'chunk_id': i
            }
        })
```

## 임베딩 모델 선택

### 기본 모델 (경량)
```python
encoder = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
# Dimension: 384
# Speed: Fast
# Quality: Good
```

### 의료 특화 모델
```python
encoder = SentenceTransformer('pritamdeka/S-PubMedBert-MS-MARCO')
# Dimension: 768
# Speed: Medium
# Quality: Better for medical text
```

### 고성능 모델
```python
encoder = SentenceTransformer('sentence-transformers/all-mpnet-base-v2')
# Dimension: 768
# Speed: Slower
# Quality: Best
```

## FAISS 인덱스 타입

### Flat Index (기본)
```python
index = faiss.IndexFlatL2(dimension)
# 정확도: 최고
# 속도: 느림 (대용량 데이터에 부적합)
# 메모리: 높음
```

### IVF Index (대용량)
```python
nlist = 100  # Number of clusters
quantizer = faiss.IndexFlatL2(dimension)
index = faiss.IndexIVFFlat(quantizer, dimension, nlist)

# Train index
index.train(embeddings)
index.add(embeddings)

# Search with nprobe
index.nprobe = 10  # Number of clusters to search
```

### HNSW Index (빠른 검색)
```python
index = faiss.IndexHNSWFlat(dimension, 32)
# 정확도: 높음
# 속도: 빠름
# 메모리: 중간
```

## RAG Service 설정

### Lambda 메모리 조정

FAISS 인덱스 크기에 따라 Lambda 메모리 조정:

```yaml
ReportGeneratorFunction:
  Properties:
    MemorySize: 2048  # 2GB (인덱스 크기에 따라 조정)
    Timeout: 120
```

### 인덱스 캐싱

Lambda 재사용을 위한 전역 변수 사용:

```python
# Global variables for caching
_rag_service = None

def handler(event, context):
    global _rag_service
    
    if _rag_service is None:
        _rag_service = RAGService(RAG_BUCKET)
    
    # Use cached service
    results = _rag_service.search(query)
```

## 검색 최적화

### 쿼리 확장

```python
def expand_query(query):
    """Expand query with synonyms and related terms."""
    
    # Medical term synonyms
    synonyms = {
        'MI': ['myocardial infarction', 'heart attack'],
        'CHF': ['congestive heart failure', 'heart failure'],
        'COPD': ['chronic obstructive pulmonary disease'],
        'PE': ['pulmonary embolism']
    }
    
    expanded = query
    for abbr, terms in synonyms.items():
        if abbr in query:
            expanded += ' ' + ' '.join(terms)
    
    return expanded
```

### 재순위화 (Re-ranking)

```python
def rerank_results(query, results):
    """Re-rank results based on additional criteria."""
    
    # Extract key terms from query
    key_terms = extract_medical_terms(query)
    
    # Score each result
    scored_results = []
    for result in results:
        score = result['score']
        
        # Boost score if key terms present
        for term in key_terms:
            if term.lower() in result['text'].lower():
                score *= 1.2
        
        scored_results.append({
            **result,
            'reranked_score': score
        })
    
    # Sort by reranked score
    scored_results.sort(key=lambda x: x['reranked_score'], reverse=True)
    
    return scored_results
```

## 모니터링

### 검색 품질 메트릭

```python
import logging

logger = logging.getLogger()

def log_search_metrics(query, results):
    """Log search quality metrics."""
    
    metrics = {
        'query_length': len(query),
        'num_results': len(results),
        'avg_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'top_score': results[0]['score'] if results else 0
    }
    
    logger.info(f"RAG Search Metrics: {metrics}")
```

### CloudWatch Custom Metrics

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

def publish_rag_metrics(query, results):
    """Publish custom metrics to CloudWatch."""
    
    cloudwatch.put_metric_data(
        Namespace='EmergencyOrchestrator/RAG',
        MetricData=[
            {
                'MetricName': 'SearchLatency',
                'Value': search_time_ms,
                'Unit': 'Milliseconds'
            },
            {
                'MetricName': 'ResultCount',
                'Value': len(results),
                'Unit': 'Count'
            },
            {
                'MetricName': 'TopScore',
                'Value': results[0]['score'] if results else 0,
                'Unit': 'None'
            }
        ]
    )
```

## 문제 해결

### 메모리 부족

**증상**: Lambda OOM 에러

**해결**:
1. Lambda 메모리 증가 (최대 10GB)
2. 인덱스 크기 줄이기 (문서 필터링)
3. 압축된 인덱스 사용 (IVF, PQ)

### 느린 검색

**증상**: 검색 시간 > 5초

**해결**:
1. HNSW 인덱스 사용
2. top_k 줄이기
3. 인덱스 샤딩

### 낮은 검색 품질

**증상**: 관련 없는 결과 반환

**해결**:
1. 의료 특화 임베딩 모델 사용
2. 쿼리 전처리 개선
3. 재순위화 로직 추가
4. 더 많은 학습 데이터

## 업데이트

### 인덱스 재구축

새로운 데이터 추가 시:

```bash
# 1. 새로운 인덱스 빌드
python index_builder.py \
  --mimic-note-path /path/to/updated/data \
  --output-dir ./indices_v2

# 2. S3에 업로드 (버전 관리)
aws s3 cp ./indices_v2/faiss_index.bin \
  s3://$RAG_BUCKET/indices/v2/faiss_index.bin

# 3. Lambda 환경변수 업데이트
aws lambda update-function-configuration \
  --function-name emergency-report-generator \
  --environment Variables={RAG_INDEX_VERSION=v2}
```

### 점진적 업데이트

```python
# Load existing index
index = faiss.read_index('faiss_index.bin')

# Add new vectors
new_embeddings = encoder.encode(new_documents)
index.add(new_embeddings)

# Save updated index
faiss.write_index(index, 'faiss_index_updated.bin')
```

## 참고 자료

- FAISS Documentation: https://github.com/facebookresearch/faiss/wiki
- Sentence Transformers: https://www.sbert.net/
- MIMIC-IV: https://physionet.org/content/mimiciv/
- MIMIC-CXR: https://physionet.org/content/mimic-cxr/
