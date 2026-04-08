# ECG 모달 학습 설계 문서

## 1. 학습 파이프라인 전체 흐름

```
processed/manifest.csv + .npy 파일들
        ↓
ECGDataset (fold 기반 분할)
        ↓
모델 추론 (백본 + 인구통계 결합)
        ↓
긴급도 가중 BCE Loss
        ↓
best_model_s4.pt 저장
```

---

## 2. 데이터 분할

20-fold stratified cross-validation 기반.

```
Fold 0~15  (80%) → Train:  125,841건
Fold 16~17 (10%) → Val:     16,103건
Fold 18~19 (10%) → Test:    15,514건
```

---

## 3. 백본 비교: 1D-CNN vs S4

### 3-1. 1D-CNN (train_ecg.py)

```
입력: (batch, 12, 250)  ← 2.5초 chunk 4개로 분할 후 평균
구조:
  Conv1d(12→64, k=7) → BN → ReLU → MaxPool
  Conv1d(64→128, k=5) → BN → ReLU → MaxPool
  Conv1d(128→256, k=5) → BN → ReLU → MaxPool
  Conv1d(256→512, k=3) → BN → ReLU → AdaptiveAvgPool
  FC(512→512)
출력: 임베딩 (512)
```

특징:
- 로컬 패턴 감지 (커널 크기 내 패턴만)
- 빠른 학습
- 4개 chunk 예측 평균으로 전체 10초 커버

### 3-2. S4 (train_ecg_s4.py) — 현재 사용

```
입력: (batch, 12, 1000)  ← 전체 10초 입력
구조:
  CNN stem: 1000 → 125 다운샘플 (3단계)
    Conv1d(12→128, k=7, stride=2)
    Conv1d(128→256, k=5, stride=2)
    Conv1d(256→512, k=3, stride=2)
  S4 레이어 × 6: 125 타임스텝 장거리 의존성 포착
  AdaptiveAvgPool → 임베딩 (512)
출력: 임베딩 (512)
```

특징:
- 전체 시퀀스 장거리 의존성 포착
- HiPPO 행렬 초기화 (과거 기억 보존 최적화)
- 파라미터 수: 8,934,872

### 3-3. 비교

| 항목 | 1D-CNN | S4 |
|------|:------:|:--:|
| 입력 길이 | 250 (chunk) | 1000 (전체) |
| 장거리 의존성 | ❌ 로컬만 | ✅ 전체 시퀀스 |
| 학습 속도 | 빠름 | 느림 |
| 파라미터 | ~3M | ~9M |
| Epoch당 시간 | ~5분 | ~10~15분 |
| 수렴 에포크 | 20 | 30 |
| LR | 3e-5 | 1e-4 |
| Batch size | 32 | 64 |

---

## 4. 인구통계 결합

```
ECG 임베딩 (512) + 나이/성별 임베딩 (16) → concat (528) → 분류기 → 24개 예측

나이: (age - 18) / (101 - 18) → 0~1
성별: M=1.0, F=0.0, Unknown=0.5
```

---

## 5. Loss 함수

### 긴급도 가중 BCE

```python
loss = Σ weight[i] × BCE(pred[i], target[i])
```

30일 사망률 기반 3단계 가중치:

| Tier | 사망률 | 가중치 | 질환 예시 |
|------|--------|--------|---------|
| Tier 1 | ≥10% | 3.0 | cardiac_arrest(60.1%), sepsis(28.1%), respiratory_failure(27.5%) |
| Tier 2 | 5~10% | 2.0 | afib_flutter(8.8%), heart_failure(8.6%) |
| Tier 3 | 2~5% | 1.5 | hypertension(4.0%), dm2(4.7%), angina(2.7%) |

### S4 Loss (Focal 제거)

```python
class UrgencyWeightedBCELoss(nn.Module):
    def forward(self, logits, targets):
        bce = F.binary_cross_entropy_with_logits(logits, targets, reduction='none')
        weighted = bce * self.weights.unsqueeze(0)
        return weighted.mean()
```

1D-CNN 버전은 focal_gamma=2.0 포함, S4 버전은 제거 (수렴 안정성).

---

## 6. 옵티마이저 & 스케줄러

```python
optimizer = AdamW(lr=1e-4, weight_decay=1e-4)
scheduler = OneCycleLR(max_lr=1e-4, pct_start=0.1)  # 10% warmup + cosine
```

