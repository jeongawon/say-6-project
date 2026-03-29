# Gap Analysis: v3-structure-cleanup

> 분석일: 2026-03-28
> Plan: `docs/01-plan/features/v3-structure-cleanup.plan.md`
> Match Rate: **100%** (23항목 중 23 Match)

---

## Executive Summary

| 항목 | 결과 |
|------|------|
| **전체 Match Rate** | 100% |
| **검증 항목 수** | 23 |
| **Gap 수** | 0 (1건 즉시 수정) |
| **판정** | **PASS** — 90% 기준 초과 |

---

## Phase별 상세 결과

### Phase 1: 파일 이동 — 100% ✅

| # | 항목 | 상태 | 검증 내용 |
|---|------|:----:|-----------|
| 1-1 | chest-svc static 이동 | ✅ Match | `tests/v3/chest-svc/static/` 존재, `v3/services/chest-svc/static/` 없음 |
| 1-2 | orchestrator static 이동 | ✅ Match | `tests/v3/central-orchestrator/static/` 존재, `v3/services/central-orchestrator/static/` 없음 |
| 1-3 | tests 이동 + 이미지 통합 | ✅ Match | `tests/v3/chest-svc/` 통합 완료, `v3/tests/` 없음 |
| 1-4 | threshold_optimization 이동 | ✅ Match | `analysis/threshold_optimization/` 존재, `v3/threshold_optimization/` 없음 |
| 1-5 | V3_MIGRATION_PLAN 이동 | ✅ Match | `docs/v3-migration/V3_MIGRATION_PLAN.md` 존재, `v3/V3_MIGRATION_PLAN.md` 없음 |

### Phase 2: CI/CD 위치 수정 — 100% ✅

| # | 항목 | 상태 | 검증 내용 |
|---|------|:----:|-----------|
| 2-1 | workflows 루트로 이동 | ✅ Match | `.github/workflows/` 에 6개 yml 파일 존재 |
| 2-2 | trigger paths 수정 | ✅ Match | 6개 파일 모두 `v3/services/{svc}/**` 경로 사용 |
| 2-3 | v3/.github/ 삭제 | ✅ Match | `v3/.github/` 존재하지 않음 |

### Phase 3: 정리 — 100% ✅

| # | 항목 | 상태 | 검증 내용 |
|---|------|:----:|-----------|
| 3-1 | v3/tests/ 삭제 | ✅ Match | 존재하지 않음 |
| 3-2 | v3/threshold_optimization/ 삭제 | ✅ Match | 존재하지 않음 |
| 3-3 | 중복 이미지 삭제 | ✅ Match | `tests/v3/chest-svc/images/real/` 존재하지 않음 |

### Phase 4: 코드 수정 — 100% ✅

| # | 항목 | 상태 | 검증 내용 |
|---|------|:----:|-----------|
| 4-1a | chest-svc GET / 조건부 | ✅ Match | `os.path.exists` 체크 + fallback HTML (131-141행) |
| 4-1b | chest-svc static mount 조건부 | ✅ Match | `os.path.isdir` + `follow_symlink=True` (250-251행) |
| 4-2a | orchestrator GET / 조건부 | ✅ Match | `os.path.exists` 체크 + fallback HTML (119-126행) |
| 4-2b | orchestrator /testdata 조건부 | ✅ Match | `os.path.isdir` 체크 (130-132행) |
| 4-2c | orchestrator /static mount | ✅ Match | 즉시 수정 완료 (134-136행) |
| 4-3 | docker-compose 볼륨 마운트 | ✅ Match | 두 서비스 모두 `../tests/v3/*/static:/app/static:ro` 설정 |

#### (수정 완료) Phase 4-2c — orchestrator /static mount

- **초기 Gap**: `/static` 전역 마운트 누락
- **수정**: `central-orchestrator/main.py` 134-136행에 조건부 마운트 추가
- **현재**: chest-svc와 동일한 패턴으로 일관성 확보 ✅

### Phase 5: thresholds.py 정리 — 100% ✅

| # | 항목 | 상태 | 검증 내용 |
|---|------|:----:|-----------|
| 5-1 | re-export 파일 삭제 | ✅ Match | `layer3_clinical_logic/thresholds.py` 존재하지 않음 |
| 5-2 | import 경로 수정 | ✅ Match | 18개 파일 `from thresholds import ...` 직접 사용 |
| 5-3 | import 동작 확인 | ✅ Match | WORKDIR=/app 환경에서 정상 import 가능 |

### Phase 6: .dockerignore — 100% ✅

| # | 항목 | 상태 | 검증 내용 |
|---|------|:----:|-----------|
| 6-1 | .dockerignore 생성 | ✅ Match | `v3/.dockerignore` 존재, 9개 엔트리 (`__pycache__`, `.pytest_cache`, `*.pyc`, `.env`, `.env.*`, `README.md`, `k8s/`, `.git`, `.gitignore`) |

### Phase 7: PROJECT_STRUCTURE.md — 100% ✅

| # | 항목 | 상태 | 검증 내용 |
|---|------|:----:|-----------|
| 7-1 | 문서 갱신 | ✅ Match | 루트 `PROJECT_STRUCTURE.md` 새 구조 반영 |
| 7-2 | 파일 통계 | ✅ Match | v3: 102파일, 외부: 30파일, 총: 132파일 |

---

## 잔여 파일 확인 (Clean Verification)

| 경로 | 상태 |
|------|------|
| `v3/services/chest-svc/static/` | ❌ 없음 (정상) |
| `v3/services/central-orchestrator/static/` | ❌ 없음 (정상) |
| `v3/tests/` | ❌ 없음 (정상) |
| `v3/threshold_optimization/` | ❌ 없음 (정상) |
| `v3/V3_MIGRATION_PLAN.md` | ❌ 없음 (정상) |
| `v3/.github/` | ❌ 없음 (정상) |
| `v3/services/chest-svc/layer3_clinical_logic/thresholds.py` | ❌ 없음 (정상) |
| `tests/v3/chest-svc/images/real/` | ❌ 없음 (정상) |
| `v3/PROJECT_STRUCTURE.md` | ❌ 없음 (정상, 루트로 이동) |

---

## 결론

**Match Rate 100%** — 초기 Gap 1건 즉시 수정 완료.
90% 기준 초과로 **PASS** 판정. Completion Report 진행 가능.
