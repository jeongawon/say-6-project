# Plan: v3 배포 전용 구조 정리

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | v3/ 안에 테스트 UI, 테스트 이미지, 분석 결과 등 비배포 파일이 혼재 — 컨테이너 이미지에 불필요한 파일 포함, `.github/workflows/`가 v3/ 안에 있어 GitHub Actions 미동작 |
| **Solution** | v3/에서 테스트 자산/분석 결과를 루트로 분리, 코드 조건부 서빙 수정, CI/CD 위치 수정, .dockerignore로 방어 |
| **Function UX Effect** | `v3/` = 배포 대상이라는 단순한 규칙, docker-compose 볼륨 마운트로 테스트 UI 자동 연결 |
| **Core Value** | 배포 경계 명확화 → 컨테이너 이미지 경량화 + CI/CD 정상 동작 + 단일 소스 테스트 자산 관리 |

---

## 1. 현재 문제 분석

### v3/ 내부의 비배포 파일 목록

| 파일/디렉토리 | 크기 | 문제 | 위험도 |
|---------------|------|------|--------|
| `services/chest-svc/static/` | ~1MB+ | 테스트 UI + 이미지 5장이 컨테이너에 포함 | **고** |
| `services/central-orchestrator/static/` | ~10KB | 통합 테스트 UI가 컨테이너에 포함 | 중 |
| `services/chest-svc/static/test-images/` (5장) | ~1MB | `tests/chest-svc/images/real/`과 동일 이미지 **중복** | 중 |
| `tests/chest-svc/` (18파일) | ~2MB+ | 테스트 코드/결과가 배포 디렉토리 안에 있음 | 중 |
| `threshold_optimization/` (3파일) | ~50KB | 분석 결과물이 배포 디렉토리 안에 있음 | 저 |
| `V3_MIGRATION_PLAN.md` | ~16KB | 계획 문서가 배포 디렉토리 안에 있음 | 저 |
| `.github/workflows/` (6파일) | ~28KB | **v3/ 안에 있어서 GitHub Actions가 인식 못함** | **고** |
| `layer3_clinical_logic/thresholds.py` | 0.2KB | sys.path.insert 해킹으로 상위 thresholds.py 재수출 | 중 |

### 컨테이너 이미지 오염

```
# chest-svc Dockerfile
COPY services/chest-svc/ /app/
  → /app/static/index.html        ← 테스트 UI (프로덕션 불필요)
  → /app/static/test-images/5장   ← 테스트 이미지 ~1MB (완전 불필요)
  → /app/.env                     ← 로컬 환경변수
  → /app/README.md                ← 문서 (경미, .dockerignore로 해결)
```

### CI/CD 미동작 (심각)

```
현재:  v3/.github/workflows/*.yml    ← GitHub가 인식 못함 (비활성)
필요:  .github/workflows/*.yml       ← 레포지토리 루트만 인식 (GitHub 플랫폼 요구사항)
```

---

## 2. 목표 구조

### 원칙
> **v3/ = 서비스 소스코드 + K8s 매니페스트 + docker-compose + 공유 스키마**
> **테스트 자산은 루트 tests/v3/ 에서 단일 관리**
> **README.md는 서비스 폴더에 유지 (.dockerignore로 이미지 제외)**
> **docker-compose.yml은 v3/ 안에 유지 (상대경로 깔끔)**

### After 구조

