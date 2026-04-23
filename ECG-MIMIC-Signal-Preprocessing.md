# ECG-MIMIC 신호 전처리 로직 분석

> 소스: [AI4HealthUOL/ECG-MIMIC](https://github.com/AI4HealthUOL/ECG-MIMIC)
> 핵심 파일: `ecg_utils.py` → `prepare_mimicecg()`

## 전체 파이프라인 흐름

```
zip에서 .hea/.dat 읽기 → NaN 보간 → 진폭 클리핑(±3mV) → 리샘플링(500→100Hz) → 12채널 정렬 → npy 저장
```

---

## Step 1: ECG 파형 읽기

```python
sigbufs, header = wfdb.rdsamp(filename)
```

| 항목 | 값 |
|------|-----|
| 원본 샘플링 레이트 | 500Hz |
| 기록 길이 | 10초 |
| 리드 수 | 12 |
| 원본 shape | (5000, 12) |

- `wfdb` 라이브러리로 PhysioNet WFDB 포맷(.hea + .dat) 파싱
- `.hea`: 헤더 (채널명, 샘플링레이트, 날짜 등)
- `.dat`: 실제 파형 바이너리 데이터

---

## Step 2: NaN 보간 + 진폭 클리핑

```python
def fix_nans_and_clip(signal, clip_amp=3):
    for i in range(signal.shape[1]):  # 채널별 처리
        tmp = pd.DataFrame(signal[:,i]).interpolate().values.ravel()
        signal[:,i] = np.clip(tmp, a_max=clip_amp, a_min=-clip_amp)
```

| 처리 | 방법 | 파라미터 |
|------|------|----------|
| NaN 처리 | `pd.interpolate()` 선형 보간 | 앞뒤 값 사이를 선형으로 채움 |
| 진폭 클리핑 | `np.clip()` | ±3mV (극단적 노이즈/아티팩트 제거) |

- NaN이 있는 경우에만 보간 수행
- 클리핑은 NaN 유무와 관계없이 항상 적용
- 채널별(12개)로 독립 처리

---

## Step 3: 리샘플링 (500Hz → 100Hz)

```python
def resample_data(sigbufs, channel_labels, fs, target_fs,
                  channels=12, channel_stoi=None):
    factor = target_fs / fs              # 100/500 = 0.2
    timesteps_new = int(len(sigbufs) * factor)  # 5000 × 0.2 = 1000
    data = np.zeros((timesteps_new, channels), dtype=np.float32)
    for i, cl in enumerate(channel_labels):
        if cl in channel_stoi.keys() and channel_stoi[cl] < channels:
            data[:, channel_stoi[cl]] = resampy.resample(
                sigbufs[:,i], fs, target_fs
            ).astype(np.float32)
    return data
```

| 항목 | 변환 전 | 변환 후 |
|------|---------|---------|
| 샘플링 레이트 | 500Hz | 100Hz |
| Timesteps | 5,000 | 1,000 |
| Shape | (5000, 12) | (1000, 12) |
| 파일 크기 (npy) | ~240KB | ~48KB |

- `resampy` 라이브러리 사용 (고품질 리샘플링)
- 채널별로 독립 리샘플링
- dtype: float32

---

## Step 4: 12채널 정렬 (채널 순서 표준화)

```python
channel_stoi_default = {
    "i": 0, "ii": 1,
    "v1": 2, "v2": 3, "v3": 4, "v4": 5, "v5": 6, "v6": 7,
    "iii": 8, "avr": 9, "avl": 10, "avf": 11,
    "vx": 12, "vy": 13, "vz": 14  # 사용 안 됨 (channels=12)
}
```

| 인덱스 | 채널 | 인덱스 | 채널 |
|--------|------|--------|------|
| 0 | I | 6 | V5 |
| 1 | II | 7 | V6 |
| 2 | V1 | 8 | III |
| 3 | V2 | 9 | aVR |
| 4 | V3 | 10 | aVL |
| 5 | V4 | 11 | aVF |

- 원본 파일마다 채널 순서가 다를 수 있음
- 채널명(소문자)으로 매핑하여 항상 동일한 순서로 정렬
- 매핑에 없는 채널은 0으로 채워짐

---

## Step 5: npy 파일 저장

```python
np.save(target_folder / tmp["data"], data)
# 파일명 예시: p10000032_40689238.npy
# shape: (1000, 12)
# dtype: float32
# 크기: ~48KB
```

---

## Step 6: 학습 시 정규화 (main_ecg.py)

저장 시점이 아닌 학습 시점에 정규화를 적용합니다.

```python
# PTB-XL 데이터셋의 채널별 통계 사용 (MIMIC 자체 통계 아님)
ds_mean = np.array([
    -0.00184586, -0.00130277,  0.00017031, -0.00091313,
    -0.00148835, -0.00174687, -0.00077071, -0.00207407,
     0.00054329,  0.00155546, -0.00114379, -0.00035649
])
ds_std = np.array([
    0.16401004, 0.1647168,  0.23374124, 0.33767231,
    0.33362807, 0.30583013, 0.2731171,  0.27554379,
    0.17128962, 0.14030828, 0.14606956, 0.14656108
])

# Transform으로 적용
transforms.Compose([Normalize(ds_mean, ds_std), ToTensor()])
```

| 항목 | 설명 |
|------|------|
| 정규화 방식 | Z-score (채널별) |
| 통계 출처 | PTB-XL 데이터셋 (cross-dataset 일반화 목적) |
| 적용 시점 | 학습/추론 시 DataLoader transform |

---

## Step 7: memmap 변환 (선택)

```python
reformat_as_memmap(df, "memmap.npy", data_folder, ...)
```

- 개별 npy 파일들을 하나의 memory-mapped 파일로 통합
- 대규모 데이터셋에서 랜덤 액세스 속도 향상
- 학습 시 디스크 I/O 병목 해소

---

## 핵심 특징: 하지 않는 것들

| 전처리 기법 | 적용 여부 | 비고 |
|------------|----------|------|
| 밴드패스 필터 (0.5-40Hz) | ❌ | 모델이 학습으로 대체 |
| 60Hz 노치 필터 | ❌ | 모델이 학습으로 대체 |
| 베이스라인 원더링 보정 | ❌ | 모델이 학습으로 대체 |
| R-peak 검출 | ❌ | 사용 안 함 |
| 세그멘테이션 (beat 단위) | ❌ | 전체 10초 사용 |
| 데이터 증강 | ❌ | 사용 안 함 |

논문의 접근: 최소한의 전처리(NaN 보간 + 클리핑 + 리샘플링)만 수행하고, 나머지는 딥러닝 모델(S4)이 raw 신호에서 직접 학습하도록 함. 이 방식으로 AUROC 0.75~0.98 달성.

---

## 학습 시 데이터 흐름 요약

```
npy 파일 (1000, 12)
  → Normalize (PTB-XL mean/std)
  → ToTensor
  → Chunk (input_size=250, stride=250)  # 2.5초 단위 슬라이딩
  → 모델 입력: (batch, 12, 250)
  → 예측 후 aggregate_predictions()로 환자 단위 평균
```

| 파라미터 | 값 | 설명 |
|----------|-----|------|
| input_size | 250 | 2.5초 @ 100Hz |
| stride | 250 (valtest) | 겹침 없이 슬라이딩 |
| chunk_length | 250 | 입력 윈도우 크기 |
| 집계 방식 | np.mean | 같은 ECG의 여러 chunk 예측을 평균 |
