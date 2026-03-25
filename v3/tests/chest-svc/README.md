# chest-svc 테스트

## 폴더 구조

```
tests/chest-svc/
├── images/
│   ├── real/                    ← S3에서 받은 실제 MIMIC-CXR 흉부 X-Ray (5장)
│   │   ├── 096052b7.jpg
│   │   ├── 174413ec.jpg
│   │   ├── 2a2277a9.jpg
│   │   ├── 68b5c4b1.jpg
│   │   └── e084de3b.jpg
│   └── dummy/                   ← 테스트용 더미 이미지 (2장)
│       ├── sample_chest_xray.png
│       └── sample_cardiomegaly.png
├── web/
│   ├── index.html               ← 브라우저 테스트 UI
│   └── serve.py                 ← 테스트 웹 서버 (포트 3000)
├── test_chest_svc.py            ← CLI 통합 테스트 (6개 테스트)
└── README.md                    ← 이 파일
```

## 1. 웹 UI 테스트 (브라우저)

### 실행 방법

터미널 2개 필요:

```bash
# 터미널 1: chest-svc 서버
cd v3/services/chest-svc
PYTHONPATH="../../shared:$PYTHONPATH" uvicorn main:app --port 8001

# 터미널 2: 테스트 웹 서버
cd v3
source venv/bin/activate
python tests/chest-svc/web/serve.py
```

브라우저에서 http://localhost:3000 접속

### 기능
- 이미지 업로드 (드래그 앤 드롭 지원)
- 샘플 이미지 5종 클릭 로드
- 환자 정보 입력 (나이, 성별, 주소, 병력)
- 분석 결과: 14개 소견, AI 요약, 소견서, 파이프라인 타이밍
- 위험도 배지 (CRITICAL / HIGH / MODERATE / LOW)

## 2. CLI 테스트

```bash
cd v3
source venv/bin/activate

# 전체 테스트 (서버가 :8001에서 실행 중이어야 함)
python tests/chest-svc/test_chest_svc.py

# 특정 테스트만
python tests/chest-svc/test_chest_svc.py --test healthz
python tests/chest-svc/test_chest_svc.py --test predict
python tests/chest-svc/test_chest_svc.py --test cardiomegaly
```

### 테스트 목록
| # | 테스트 | 설명 |
|---|--------|------|
| 1 | healthz | Liveness 프로브 |
| 2 | readyz | Readiness 프로브 + 모델 로딩 확인 |
| 3 | predict | 정상 흉부 X-Ray (더미) |
| 4 | cardiomegaly | 심비대 시뮬레이션 (더미) |
| 5 | context | 이전 모달(ECG) 결과 포함 요청 |
| 6 | invalid | 에러 핸들링 (이미지 없는 요청) |

## 3. 테스트 데이터 출처

| 데이터 | 출처 | 비고 |
|--------|------|------|
| real/*.jpg | S3 `pre-project-practice-hyunwoo-.../test-images/` | MIMIC-CXR 데이터셋 |
| dummy/*.png | 코드 생성 | 320x320 합성 이미지 |
| ONNX 모델 | S3 `onnx_models/` → `v3/models/` | UNet + DenseNet + YOLO |
| RAG 인덱스 | S3 `rag/` → `v3/models/rag/` | FAISS + metadata |
