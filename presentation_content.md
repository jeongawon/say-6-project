# Dr. AI Radiologist — 멀티모달 임상 의사결정 지원 시스템

> 팀: 원정아, 박현우, 홍경태, 양정인, 이정인 (5인)

---

## 1. 프로젝트 개요

### 1.1 문제 정의
- 응급실 의사의 진단 의사결정 시간 **40% 단축** 목표
- 단일 검사(ECG, X-ray, 혈액)만으로는 놓치는 질환이 존재
- **멀티모달 AI**가 3가지 검사를 교차 분석하여 종합 판단

### 1.2 시스템 구성 (3개 모달)

| 모달 | 입력 | 모델 | 출력 |
|------|------|------|------|
| **ECG 모달** | 12-lead ECG 파형 | S6 Mamba (ONNX) | 24개 질환 확률 + ECG Vitals |
| **흉부 X-ray 모달** | Chest X-ray 이미지 | UNet + DenseNet-121 (ONNX) | 6개 흉부 질환 + MIMIC-CXR 리포트 |
| **혈액검사 모달** | 10개 핵심 수치 | XGBoost+LightGBM+CatBoost 앙상블 | 8개 진단 그룹 |

### 1.3 핵심 차별점
- AWS Bedrock Agent(Claude)가 **중앙 오케스트레이터**로 모달 간 라우팅
- 사망률 기반 **긴급도 가중치** 적용 (Tier 1: 사망률 ≥10% → weight 3.0)
- 각 모달이 **독립 마이크로서비스**로 운영 → 확장성·독립 배포 가능

---

## 2. 인프라 아키텍처

### 2.1 전체 시스템 흐름

```
[환자 정보 입력]
       ↓
┌─────────────────────────────────┐
│   AWS Bedrock Agent (Claude)    │
│   중앙 오케스트레이터            │
│   - 증상 분석 → 모달 호출 순서 결정│
│   - 교차 분석 → 추가 모달 요청    │
│   - 최종 종합 리포트 생성         │
└──────┬──────┬──────┬────────────┘
       │      │      │
  ┌────▼──┐┌──▼───┐┌─▼─────┐
  │ECG-svc││CXR-svc││Blood-svc│
  │:8000  ││:8000  ││:8000   │
  └───────┘└───────┘└────────┘
       │      │      │
  ┌────▼──────▼──────▼────────┐
  │   Aurora Serverless v2     │
  │   (PostgreSQL) + DynamoDB  │
  └───────────────────────────┘
```

### 2.2 배포 옵션 비교

| 옵션 | 월 비용 | 추론 지연 | GPU | 적합 단계 |
|------|---------|----------|-----|----------|
| **Lambda + API GW** | ~$19 | 3-5초 | X | 데모/PoC |
| **SageMaker Endpoint** | $130-380 | ~0.5초 | O (g4dn.xlarge) | PoC+GPU |
| **EKS (Kubernetes)** | ~$856 | ~0.5초 | O | 프로덕션 |

### 2.3 현재 배포 환경
- **EC2** t3.large (i-008fbaebbadbc0dee)
- Docker 컨테이너 → AWS ECR (ap-northeast-2)
- S3 버킷: `say2-6team` (모델 + ECG 데이터 저장)
- Kubernetes manifest 준비 완료 (k8s/deployment.yaml, ingress.yaml)

### 2.4 DB 설계