```
say-6-project/
│
├── .github/workflows/                  ← v3에서 수정: CI/CD (GitHub 요구사항)
│   ├── chest-svc.yml                     paths: 'v3/services/chest-svc/**'
│   ├── ecg-svc.yml
│   ├── blood-svc.yml
│   ├── orchestrator.yml
│   ├── rag-svc.yml
│   └── report-svc.yml
│
├── v3/                                 ← 배포 + 개발 환경
│   ├── services/
│   │   ├── chest-svc/                  (static/ 제거, README.md 유지)
│   │   │   ├── main.py                 ← 조건부 static 서빙
│   │   │   ├── config.py
│   │   │   ├── pipeline.py
│   │   │   ├── thresholds.py           (SSOT)
│   │   │   ├── .env                    (로컬 개발용, 유지)
│   │   │   ├── README.md               (유지 — 서비스 설명 문서)
│   │   │   ├── layer1_segmentation/
│   │   │   ├── layer2_detection/
│   │   │   ├── layer3_clinical_logic/  (thresholds.py 재수출 제거)
│   │   │   ├── report/
│   │   │   ├── Dockerfile
│   │   │   └── requirements.txt
│   │   ├── central-orchestrator/       (static/ 제거, README.md 유지)
│   │   ├── ecg-svc/
│   │   ├── blood-svc/
│   │   ├── rag-svc/
│   │   └── report-svc/
│   ├── shared/
│   ├── k8s/
│   ├── docker-compose.yml              ← 유지 + 테스트 static 볼륨 마운트 추가
│   └── .dockerignore                   ← NEW (README.md, .env 등 이미지 제외)
│
├── tests/                              ← 테스트 자산 통합
│   ├── e2e/                            (기존 v2 E2E)
│   └── v3/                             ← v3 테스트 전체
│       ├── chest-svc/
│       │   ├── static/                 ← 테스트 UI + 이미지 (단일 소스)
│       │   │   ├── index.html
│       │   │   └── test-images/        (5장 — 유일한 소스)
│       │   ├── test_chest_svc.py
│       │   ├── images/
│       │   │   └── dummy/
│       │   ├── results/
│       │   ├── *.json
│       │   ├── PIPELINE_STAGE_ANALYSIS.md
│       │   └── YOLO_DETECTION_REPORT.md
│       └── central-orchestrator/
│           └── static/
│               └── index.html
│
├── analysis/                           ← 분석/최적화 결과
│   └── threshold_optimization/
│
├── docs/
│   ├── 01-plan/features/
│   ├── 02-design/
│   ├── 03-analysis/
│   ├── 04-report/
│   └── v3-migration/
│       └── V3_MIGRATION_PLAN.md
│
└── PROJECT_STRUCTURE.md
```

---

## 3. 작업 항목

### Phase 1: 파일 이동

| # | 작업 | From | To |
|---|------|------|----|
| 1-1 | chest-svc 테스트 UI 이동 | `v3/services/chest-svc/static/` | `tests/v3/chest-svc/static/` |
| 1-2 | orchestrator 테스트 UI 이동 | `v3/services/central-orchestrator/static/` | `tests/v3/central-orchestrator/static/` |
| 1-3 | 테스트 코드/결과 이동 | `v3/tests/chest-svc/` | `tests/v3/chest-svc/` (1-1과 합침) |
| 1-4 | 분석 결과 이동 | `v3/threshold_optimization/` | `analysis/threshold_optimization/` |
| 1-5 | 마이그레이션 문서 이동 | `v3/V3_MIGRATION_PLAN.md` | `docs/v3-migration/V3_MIGRATION_PLAN.md` |

**테스트 이미지 중복 해소 (1-1 + 1-3 합치면서):**
```
tests/v3/chest-svc/
├── static/                         ← from v3/services/chest-svc/static/
│   ├── index.html
│   └── test-images/                (5장 — 유일한 소스)
├── images/
│   └── dummy/                      ← from v3/tests/chest-svc/images/dummy/
│   (real/ 삭제 — static/test-images/가 단일 소스)
├── test_chest_svc.py
├── results/
└── *.json, *.md
```

### Phase 2: CI/CD 위치 수정 (GitHub Actions 정상화)

| # | 작업 | 설명 |
|---|------|------|
| 2-1 | workflows 루트로 이동 | `v3/.github/workflows/` → `.github/workflows/` |
| 2-2 | trigger paths 수정 | `services/chest-svc/**` → `v3/services/chest-svc/**` |
| 2-3 | v3/.github/ 삭제 | 이동 완료 후 빈 디렉토리 삭제 |

> 이건 "구조 정리"가 아니라 **"잘못 놓인 CI/CD 설정 수정"**입니다.
> GitHub Actions는 레포지토리 루트의 `.github/workflows/`만 인식합니다.

### Phase 3: 빈 디렉토리/중복 파일 제거

