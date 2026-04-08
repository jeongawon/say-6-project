# 긴급도 기반 가중 Loss 설계 (30일 사망률 기반)

> ECG-MIMIC 논문 대비 차별화 포인트
> 목적: 응급실에서 "놓치면 안 되는 질환"의 recall을 우선 확보
> 근거: MIMIC-IV 응급실 첫 ECG 158,440건의 실제 30일 사망률 데이터

## 핵심 아이디어

논문은 모든 라벨의 loss를 동등하게 취급합니다.
하지만 응급실에서는 심정지를 놓치는 것과 고혈압을 놓치는 것의 임상적 결과가 완전히 다릅니다.

```
기존: L = BCE(pred, target)  ← 모든 라벨 동일 가중치
제안: L = Σ (urgency_weight[i] × BCE(pred[i], target[i]))
```

가중치는 임의 설정이 아닌, 실제 데이터의 30일 사망률에서 도출합니다.

---

## 30일 사망률 분석 결과

데이터: 응급실 첫 ECG 158,440건, 30일 내 사망 5,961건 (전체 3.8%)

---

## 긴급도 등급 체계 (데이터 기반)

### Tier 1: 즉시 조치 (weight = 3.0) — 30일 사망률 ≥ 10%

| 코드 | 질환 | 건수 | 30일 사망 | 사망률 |
|------|------|------|----------|--------|
| I46 | 심정지 | 817 | 489 | 60.1% |
| R65 | 패혈증/패혈성 쇼크 | 4,167 | 1,171 | 28.1% |
| J96 | 호흡부전 | 7,408 | 2,040 | 27.5% |
| I21 | 급성 심근경색 | 5,239 | 664 | 12.7% |
| E875 | 고칼륨혈증 | 5,902 | 744 | 12.6% |
| N17 | 급성 신부전 | 19,376 | 2,437 | 12.6% |
| E835 | 칼슘 대사 이상 | 1,741 | 211 | 12.1% |
| I26 | 폐색전증 | 2,011 | 236 | 11.7% |
| I47 | 발작성 빈맥 (VT/SVT) | 3,054 | 355 | 11.6% |
| I31 | 심낭질환 | 1,224 | 130 | 10.6% |

### Tier 2: 긴급 (weight = 2.0) — 30일 사망률 5~10%

| 코드 | 질환 | 건수 | 30일 사망 | 사망률 |
|------|------|------|----------|--------|
| I4891 | 심방세동 (세부) | 17,530 | 1,611 | 9.2% |
| I509 | 심부전 (세부) | 12,371 | 1,099 | 8.9% |
| I48 | 심방세동/조동 | 22,826 | 2,015 | 8.8% |
| I50 | 심부전 | 23,344 | 2,015 | 8.6% |
| J44 | COPD | 12,503 | 998 | 8.0% |
| E876 | 저칼륨혈증 | 4,335 | 337 | 7.8% |
| N18 | 만성 신장질환 | 22,122 | 1,687 | 7.6% |
| I44 | 방실차단/좌각차단 | 2,690 | 176 | 6.5% |
| I25 | 만성 허혈성 심질환 | 28,709 | 1,830 | 6.4% |
| E039 | 갑상선기능저하증 | 13,567 | 855 | 6.3% |
| I45 | 기타 전도장애 | 1,854 | 111 | 6.0% |

### Tier 3: 중요 (weight = 1.5) — 30일 사망률 2~5%

| 코드 | 질환 | 건수 | 30일 사망 | 사망률 |
|------|------|------|----------|--------|
| E119 | 제2형 당뇨병 | 21,581 | 1,011 | 4.7% |
| I10 | 본태성 고혈압 | 55,498 | 2,230 | 4.0% |
| I20 | 협심증 | 1,474 | 40 | 2.7% |

---

## 임의 설정 vs 데이터 기반 비교

| 질환 | 임의 Tier | 데이터 Tier | 변경 이유 |
|------|----------|------------|----------|
| 패혈증 | Tier 2 | **Tier 1** ↑ | 사망률 28.1%로 매우 높음 |
| 호흡부전 | Tier 2 | **Tier 1** ↑ | 사망률 27.5% |
| 급성 신부전 | Tier 3 | **Tier 1** ↑ | 사망률 12.6%, 전해질 이상 동반 |
| 고칼륨혈증 | Tier 2 | **Tier 1** ↑ | 사망률 12.6% |
| 칼슘 대사 이상 | Tier 3 | **Tier 1** ↑ | 사망률 12.1% |
| 심낭질환 | Tier 3 | **Tier 1** ↑ | 사망률 10.6% |
| 협심증 | Tier 3 | Tier 3 | 사망률 2.7%로 유지 |
| 고혈압 | Tier 4 | **Tier 3** ↑ | 사망률 4.0% |