---

## 7. AUROC 0.000 문제 — 원인 및 해결

### 문제 현상

초기 학습 시 모든 라벨의 AUROC가 0.000으로 출력됨.

### 원인 분석

**원인 1: 단일 클래스 배치**
```
희귀 질환(cardiac_arrest 0.5%, calcium_disorder 1.1%)은
배치 내에 양성 샘플이 0개인 경우 발생
→ roc_auc_score가 ValueError 발생 → except로 0.0 반환
```

**원인 2: Focal Loss gamma 과도**
```
focal_gamma=2.0 적용 시 초기 학습에서
쉬운 샘플 가중치가 너무 낮아져 gradient 소실
→ 모델이 전부 0 예측 → AUROC 0.000
```

**원인 3: LR 너무 낮음**
```
LR=3e-5로 시작 시 초기 수렴이 너무 느려
첫 에포크에서 의미 있는 예측 불가
```

### 해결 방법

```python
# 1. try-except로 ValueError 처리 (라벨별 개별 처리)
for i, label in enumerate(TARGET_LABELS):
    try:
        results[f'auroc_{label}'] = roc_auc_score(all_targs[:, i], all_preds[:, i])
    except ValueError:
        results[f'auroc_{label}'] = 0.0  # 단일 클래스 배치 시 0으로 처리

# 2. S4에서 Focal Loss 제거
criterion = UrgencyWeightedBCELoss(URGENCY_WEIGHTS.to(DEVICE))
# focal_gamma 파라미터 제거

# 3. LR 상향 + OneCycleLR warmup
optimizer = AdamW(lr=1e-4)  # 3e-5 → 1e-4
scheduler = OneCycleLR(max_lr=1e-4, pct_start=0.1)
```

---

## 8. 학습 결과 (S4, 최종 30 에포크)

```
체크포인트 로드 (10 에포크 AUROC 0.803) → 20 에포크 추가 학습

Epoch 7/20:  Val AUROC 0.812 (Best)
Epoch 20/20: Val AUROC 0.808

=== Test Results ===
Macro AUROC:      0.817
T1 (놓치면 사망): 0.809
T2 (긴급):        0.848
T3 (중요):        0.732

질환별 AUROC:
afib_flutter         0.912  ✅
heart_failure        0.898  ✅
afib_detail          0.900  ✅
hf_detail            0.899  ✅
cardiac_arrest       0.895  ✅
sepsis               0.857  ✅
acute_mi             0.848  ✅
other_conduction     0.849  ✅
av_block_lbbb        0.903  ✅
chronic_kidney       0.842  ✅
hyperkalemia         0.831  ✅
respiratory_failure  0.833  ✅
chronic_ihd          0.827  ✅
paroxysmal_tachy     0.823  ✅
hypokalemia          0.802  ✅
acute_kidney_failure 0.794
angina               0.784
pericardial_disease  0.772
copd                 0.775
pulmonary_embolism   0.723  ⚠️
hypothyroidism       0.724  ⚠️
hypertension         0.722  ⚠️ ECG 특이 소견 적음
calcium_disorder     0.714  ⚠️
dm2                  0.691  ⚠️ ECG로 감지 어려움
```

---

## 9. 체크포인트 이어받기

세션 타임아웃으로 프로세스가 죽어도 이어서 학습 가능.

```python
checkpoint_path = os.path.join(OUTPUT_DIR, "best_model_s4.pt")
best_val_auroc = 0
if os.path.exists(checkpoint_path):
    model.load_state_dict(torch.load(checkpoint_path, map_location=DEVICE))
    best_val_auroc = 0.803  # 마지막 저장된 AUROC
    print(f"체크포인트 로드 완료 (AUROC: {best_val_auroc})")
```

---

## 10. 실행 명령

```python
import subprocess

# 설치
subprocess.run(['pip', 'install', 'einops', '-q'])

# 백그라운드 실행
proc = subprocess.Popen(
    ['python', 'train_ecg_s4.py',
     '--processed-dir', '/home/sagemaker-user/processed',
     '--output-dir', '/home/sagemaker-user',
     '--epochs', '20'],
    stdout=open('/home/sagemaker-user/train.log', 'w'),
    stderr=subprocess.STDOUT
)
print(f"PID: {proc.pid}")

# 로그 확인
with open('/home/sagemaker-user/train.log') as f:
    print(f.read())
```