| # | 작업 | 대상 | 이유 |
|---|------|------|------|
| 3-1 | v3/tests/ 삭제 | `v3/tests/` | Phase 1-3에서 이동 완료 |
| 3-2 | v3/threshold_optimization/ 삭제 | `v3/threshold_optimization/` | Phase 1-4에서 이동 완료 |
| 3-3 | 중복 이미지 삭제 | `tests/v3/chest-svc/images/real/` | static/test-images/가 단일 소스 |

### Phase 4: 코드 수정 (조건부 static 서빙)

#### 4-1. chest-svc/main.py 수정

**현재:**
```python
# 128행 — 무조건 static/index.html 읽기 (없으면 FileNotFoundError)
@app.get("/", response_class=HTMLResponse)
def test_ui():
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path) as f:
        return f.read()

# 241행 — 무조건 static 마운트 (디렉토리 없으면 시작 시 에러)
app.mount("/static", StaticFiles(directory=...), name="static")
```

**변경 후:**
```python
_static_dir = os.path.join(os.path.dirname(__file__), "static")

@app.get("/", response_class=HTMLResponse)
def test_ui():
    """GET / → 테스트 UI (static/ 있으면) 또는 API 상태 페이지"""
    html_path = os.path.join(_static_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            return f.read()
    return "<h1>chest-svc</h1><p>API running. Test UI available via docker-compose.</p>"

# 마지막 줄 — 조건부 마운트
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir, follow_symlink=True), name="static")
```

#### 4-2. central-orchestrator/main.py 수정

동일 패턴 적용. `GET /` 조건부 서빙. `/testdata` 마운트는 이미 조건부(`os.path.isdir` 체크).

#### 4-3. docker-compose.yml 수정 — 테스트 static 볼륨 마운트 추가

docker-compose.yml은 v3/ 안에 유지하므로 기존 경로는 그대로. 테스트 볼륨만 추가:

```yaml
chest-svc:
  build: ./services/chest-svc
  volumes:
    - ./models:/models:ro
    - ../tests/v3/chest-svc/static:/app/static:ro        # ← NEW

central-orchestrator:
  build: ./services/central-orchestrator
  volumes:
    - ../tests/v3/central-orchestrator/static:/app/static:ro  # ← NEW
```

**환경별 동작:**
| 환경 | 실행 위치 | 테스트 UI | 설명 |
|------|-----------|-----------|------|
| `docker-compose up` | `v3/` | 볼륨 마운트로 자동 연결 | `../tests/v3/` 참조 |
| `uvicorn` 로컬 | `v3/services/chest-svc/` | "API running" 표시 | static/ 없으므로 조건부 분기 |
| K8s 배포 | 클러스터 | "API running" 표시 | static 볼륨 없음 |

### Phase 5: thresholds.py 정리

| # | 작업 | 설명 |
|---|------|------|
| 5-1 | re-export 해킹 제거 | `layer3_clinical_logic/thresholds.py`의 sys.path.insert 삭제 |
| 5-2 | import 경로 확인/수정 | layer3 내부 코드에서 thresholds import 경로 확인 |
| 5-3 | 동작 확인 | Python import 테스트 |

**상세:**
- 현재: `layer3_clinical_logic/thresholds.py`가 `sys.path.insert(0, ...)` + `from thresholds import *` 해킹
- 변경: 파일 삭제, layer3 코드에서 `from thresholds import ...` 직접 사용
- 컨테이너 WORKDIR=/app, uvicorn도 chest-svc/ 에서 실행 → 상위 thresholds.py 직접 import 가능

### Phase 6: .dockerignore 생성

```dockerignore
# v3/.dockerignore — 컨테이너 이미지에서 제외할 파일
**/__pycache__
**/.pytest_cache
**/.env
**/README.md
```

> README.md는 서비스 폴더에 유지하되 .dockerignore로 이미지에서 제외.
> 개발자가 서비스 폴더에 들어가면 README가 보이고, 컨테이너에는 안 들어감.

### Phase 7: PROJECT_STRUCTURE.md 갱신

| # | 작업 | 설명 |
|---|------|------|
| 7-1 | 문서 갱신 | 새 구조 반영, auth-svc/patient-svc 미구현 섹션 제거 |
| 7-2 | 파일 통계 재집계 | v3 내부/외부 파일 수 재계산 |

---