---

## 인구통계 결합 (나이/성별)

ECG-MIMIC 논문은 ECG 신호만 모델에 입력합니다.
우리는 나이와 성별을 추가 입력으로 결합하여 진단 정확도를 높입니다.

### 근거

같은 ECG 파형이라도 환자의 나이/성별에 따라 임상적 의미가 다릅니다:
- 심방세동 유병률: 50대 2% → 80대 15% (나이에 따라 7배 차이)
- 급성 심근경색: 남성이 여성보다 2배 높음
- 고칼륨혈증: 고령 + 신부전 환자에서 집중

### 전처리

| 피처 | 원본 값 | 변환 방법 | 변환 결과 |
|------|---------|----------|----------|
| 나이 | 18~101세 | Min-Max 정규화: (age - 18) / (101 - 18) | 0.0 ~ 1.0 |
| 성별 | M / F / missing | 인코딩: M=1.0, F=0.0, Unknown=0.5 | 0.0 / 0.5 / 1.0 |

출력: `demographics = [age_norm, gender_enc]` → shape (2,)

### 모델 아키텍처

```
ECG 신호 (1000, 12)
  → S4/Transformer 백본
  → ECG 임베딩 (512차원)

나이/성별 (2,)
  → FC층 (2 → 16)
  → ReLU
  → 인구통계 임베딩 (16차원)

concat → (528차원) → FC → 24개 예측 확률
```

### 구현 코드

```python
class ECGClassifier(nn.Module):
    def __init__(self, ecg_backbone, num_labels=24):
        super().__init__()
        self.ecg_backbone = ecg_backbone       # S4 or Transformer → 512차원
        self.demo_fc = nn.Linear(2, 16)        # 나이+성별 → 16차원
        self.classifier = nn.Linear(512 + 16, num_labels)
    
    def forward(self, ecg_signal, age, gender):
        # ECG 임베딩
        ecg_emb = self.ecg_backbone(ecg_signal)          # (batch, 512)
        
        # 인구통계 임베딩
        demo = torch.stack([age, gender], dim=1)          # (batch, 2)
        demo_emb = F.relu(self.demo_fc(demo))             # (batch, 16)
        
        # 결합 + 분류
        combined = torch.cat([ecg_emb, demo_emb], dim=1)  # (batch, 528)
        return self.classifier(combined)                   # (batch, 24)
```

### 논문 대비 차이

| 항목 | ECG-MIMIC 논문 | 우리 |
|------|---------------|------|
| 모델 입력 | ECG 신호만 | ECG 신호 + 나이 + 성별 |
| 임베딩 차원 | 512 → 분류기 | 512 + 16 = 528 → 분류기 |
| 인구통계 활용 | fold 생성에만 사용 | 모델 입력으로 직접 활용 |

---

## 구현 코드

### Loss 함수

```python
import torch
import torch.nn.functional as F

class UrgencyWeightedBCELoss(torch.nn.Module):
    """30일 사망률 기반 긴급도 가중 BCE Loss"""
    
    def __init__(self, urgency_weights, focal_gamma=0.0):
        super().__init__()
        self.register_buffer('weights', urgency_weights)
        self.focal_gamma = focal_gamma
    
    def forward(self, logits, targets):
        bce = F.binary_cross_entropy_with_logits(
            logits, targets, reduction='none'
        )
        
        if self.focal_gamma > 0:
            probs = torch.sigmoid(logits)
            pt = targets * probs + (1 - targets) * (1 - probs)
            focal = (1 - pt) ** self.focal_gamma
            bce = focal * bce
        
        weighted = bce * self.weights.unsqueeze(0)
        return weighted.mean()
```

### 가중치 설정 (30일 사망률 기반)

