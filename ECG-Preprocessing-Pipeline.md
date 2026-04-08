# ECG 데이터 전처리 파이프라인 설계

## 전체 흐름

```
[입력]
  ecg_ed_first_24targets.csv (158,440건 메타데이터 + 24개 라벨)
  ecg_waveforms/ (316,880개 .hea/.dat 파일)

[전처리]
  1. CSV 로딩 → 메타데이터 + 라벨 파싱
  2. ECG 파형 읽기 (wfdb) → (5000, 12)
  3. NaN 보간 + ±3mV 클리핑
  4. 리샘플링 500Hz → 100Hz → (1000, 12)
  5. 12채널 정렬 (채널명 기반)
  6. 나이/성별 정규화 → (2,)
  7. npy 저장 + manifest.csv 생성

[출력]
  processed/
    signals/     → 158,440개 .npy (1000, 12) float32 ~48KB each
    demographics/ → 158,440개 .npy (2,) float32
    manifest.csv → study_id, npy경로, 24개 라벨, fold, 가중치
    urgency_weights.npy → (24,) 긴급도 가중치
    ptb_xl_stats.npz → mean/std (정규화용, 학습 시 적용)
```

---

## Step 1: CSV 로딩

| 컬럼 | 용도 |
|------|------|
| file_name | ECG 파형 파일 경로 |
| study_id | 고유 식별자 |
| subject_id | 환자 ID (fold 검증용) |
| age | 나이 → 정규화 |
| gender | 성별 → 인코딩 |
| strat_fold | 20-fold 분할 |
| 24개 라벨 컬럼 | 멀티핫 타겟 (0/1) |

---

## Step 2: ECG 파형 읽기

```python
sigbufs, header = wfdb.rdsamp(file_path)
# sigbufs: (5000, 12) — 10초 × 500Hz × 12리드
# header['fs']: 500 (샘플링 레이트)
# header['sig_name']: ['I','II','III','aVR','aVL','aVF','V1',...,'V6']
```

- 입력: ecg_waveforms/files/p1000/.../40689238 (.hea + .dat)
- wfdb 라이브러리로 PhysioNet WFDB 포맷 파싱

---

## Step 3: NaN 보간 + 진폭 클리핑

```python
# 채널별 독립 처리
for i in range(12):
    signal[:, i] = pd.Series(signal[:, i]).interpolate().values  # NaN 선형 보간
    signal[:, i] = np.clip(signal[:, i], -3.0, 3.0)             # ±3mV 클리핑
```

| 처리 | 방법 | 이유 |
|------|------|------|
| NaN 보간 | pandas 선형 보간 | 일부 ECG에 결측 샘플 존재 |
| 클리핑 | ±3mV | 극단적 노이즈/아티팩트 제거 |

ECG-MIMIC 논문과 동일. 밴드패스/노치 필터는 적용하지 않음 (모델이 학습으로 대체).

---

## Step 4: 리샘플링 (500Hz → 100Hz)

```python
data = resampy.resample(sigbufs, 500, 100, axis=0)
# (5000, 12) → (1000, 12)
```

| 항목 | 변환 전 | 변환 후 |
|------|---------|---------|
| 샘플링 레이트 | 500Hz | 100Hz |
| Timesteps | 5,000 | 1,000 |
| 10초 기록 | 유지 | 유지 |
| 파일 크기 | ~240KB | ~48KB |

resampy 라이브러리 사용 (고품질 다운샘플링).

---

## Step 5: 12채널 정렬

원본 파일마다 채널 순서가 다를 수 있어서, 채널명으로 매핑하여 고정 순서로 정렬.

| 인덱스 | 채널 | 인덱스 | 채널 |
|--------|------|--------|------|
| 0 | I | 6 | V5 |
| 1 | II | 7 | V6 |
| 2 | V1 | 8 | III |
| 3 | V2 | 9 | aVR |
| 4 | V3 | 10 | aVL |
| 5 | V4 | 11 | aVF |

---

## Step 6: 나이/성별 정규화

```python
age_norm = (age - 18) / (101 - 18)   # 0~1 범위
gender_enc = 1.0 if M, 0.0 if F, 0.5 if Unknown
demographics = [age_norm, gender_enc]  # shape: (2,)
```

| 피처 | 원본 | 변환 |
|------|------|------|
| 나이 | 18~101세 | 0.0~1.0 (min-max) |
| 성별 | M/F/missing | 1.0 / 0.0 / 0.5 |

학습 시 ECG 임베딩(512차원)과 concat하여 분류기에 입력.

---

## Step 7: 저장 구조

### signals/ — ECG 파형

```
processed/signals/40689238.npy
  shape: (1000, 12)
  dtype: float32
  크기: ~48KB
```

### demographics/ — 인구통계

```
processed/demographics/40689238.npy
  shape: (2,)
  dtype: float32
  값: [age_norm, gender_enc]
```

### manifest.csv — 학습용 매니페스트

```csv
study_id,signal_path,demo_path,strat_fold,afib_flutter,heart_failure,...,calcium_disorder
40689238,signals/40689238.npy,demographics/40689238.npy,9,0,1,...,0
```

### urgency_weights.npy — 긴급도 가중치

```
shape: (24,)
값: [2.0, 2.0, 1.5, 2.0, 3.0, 3.0, ...]  # 라벨 순서대로
```

### ptb_xl_stats.npz — 정규화 통계

```
mean: (12,) — PTB-XL 채널별 평균
std: (12,) — PTB-XL 채널별 표준편차
```

정규화는 저장 시점이 아닌 학습 시점에 DataLoader transform으로 적용.

---

## 학습 시 데이터 흐름

```
manifest.csv에서 배치 샘플링
  → signals/xxx.npy 로딩 (1000, 12)
  → PTB-XL 통계로 Z-score 정규화
  → Chunk (input_size=250, stride=250) → 4개 윈도우
  → 모델 입력: (batch, 12, 250)
  
  → demographics/xxx.npy 로딩 (2,)
  
  → ECG 임베딩 (512) + demo (16) → concat (528)
  → 분류기 → 24개 예측
  → 긴급도 가중 BCE Loss
```

---

## 예상 출력 크기

| 항목 | 크기 |
|------|------|
| signals/ | 158,440 × 48KB ≈ 7.2GB |
| demographics/ | 158,440 × 8B ≈ 1.2MB |
| manifest.csv | ~30MB |
| 전체 | ~7.3GB |

---

## 실행 순서

```bash
# 1. 다운로드 완료 확인
find ecg_waveforms -type f -size +0 | wc -l  # 316,880이면 완료

# 2. 전처리 실행
python preprocess_ecg.py

# 3. 결과 확인
ls processed/
# signals/  demographics/  manifest.csv  urgency_weights.npy  ptb_xl_stats.npz
```