## 4. 작업 순서 및 의존성

```
Phase 1 (파일 이동)                 ← 모두 병렬 가능
  ├── 1-1 chest-svc static 이동
  ├── 1-2 orchestrator static 이동
  ├── 1-3 tests 이동 + 이미지 통합
  ├── 1-4 threshold_optimization 이동
  └── 1-5 V3_MIGRATION_PLAN 이동
         │
         ▼
Phase 2 (CI/CD 수정)               ← Phase 1과 독립, 병렬 가능
  ├── 2-1 workflows 루트로 이동
  ├── 2-2 trigger paths 수정
  └── 2-3 v3/.github/ 삭제
         │
         ▼
Phase 3 (제거)                     ← Phase 1 완료 후
  ├── 3-1 v3/tests/ 삭제
  ├── 3-2 v3/threshold_optimization/ 삭제
  └── 3-3 중복 이미지 삭제
         │
         ▼
Phase 4 (코드 수정)                ← Phase 1 완료 후 (Phase 3과 병렬 가능)
  ├── 4-1 chest-svc/main.py 조건부 static
  ├── 4-2 orchestrator/main.py 조건부 static
  └── 4-3 docker-compose.yml 볼륨 추가
         │
         ▼
Phase 5 (thresholds 정리)          ← 독립, 언제든 가능
  ├── 5-1 re-export 파일 삭제
  ├── 5-2 import 경로 수정
  └── 5-3 동작 확인
         │
         ▼
Phase 6 (.dockerignore)            ← Phase 3 이후
         │
         ▼
Phase 7 (문서 갱신)                ← 모든 Phase 완료 후
```

---

## 5. 영향 범위

### 코드 변경 대상

| 파일 | 변경 내용 | 줄 수 |
|------|-----------|:-----:|
| `v3/services/chest-svc/main.py` | 조건부 static 서빙 (128행, 241행) | ~10줄 |
| `v3/services/central-orchestrator/main.py` | 조건부 static 서빙 (114행) | ~8줄 |
| `v3/docker-compose.yml` | chest-svc, orchestrator에 static 볼륨 추가 | ~4줄 |
| `.github/workflows/*.yml` (6개) | trigger paths `v3/` prefix 추가 | 각 ~2줄 |

### 변경 없음 (건드리지 않는 것)
- **README.md** — 서비스 폴더에 유지 (.dockerignore로 이미지 제외)
- **docker-compose.yml 위치** — v3/ 안에 유지 (상대경로 깔끔)
- 서비스 소스코드 (main.py static 부분 외)
- K8s 매니페스트
- shared/schemas.py
- .env 파일

---

## 6. 지금 vs 나중에

| 개선점 | 지금? | 이유 |
|--------|:-----:|------|
| static 폴더 이동 + 코드 수정 (Phase 1, 4) | **지금** | 핵심 목표, 컨테이너 경량화 |
| CI/CD 위치 수정 (Phase 2) | **지금** | 현재 GitHub Actions 미동작 상태 |
| 테스트/분석 이동 (Phase 1-3,4,5) | **지금** | 핵심 목표 |
| thresholds.py 해킹 제거 (Phase 5) | **지금** | 잠재적 버그 원인 |
| .dockerignore (Phase 6) | **지금** | 방어적 보호 |
| PROJECT_STRUCTURE.md 갱신 (Phase 7) | **지금** | 작업 후 반영 |
| K8s 서비스별 폴더 분리 | 나중에 | 현재 잘 동작 |
| 다른 서비스 스모크 테스트 추가 | 나중에 | 팀원 작업 의존 |

---

## 7. 리스크

| 리스크 | 가능성 | 완화 |
|--------|--------|------|
| docker-compose `../tests/v3/` 상대경로 오류 | 중 | docker-compose up 후 테스트 UI 접근 확인 |
| thresholds import 깨짐 | 중 | Phase 5-3에서 Python import 테스트 |
| CI/CD trigger paths 오타 | 저 | yml 수정 후 push 전 문법 확인 |
| 테스트 이미지 경로 하드코딩 | 저 | test_chest_svc.py 내 경로 확인 후 수정 |
| git mv 히스토리 추적 | 저 | git mv 사용 |