```python
URGENCY_WEIGHTS = {
    # --- Tier 1: 사망률 ≥ 10% (weight = 3.0) ---
    'cardiac_arrest':         3.0,  # 60.1%
    'sepsis':                 3.0,  # 28.1%
    'respiratory_failure':    3.0,  # 27.5%
    'acute_mi':               3.0,  # 12.7%
    'hyperkalemia':           3.0,  # 12.6%
    'acute_kidney_failure':   3.0,  # 12.6%
    'calcium_disorder':       3.0,  # 12.1%
    'pulmonary_embolism':     3.0,  # 11.7%
    'paroxysmal_tachycardia': 3.0,  # 11.6%
    'pericardial_disease':    3.0,  # 10.6%
    
    # --- Tier 2: 사망률 5~10% (weight = 2.0) ---
    'afib_detail':            2.0,  #  9.2%
    'hf_detail':              2.0,  #  8.9%
    'afib_flutter':           2.0,  #  8.8%
    'heart_failure':          2.0,  #  8.6%
    'copd':                   2.0,  #  8.0%
    'hypokalemia':            2.0,  #  7.8%
    'chronic_kidney':         2.0,  #  7.6%
    'av_block_lbbb':          2.0,  #  6.5%
    'chronic_ihd':            2.0,  #  6.4%
    'hypothyroidism':         2.0,  #  6.3%
    'other_conduction':       2.0,  #  6.0%
    
    # --- Tier 3: 사망률 2~5% (weight = 1.5) ---
    'dm2':                    1.5,  #  4.7%
    'hypertension':           1.5,  #  4.0%
    'angina':                 1.5,  #  2.7%
}


# 텐서 변환
label_order = list(URGENCY_WEIGHTS.keys())
weights = torch.tensor([URGENCY_WEIGHTS[k] for k in label_order])
```

### 학습 코드 적용

```python
# 기존 (ECG-MIMIC 논문)
criterion = F.binary_cross_entropy_with_logits

# 변경 (긴급도 가중)
criterion = UrgencyWeightedBCELoss(
    urgency_weights=weights,
    focal_gamma=2.0  # Focal Loss 결합 (선택)
)

loss = criterion(model_output, target_labels)
loss.backward()
```

---

## 평가 지표

### Tier별 성능 리포트

```python
def tier_report(targs, preds, label_names, urgency_weights):
    tiers = {
        'Tier1_즉시조치': [i for i,k in enumerate(label_names) 
                          if urgency_weights[k] == 3.0],
        'Tier2_긴급':     [i for i,k in enumerate(label_names) 
                          if urgency_weights[k] == 2.0],
        'Tier3_중요':     [i for i,k in enumerate(label_names) 
                          if urgency_weights[k] == 1.5],
    }
    
    for tier_name, indices in tiers.items():
        tier_auroc = roc_auc_score(
            targs[:, indices], preds[:, indices], average='macro'
        )
        print(f"{tier_name}: AUROC={tier_auroc:.3f}")
```

### 핵심 평가 기준

| 지표 | Tier 1 (≥10%) | Tier 2 (5~10%) | Tier 3 (2~5%) |
|------|--------------|----------------|---------------|
| AUROC | ≥ 0.80 | ≥ 0.75 | ≥ 0.65 |
| Recall@0.5 | ≥ 0.90 | ≥ 0.80 | ≥ 0.70 |
| 의미 | 놓치면 사망 | 빠른 감지 필요 | 참고 정보 |

---

## 논문 대비 기여점 요약

| 항목 | ECG-MIMIC 논문 | 우리 |
|------|---------------|------|
| Loss | BCE (동일 가중치) | 30일 사망률 기반 가중 BCE + Focal |
| 가중치 근거 | 없음 | MIMIC-IV 실제 사망 데이터 |
| 모델 입력 | ECG 신호만 | ECG 신호 + 나이 + 성별 |
| 라벨 중요도 | 모두 동등 | 3단계 Tier (사망률 기반) |
| 평가 | macro AUROC만 | Tier별 AUROC + Recall |
| 관점 | 범용 스크리닝 | 응급실 의사결정 최적화 |
| 핵심 가치 | "얼마나 정확한가" | "놓치지 않는가" |

### 핵심 발견

- 2차 타겟(비심혈관)인 패혈증(28.1%), 호흡부전(27.5%), 급성 신부전(12.6%)이 
  1차 타겟(심혈관)인 심방세동(8.8%)보다 사망률이 훨씬 높음
- → ECG 간접 단서로 비심혈관 고위험 질환을 감지하는 것의 임상적 가치가 매우 큼
- → "ECG만으로 패혈증/호흡부전을 조기 감지할 수 있다"는 것이 강력한 기여점
