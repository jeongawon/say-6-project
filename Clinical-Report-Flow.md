# 멀티모달 임상 의사결정 지원 시스템 — 결과 흐름 시나리오

## 환자 정보

- 나이/성별: 72세 여성
- 주 증상: 흉통, 호흡곤란
- 과거력: 고혈압

---

## Step 1: 환자 입력 → Bedrock Agent 첫 판단

```json
{
  "age": 72,
  "gender": "F",
  "chief_complaint": "흉통, 호흡곤란",
  "past_history": ["고혈압"]
}
```

Agent 판단: "흉통 + 호흡곤란 → ECG 먼저 호출"

---

## Step 2: ECG 모달 결과

```json
{
  "predictions": {
    "afib_flutter":        0.87,
    "heart_failure":       0.72,
    "hyperkalemia":        0.45,
    "cardiac_arrest":      0.03
  },
  "abnormal_flags": {
    "heart_rate": {"value": 142, "status": "CRITICAL_HIGH"}
  }
}
```

Agent 판단:
- 심방세동 87% + 심부전 72% 확인
- 고칼륨혈증 45% 의심 → 혈액검사 필요
- 심박수 142 CRITICAL → 빈맥 확인

→ **Lab 모달 호출**

---

## Step 3: Lab 모달 결과

```json
{
  "predicted_group": "Cardio_Group",
  "probabilities": {
    "Cardio_Group":  0.68,
    "Sepsis_Group":  0.18,
    "Kidney_Group":  0.11
  },
  "abnormal_flags": {
    "potassium":  {"value": 6.1,  "status": "CRITICAL_HIGH"},
    "bun":        {"value": 1200, "status": "CRITICAL_HIGH"},
    "creatinine": {"value": 2.8,  "status": "HIGH"}
  }
}
```

Agent 판단:
- 칼륨 6.1 CRITICAL → 심정지 위험 확인
- BNP 1200 CRITICAL → 심부전 확정
- 크레아티닌 2.8 HIGH → 신기능 저하
- 폐부종 동반 여부 확인 필요

→ **CXR 모달 호출**

---

## Step 4: CXR 모달 결과

```json
{
  "predictions": {
    "pulmonary_edema": 0.78,
    "cardiomegaly":    0.65,
    "pleural_effusion":0.42
  },
  "abnormal_flags": {
    "pulmonary_edema": {"value": 0.78, "status": "HIGH"},
    "cardiomegaly":    {"value": 0.65, "status": "HIGH"}
  }
}
```

Agent 판단:
- 폐부종 78% 확인 → 심부전 악화 증거
- 심비대 65% → 만성 심장 과부하 소견
- 모든 검사 완료 → 최종 소견서 생성

---

## Step 5: 최종 소견서

```
[AI 임상 보조 소견서]
환자: 72세 여성
검사 일시: 2026-04-06 09:15

[검사 결과 요약]

■ 심전도 (ECG)
  - 심방세동 (87%) — 확인됨
  - 심부전 소견 (72%)
  - 고칼륨혈증 의심 (45%)
  - 심박수 142 bpm (빈맥)

■ 혈액검사 (Lab)
  - 칼륨 6.1 mEq/L ↑↑ (위험)
  - BNP 1,200 pg/mL ↑↑
  - 크레아티닌 2.8 mg/dL ↑

■ 흉부 X-ray (CXR)
  - 폐부종 (78%)
  - 심비대 (65%)

[종합 소견]
심방세동을 동반한 급성 심부전 악화 소견.
고칼륨혈증 및 신기능 저하가 동반되어 있으며
흉부 X-ray상 폐부종 확인됨.

심비대는 만성 심장 과부하의 결과로,
심부전이 상당 기간 진행되었음을 시사함.

[위험도]
🔴 CRITICAL — 즉각적 처치 필요

[권고 사항]
1. 심장내과 즉시 협진
2. 이뇨제 투여 (폐부종 치료)
3. 고칼륨혈증 처치 (칼슘 글루코네이트)
4. 신장내과 협진 (크레아티닌 2.8)
5. 지속적 심전도 모니터링

※ 본 소견은 AI 보조 도구로 생성되었으며
   최종 진단은 담당 의사의 판단에 따릅니다.
```

---

## 질환 관계도

```
심부전 (근본 원인)
  │
  ├── 심장 과부하 지속 → 심비대 (CXR)
  ├── 폐에 혈액 고임  → 폐부종 (CXR)
  ├── 심장 리듬 이상  → 심방세동 (ECG)
  └── 신장 혈류 감소  → 신기능 저하 → 고칼륨혈증 (Lab)
```

---

## 모달별 역할 요약

| 모달 | 발견 사항 | Bedrock Agent 판단 |
|------|----------|-------------------|
| ECG | 심방세동, 심부전 의심, 고칼륨혈증 의심 | 혈액검사 필요 |
| Lab | 칼륨 CRITICAL, BNP CRITICAL, 크레아티닌 HIGH | 폐부종 확인 필요 |
| CXR | 폐부종, 심비대 | 모든 검사 완료 → 소견서 생성 |

---

## 추가 테스트 케이스

---

### 케이스 2: Lab → ECG → CXR (패혈증 + 심장 합병증)

**환자**: 65세 남성 / 발열, 저혈압, 의식 저하 / 과거력: 당뇨

**Step 1: Lab 먼저 호출**
Agent 판단: "발열 + 저혈압 → 패혈증 의심 → 혈액검사 먼저"