| DB | 용도 | 비용 |
|----|------|------|
| **Aurora Serverless v2** (PostgreSQL) | patients 테이블 (환자 정보) | ~$5/월 |
| **DynamoDB** | modal_results 테이블 (모달별 결과, PK: patient_id, SK: modal#timestamp) | ~$1/월 |

---

## 3. ECG 모달 (심전도 분석)

### 3.1 데이터셋

| 항목 | 내용 |
|------|------|
| 데이터 소스 | MIMIC-IV ECG (800,035건) |
| 필터링 | ED 첫 번째 ECG만 (ecg_no_within_stay == 0) |
| 최종 데이터 | **158,440건**, 83,740명 |
| 포맷 | 12-lead × 10초 × 500Hz |
| 교차검증 | 20-fold stratified (0-15 train, 16-17 val, 18-19 test) |

### 3.2 24개 타겟 질환

**Tier 1 — ECG 직접 검출 가능 (14개 심혈관 질환)**

| 질환 | 유병률 | 30일 사망률 | 가중치 |
|------|--------|-----------|--------|
| 심정지 (Cardiac arrest) | 1.2% | **60.1%** | 3.0 |
| 패혈증 (Sepsis) | 2.6% | **28.1%** | 3.0 |
| 호흡 부전 (Respiratory failure) | 4.7% | **27.5%** | 3.0 |
| 급성 심근경색 (Acute MI) | 3.3% | **12.7%** | 3.0 |
| 심방세동 (Afib/flutter) | 14.4% | 8.8% | 2.0 |
| 심부전 (Heart failure) | 14.7% | 8.6% | 2.0 |
| 고혈압 (Hypertension) | 35.0% | 4.0% | 1.5 |

**Tier 2 — ECG 간접 검출 (10개 비심혈관 질환)**
- 만성 신부전 (14%), 당뇨병 (13.6%), 급성 신부전 (12.2%), 갑상선 기능 저하 (8.6%), COPD (7.9%)
- 고칼륨혈증 (3.7%), 저칼륨혈증 (2.7%), 칼슘 장애 (1.1%)

> **핵심 인사이트:** 비심혈관 질환(패혈증 28.1%, 호흡부전 27.5%)이 전통적 심장질환(심방세동 8.8%)보다 30일 사망률이 훨씬 높음 → ECG 기반 조기 감지의 임상적 가치

### 3.3 모델 아키텍처 — S6 Mamba

```
Raw ECG (12, 5000)
    ↓ 전처리: NaN보간 → ±3mV클리핑 → 100Hz리샘플링 → PTB-XL정규화
    ↓
ECG Signal (12, 1000)
    ↓
┌─────────────────────────┐
│ CNN Stem                │
│ Conv1d(12→128, k=7, s=2)  │  1000 → 500
│ Conv1d(128→256, k=5, s=2) │   500 → 250
│ Conv1d(256→512, k=3, s=2) │   250 → 125
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│ 6× MambaBlock (S6)      │
│ d_model=512, d_state=64 │  입력 의존적 선택 스캔
│ ~9M 파라미터             │
└────────────┬────────────┘
             ↓
    ECG Embedding (512)
        ⊕                    ← Demographics FC(2→32): age + sex
    Fusion (544)
        ↓
    LayerNorm → FC(544→128) → GELU → FC(128→24) → Sigmoid
        ↓
    24개 질환 확률
```

**S4 vs S6 선택 근거:**
- S4: 고정 상태 파라미터 → 모든 시점을 동일하게 처리
- **S6 (채택):** 입력 의존적 선택 파라미터 → 중요한 시점(QRS, ST변화)에 집중, 노이즈 무시

### 3.4 학습 설정

| 항목 | 값 |
|------|-----|
| Loss | Urgency-Weighted BCE (Tier별 3.0/2.0/1.5) |
| Optimizer | AdamW (lr=1e-4, wd=1e-4) |
| Scheduler | OneCycleLR (10% warmup, cosine) |
| Batch size | 64 |
| Epochs | 20 |
| Gradient clipping | max_norm=1.0 |

### 3.5 성능 결과

**AUROC (검증 셋)**

| 지표 | 점수 |
|------|------|
| **Macro AUROC** | **0.814** |
| Tier 1 (치명적) | 0.809 |
| Tier 2 (긴급) | 0.844 |
| Tier 3 (주의) | 0.721 |

**질환별 Top 5 AUROC:**
- 심방세동: 0.903
- AV 차단/LBBB: 0.898
- 심부전: 0.897
- 패혈증: 0.869
- 급성 심근경색: 0.846

**벤치마크 (108건 Golden Dataset)**

| 지표 | PPV | Recall | F1 |
|------|-----|--------|-----|
| Tier 1 | 60.9% | 29.2% | 39.4% |
| Tier 2 | 62.1% | 38.3% | 47.4% |
| Tier 3 | 52.5% | 42.1% | 46.7% |
| **전체** | **58.7%** | **37.8%** | **46.0%** |

### 3.6 분류 임계값 전략

| Tier | 임계값 | 설계 근거 |
|------|--------|----------|
| Tier 1 (사망률 ≥10%) | **0.30** | 치명적 질환 놓치지 않기 (높은 recall) |
| Tier 2 (사망률 5-10%) | **0.40** | 균형 잡힌 감지 |
| Tier 3 (사망률 2-5%) | **0.45** | 불필요한 경보 최소화 |

> PR-curve 최적화 임계값(0.001-0.06) 사용 시 2-3% 신뢰도 알림 → 과도한 false positive 발생 → 임상적으로 의미있는 고정값으로 전환

### 3.7 ECG Vitals 측정
- **방법:** Pan-Tompkins 간소화 R-peak 검출 (Lead II 기준)
- **측정값:** 심박수(HR), 서맥(HR<50), 빈맥(HR>100), 부정맥(RR CV>0.15)
- **보정 로직:** Afib 검출 시 irregular_rhythm 강제 true

### 3.8 서비스 아키텍처 (3-Layer Pipeline)

```
POST /predict
    ↓
Layer 1: ECGPreprocessor
  - S3/로컬에서 WFDB 로딩
  - 전처리 + ECG Vitals 측정
    ↓
Layer 2: ECGInferenceEngine
  - ONNX Runtime (ecg_s6.onnx)
  - S3 모델 자동 다운로드 + 캐싱
    ↓
Layer 3: ClinicalEngine
  - Tier 기반 임계값 적용
  - 중증도/권고사항 매핑
  - risk_level 계산 (critical/urgent/routine)
  - Afib→부정맥 보정
    ↓
Response: findings + all_probs + ecg_vitals + risk_level
```

---

## 4. 흉부 X-ray 모달 (CXR 분석)

### 4.1 검출 대상 (6개 흉부 질환)

| 질환 | DenseNet Index | 임계값 | 교차검증 방법 |
|------|---------------|--------|-------------|
| 심비대 (Cardiomegaly) | 1 | 0.55 | CTR (심흉비) |
| 흉수 (Pleural Effusion) | 9 | 0.45 | CP각 측정 |
| 폐부종 (Edema) | 3 | 0.35 | DenseNet + 심비대 동시 발생 |
| 기흉 (Pneumothorax) | 12 | 0.50 | 폐 면적 비대칭 |
| 무기폐 (Atelectasis) | 0 | 0.50 | 용적 감소 + 기관 편위 |
| 심장종격동 비대 | 4 | 0.45 | 종격동 너비 |

### 4.2 3-Stage 처리 파이프라인

```
Chest X-ray 이미지
    ↓
Stage 1: UNet Segmentation (~85MB)
  - 320×320 입력 → 5-class 분할 (배경, 좌폐, 우폐, 심장, 종격동)
  - 해부학적 측정: CTR, CP각, 폐면적비, 기관편위, 종격동 너비
  - PA/AP/측면 판별 (측면 자동 거부)
  - SVG 오버레이 좌표 생성
    ↓
Stage 2: DenseNet-121 Classification (~28MB)
  - 224×224 ImageNet 정규화
  - CheXpert 14-label 확률 → 6개 활성 질환 필터링
    ↓
Stage 3: Clinical Logic Engine
  - DenseNet 확률 × UNet 해부학적 증거 교차검증 (False Positive 감소)
  - 중증도 등급화 + 위험도 분류 (ROUTINE/URGENT/CRITICAL)
  - MIMIC-CXR 스타일 FINDINGS + IMPRESSION 리포트 생성
  - RAG query hints 생성
    ↓
Response: findings + measurements + risk_level + 서술형 리포트
```

### 4.3 핵심 설계 — 교차검증 패턴
- 모든 질환에 대해 **DenseNet 확률 + UNet 해부학적 증거** 이중 검증
- 예: 심비대 → DenseNet 확률 0.55 이상 **AND** CTR 0.50 이상 → 검출
- False Positive를 구조적으로 줄이는 설계

### 4.4 성능 벤치마크

| 지표 | 점수 |
|------|------|
| Expert 데이터셋 (2,411건) 전체 민감도 | 86.7% |
| 심비대 민감도 | 93.6% |
| 심비대 특이도 | 82.9% |
| MIMIC 검증 (102건) 전체 정확도 | 65.4% |
| MIMIC 심비대 양성예측도 | 96.6% |

### 4.5 프론트엔드 (CXR 모달)
- **Figma 디자인** → React 18 + TypeScript + shadcn/ui
- **인터랙티브 시각화:** X-ray 위에 측정선(CTR, CP각 등) SVG 오버레이 토글
- **차트:** Recharts 기반 데이터 시각화

---

## 5. 혈액검사 모달

### 5.1 8개 진단 그룹

| 그룹 | AUROC | 설명 |
|------|-------|------|
| 패혈증 (Sepsis) | 0.764 | WBC, 혈소판 이상 |
| 심혈관 (Cardio) | 0.645 | troponin/BNP 미포함 한계 |
| 신장 (Kidney) | 0.826 | creatinine, BUN 기반 |
| 췌장염 (Pancreatitis) | **0.880** | 특이적 패턴 |
| 항암 (Chemo) | 0.703 | 혈구 수치 변화 |
| 뇌졸중 (Stroke) | 0.756 | 응고·전해질 |
| 호흡기 (Respiratory) | 0.715 | 가스 교환 지표 |
| 소화기 출혈 (GI Bleeding) | 0.812 | 빈혈·응고 |

### 5.2 모델 및 데이터

| 항목 | 내용 |
|------|------|
| 모델 | XGBoost + LightGBM + CatBoost (Soft Voting) |
| 데이터 | MIMIC-IV 33,896 환자 (입원 전 Lab 값) |
| 핵심 피처 (10개) | WBC, hemoglobin, platelet, creatinine, BUN, Na, K, glucose, AST, albumin |
| 불균형 처리 | SMOTE |
| 후처리 | MIMIC-IV 임상 기준치 기반 abnormal_flags |

---

## 6. 멀티모달 연동 — Bedrock Agent 오케스트레이션

### 6.1 라우팅 로직

```
환자: 72세 여성, 주소: 흉통 + 호흡곤란

Bedrock Agent 판단:
  1️⃣ ECG 모달 호출 → 심방세동 87%, 심부전 45% 검출
  2️⃣ all_probs 분석 → dm2=0.11 (임계값 이하지만 65세+고혈압)
      → 혈액검사 모달 추가 호출 (HbA1c 확인)
  3️⃣ 심부전 검출 → CXR 모달 호출 (폐부종 확인)
  4️⃣ 3개 모달 결과 종합 → 최종 리포트 생성
```

### 6.2 모달 간 교차 진단 매핑

| ECG 검출 질환 | 다음 모달 | 확인 항목 |
|--------------|----------|----------|
| 급성 심근경색 | 혈액 | Troponin 확인 |
| 심부전 | 혈액 + CXR | BNP + 폐부종 |
| 심방세동 | 혈액 | 전해질 이상 |
| 폐색전증 (간접) | CXR | CTPA 영상 |
| 고칼륨혈증 (간접) | 혈액 | K+ 직접 측정 |
| 당뇨·COPD (무신호) | 혈액 | Lab/영상 위임 |

### 6.3 all_probs의 역할
- ECG 모달이 **임계값 이상 findings** 외에 **24개 전체 확률(all_probs)**도 반환
- Bedrock Agent가 임계값 이하 질환도 분석하여 추가 모달 호출 판단
- 예: dm2 확률 0.11 (임계값 0.45 미달) + 고령 + 고혈압 → 혈액검사 권고

---

## 7. 기술 스택 요약

| 계층 | 기술 |
|------|------|
| **오케스트레이터** | AWS Bedrock Agent (Claude) |
| **ECG 서비스** | FastAPI + ONNX Runtime + wfdb + boto3 |
| **CXR 서비스** | FastAPI + ONNX Runtime (UNet + DenseNet-121) |
| **혈액 서비스** | FastAPI + XGBoost/LightGBM/CatBoost |
| **모델 포맷** | 모두 ONNX (PyTorch 런타임 불필요, CPU 추론) |
| **컨테이너** | Docker (python:3.11-slim) |
| **오케스트레이션** | Kubernetes (EKS 준비) |
| **저장소** | S3 (모델+데이터), Aurora Serverless v2, DynamoDB |
| **CI/CD** | ECR + deploy.sh |
| **프론트엔드** | React 18 + TypeScript + shadcn/ui (CXR) / Streamlit (ECG 데모) |

---

## 8. 서비스별 API 설계 비교

### 공통 패턴
- 모든 모달: `POST /predict` (분석), `GET /health` (liveness), `GET /ready` (readiness)
- 응답: `{ status, modal, findings[], summary, risk_level, metadata }`
- Kubernetes 프로브 호환 설계

### ECG 고유
```json
{
  "ecg_vitals": { "heart_rate": 90.6, "bradycardia": false, "tachycardia": false, "irregular_rhythm": true },
  "all_probs": { "afib_flutter": 0.87, "heart_failure": 0.45, ... }
}
```

### CXR 고유
```json
{
  "measurements": { "ctr": 0.58, "ctr_line_coords": {...}, "cp_angle_left": 25.3, ... },
  "findings_text": "FINDINGS: The cardiac silhouette is enlarged...",
  "impression": "1. Cardiomegaly with CTR of 0.58...",
  "mask_base64": "...",
  "rag_query_hints": ["cardiomegaly management", ...]
}
```

---

## 9. 향후 계획 (Phase별 로드맵)

| Phase | 내용 | 인프라 | 비용 |
|-------|------|--------|------|
| Phase 1 | 로컬 모델 학습 + 검증 | 로컬 | - |
| Phase 2 | Lambda 기반 데모 배포 | Lambda + API GW | ~$19/월 |
| Phase 3 | SageMaker GPU 추론 PoC | SageMaker (g4dn) | ~$130-380/월 |
| Phase 4 | EKS 프로덕션 멀티모달 통합 | EKS + ALB | ~$856/월 |

---

## 10. 발표 포인트 요약

### 기술적 차별화
1. **3개 독립 마이크로서비스** → Bedrock Agent가 증상 기반 지능형 라우팅
2. **교차검증 패턴** — CXR: DenseNet×UNet 이중검증 / ECG: 모델 확률×ECG Vitals 보정
3. **사망률 가중 학습** — 치명적 질환(심정지 60.1%) 놓치지 않도록 loss 가중치 3.0배
4. **all_probs 라우팅** — 임계값 이하 질환도 Bedrock Agent가 맥락 분석하여 추가 검사 권고
5. **ONNX 경량화** — PyTorch 런타임 없이 CPU만으로 추론 가능

### 임상적 가치
1. ECG에서 비심혈관 고위험 질환(패혈증, 호흡부전) 조기 감지
2. 단일 검사 한계를 멀티모달 교차 분석으로 보완
3. MIMIC-CXR 스타일 서술형 리포트로 의사 의사결정 지원
4. 위험도 3단계 분류 (Critical/Urgent/Routine)로 우선순위화

### 비용 효율
- 데모/PoC 단계: 월 $19-25 (Lambda + Aurora + DynamoDB)
- GPU 추론 필요 시: 월 $130-380 (SageMaker)
- 모든 모델 ONNX 포맷 → CPU 추론으로도 0.5-3초 내 응답