```json
{
  "predicted_group": "Sepsis_Group",
  "probabilities": {"Sepsis_Group": 0.81, "Cardio_Group": 0.12},
  "abnormal_flags": {
    "wbc":        {"value": 22.3, "status": "HIGH"},
    "potassium":  {"value": 6.4,  "status": "CRITICAL_HIGH"},
    "creatinine": {"value": 3.1,  "status": "HIGH"},
    "albumin":    {"value": 2.0,  "status": "LOW"}
  }
}
```

Agent 판단: "패혈증 확인 + 칼륨 6.4 CRITICAL → 심장 영향 확인 필요"
→ **ECG 호출**

**Step 2: ECG 결과**
```json
{
  "predictions": {
    "hyperkalemia":     0.89,
    "cardiac_arrest":   0.34,
    "av_block_lbbb":    0.41
  },
  "abnormal_flags": {
    "heart_rate": {"value": 38, "status": "CRITICAL_LOW"}
  }
}
```

Agent 판단: "고칼륨혈증으로 인한 서맥 + 전도 장애 → 폐 상태 확인"
→ **CXR 호출**

**최종 소견**
```
[위험도] 🔴 CRITICAL
종합 진단: 패혈증 유발 다발성 장기부전
  - 패혈증 (WBC 22.3, 발열, 저혈압)
  - 고칼륨혈증 (6.4) → 심전도 이상 (서맥 38bpm, 전도 장애)
  - 급성 신부전 (크레아티닌 3.1)
  - 심정지 위험 34%

권고: 즉시 ICU 이송, 투석 고려, 칼슘 글루코네이트 즉시 투여
```

**왜 놓치면 안 되나**: 패혈증 환자에서 고칼륨혈증을 놓치면 심정지로 이어짐. Lab 없이 ECG만 봤으면 원인을 몰랐을 케이스.

---

### 케이스 3: ECG → CXR (Lab 불필요, 폐색전증)

**환자**: 45세 여성 / 갑작스러운 호흡곤란, 흉통 / 과거력: 장거리 비행 후

**Step 1: ECG 호출**
Agent 판단: "갑작스러운 호흡곤란 + 흉통 → ECG 먼저"

```json
{
  "predictions": {
    "pulmonary_embolism": 0.78,
    "cardiac_arrest":     0.21,
    "paroxysmal_tachycardia": 0.65
  },
  "abnormal_flags": {
    "heart_rate": {"value": 128, "status": "CRITICAL_HIGH"}
  }
}
```

Agent 판단: "폐색전증 78% + 빈맥 → 혈액검사보다 CXR로 폐 상태 즉시 확인"
→ **CXR 호출** (Lab 스킵)

**Step 2: CXR 결과**
```json
{
  "predictions": {
    "pulmonary_embolism_sign": 0.72,
    "pleural_effusion":        0.58,
    "cardiomegaly":            0.31
  },
  "abnormal_flags": {
    "pleural_effusion": {"value": 0.58, "status": "HIGH"}
  }
}
```

**최종 소견**
```
[위험도] 🔴 CRITICAL
종합 진단: 급성 폐색전증 의심
  - ECG: 폐색전증 패턴 78%, 빈맥 128bpm
  - CXR: 흉막삼출 58%, 폐색전증 소견 72%

권고: 즉시 CT 폐혈관조영술, 항응고 치료 시작, 흉부외과 협진
```

**왜 놓치면 안 되나**: 폐색전증은 초기 30분 내 사망률이 높음. Lab 기다리는 시간 없이 CXR 직행이 맞는 케이스. Agent가 Lab을 스킵한 판단이 핵심.

---

### 케이스 4: Lab → CXR (ECG 불필요, 항암 환자 폐렴)

**환자**: 58세 남성 / 발열, 기침, 호흡곤란 / 과거력: 폐암 항암치료 중

**Step 1: Lab 먼저 호출**
Agent 판단: "항암 환자 + 발열 → 면역 저하 감염 의심 → 혈액검사 먼저"

```json
{
  "predicted_group": "Chemo_Group",
  "probabilities": {"Chemo_Group": 0.74, "Sepsis_Group": 0.21},
  "abnormal_flags": {
    "wbc":       {"value": 0.8,  "status": "CRITICAL_LOW"},
    "albumin":   {"value": 2.2,  "status": "LOW"},
    "glucose":   {"value": 48,   "status": "CRITICAL_LOW"}
  }
}
```

Agent 판단: "WBC 0.8 CRITICAL → 심각한 면역 저하 + 기침 → 폐렴 확인 필요. 심장 증상 없어 ECG 불필요"
→ **CXR 호출** (ECG 스킵)

**Step 2: CXR 결과**
```json
{
  "predictions": {
    "pneumonia":       0.91,
    "pleural_effusion":0.44,
    "pulmonary_edema": 0.22
  },
  "abnormal_flags": {
    "pneumonia": {"value": 0.91, "status": "CRITICAL_HIGH"}
  }
}
```

**최종 소견**
```
[위험도] 🔴 CRITICAL
종합 진단: 면역 저하 환자의 중증 폐렴 (호중구 감소성 발열)
  - WBC 0.8 CRITICAL → 호중구 감소증
  - CXR: 폐렴 91%, 흉막삼출 44%
  - 혈당 48 CRITICAL → 저혈당 동반

권고: 즉시 광범위 항생제 투여, 격리 입원, 혈액종양내과 협진,
      저혈당 교정 (포도당 정맥 투여)
```

**왜 놓치면 안 되나**: 항암 환자는 WBC가 낮아 감염에 대한 발열 반응 자체가 약함. 일반 환자보다 훨씬 빠르게 패혈증으로 진행. ECG 없이 Lab → CXR 직행이 시간을 아낀 케이스.
