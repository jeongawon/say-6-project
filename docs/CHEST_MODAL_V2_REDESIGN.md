# 흉부 모달 v2 — Clinical Logic Layer 기반 재설계

> 최종 업데이트: 2026-03-22
> 이 문서는 기존 흉부 모달(DenseNet+Grad-CAM)을 전면 재설계한 것입니다.
> 핵심 변경: "전문의의 판독 로직을 알고리즘화"하여 정량적/해부학적 근거가 있는 소견을 생성
> **Layer 3 Clinical Logic 구현 완료 (2026-03-22)** — 14개 질환 Rule + 교차검증 + 감별진단 + 위험도 3단계

---

## 1. 전체 시스템 흐름 (MIMIC-IV Note 기반 테스트)

### 실제 작동 시나리오
```
[MIMIC-IV Note에서 추출한 실제 환자 기록]

1. 환자 도착 (응급차)
   - 67세 남성, 주소: "흉통, 호흡곤란, 기침"
   - 활력: HR 110, BP 90/60, SpO2 88%, RR 28, Temp 38.2

2. 오케스트레이터 (응급의 역할)
   → "흉통+빈맥+저혈압 → 심장 먼저"
   → ECG 모달 호출

3. ECG 모달 → "정상 동성리듬, STEMI 아님"
   → 결과가 중앙 DB에 저장됨

4. 오케스트레이터 재판단
   → "심장은 배제. 기침+발열+호흡곤란 → 폐 보자"
   → 흉부 X-Ray 모달 호출
   → 입력에 [환자정보 + 증상 + ECG 정상 결과]가 포함됨

5. 흉부 모달 내부 처리
   - 해부학 세그멘테이션 (폐/심장/뼈)
   - DenseNet-121 14-label 분류
   - YOLOv8 병변 탐지 (바운딩 박스)
   - Clinical Logic (CTR 계산, Silhouette sign, CP angle 등)
   - 교차 검증 (DenseNet vs YOLO vs Clinical Logic 일치 여부)
   - RAG (유사 판독문 검색)
   - Bedrock 종합 소견 (이전 ECG 결과 맥락 반영)
   → "좌하엽 경화(Silhouette sign+), CTR 0.48(정상) → 심인성 배제, 감염성 폐렴 의심"

6. 오케스트레이터 재판단
   → "감염 확인 필요 → 혈액검사"
   → 혈액검사 모달 호출

7. 혈액검사 모달 → "WBC 15,000↑, CRP 12.5↑"

8. 오케스트레이터 → 충분 → 소견서 생성

[비교 대상: MIMIC-IV Note의 실제 의사 판단 + 최종 진단]
```

### 핵심 원칙
- 각 모달은 **이전 검사 결과를 맥락으로 받음** (독립 판독이 아님)
- 흉부 모달이 "ECG 정상"을 알면 "심인성 폐부종은 아닐 가능성 높다"를 소견에 반영
- 테스트 케이스의 "정답"은 MIMIC-IV Note의 실제 의사 판단

---

## 2. 흉부 모달 v2 아키텍처 — 6-Layer 파이프라인

```
CXR 이미지 입력 + 환자정보 + 이전 검사결과
    ↓
[Layer 1] Anatomy Segmentation — 해부학 구조 추출
    ├── Lung Seg: 좌/우 폐 마스크, 폐엽 구분, 면적 계산
    ├── Heart Seg: 심장 윤곽, 양쪽 경계점 좌표
    └── Bone Seg: 늑골 개별 추적, 쇄골, 척추 (선택)
    ↓
[Layer 2] Disease Detection — 질환 탐지
    ├── DenseNet-121: 14-label 확률 (뭐가 있는가?)
    └── YOLOv8: 바운딩 박스 (어디에 있는가?)
    ↓
[Layer 3] Clinical Logic — 전문의 판독 로직 ★ 구현 완료 (2026-03-22)
    ├── 질환별 Rule-Based 분석 (CTR, CP angle, Silhouette 등) → 14개 Rule 모듈
    ├── 정량적 수치 산출 (CTR 0.54, 기흉 거리 2.3cm 등) → thresholds.py
    ├── 해부학적 위치 특정 (좌하엽, 우측 CP angle 등) → 각 Rule 내 location 출력
    ├── 3-소스 교차검증 (DenseNet vs YOLO vs Logic) → cross_validation.py
    ├── 6개 감별진단 패턴 → differential.py
    └── 위험도 3단계 (CRITICAL/URGENT/ROUTINE) → engine.py Phase 4
    ↓
[Layer 4] Cross-Validation — 교차 검증
    ├── DenseNet vs YOLO vs Clinical Logic 일치 확인
    ├── 불일치 시 신뢰도 하향 + 의사 확인 플래그
    └── 동반 소견 조합으로 감별 진단
    ↓
[Layer 5] RAG + Context — 지식 검색 + 맥락 반영
    ├── PubMedBERT+FAISS: 유사 판독문 Top-3
    └── 이전 검사 결과 (ECG 정상 등) 맥락 반영
    ↓
[Layer 6] Bedrock Report — 최종 소견 생성
    └── 어노테이션 이미지 + 정량 수치 + RAG + 맥락 → 구조화된 JSON
```

---

## 3. 14개 질환별 임상 기준 + 알고리즘 매핑

### 3-1. Cardiomegaly (심비대)

**전문의 판독 기준:**
- CTR(Cardiothoracic Ratio) > 0.50이면 심비대
- 심장 가로 최대 폭 / 흉곽 가로 최대 폭
- 좌심실 비대: 좌측 심장 경계가 좌측 하방으로 편위
- 우심실 비대: 심장 첨부가 위쪽으로 들림 (boot-shaped)
- PA 뷰에서만 유효 (AP는 심장이 확대되어 보임)

**정량 지표:** CTR 수치 (소수점 2자리), 심장 가로 폭 (cm), 흉곽 가로 폭 (cm)

**알고리즘:**
- U-Net (심장+폐 세그멘테이션) → 심장 마스크에서 좌측/우측 경계점 자동 추출 → 심장 가로 폭 계산
- 폐 마스크에서 흉곽 내벽 좌측/우측 경계점 → 흉곽 가로 폭 계산
- CTR = 심장 가로 폭 / 흉곽 가로 폭
- Rule: CTR > 0.50 → cardiomegaly, > 0.60 → severe

**학습 데이터:** JSRT (247장, 심장+폐 마스크) + CheXmask (676K장, HybridGNet 생성 마스크)

**프론트엔드 출력:** "CTR 0.54 (정상 <0.50) → 심비대" + 심장/흉곽 윤곽선 오버레이

---

### 3-2. Pleural Effusion (흉수)

**전문의 판독 기준:**
- Costophrenic(CP) angle 둔화 — 가장 첫 번째 징후 (~200-300mL부터)
- Meniscus sign — 바깥쪽 높고 안쪽 낮은 오목 곡선
- 횡격막 소실 — 흉수가 많으면 횡격막 윤곽 안 보임
- Veil-like opacity — 한쪽 전체가 뿌연데 혈관은 보임 (경화와 구분점)
- 대량 흉수: 종격동이 반대쪽으로 밀림

**정량 지표:** CP angle 각도 (도), 추정량 (소량/중등/대량), 좌/우 구분

**알고리즘:**
- U-Net 폐 세그멘테이션 → 폐 마스크 하단의 CP angle 영역 추출
- CP angle 곡률 분석: 정상(날카로운 각도) vs 둔화(둥근 곡선)
- 횡격막 선명도 측정: 폐-횡격막 경계의 gradient 강도
- 흉수 양 추정: CP angle만 둔화(소량) / 횡격막 절반 가림(중등) / 폐야 전체 음영(대량)
- YOLOv8 바운딩 박스로 흉수 영역 탐지 (VinDr-CXR에 Pleural Effusion bbox 있음)

**학습 데이터:** VinDr-CXR (18K장, Pleural effusion bbox) + SIIM (폐 세그멘테이션)

**프론트엔드 출력:** "우측 CP angle 둔화, 추정량 ~300mL, Meniscus sign(+)" + CP angle 영역 하이라이트

---

### 3-3. Pneumothorax (기흉)

**전문의 판독 기준:**
- Visceral pleural line — 폐 가장자리에 가느다란 흰 선, 바깥에 lung marking 없음
- 크기: 폐 가장자리~흉벽 거리 > 2cm면 "large"
- Tension: 종격동이 반대쪽으로 밀림 + 횡격막 하강 → 응급!
- Deep sulcus sign — 앙와위에서 CP angle이 비정상적으로 깊어짐

**정량 지표:** 폐 가장자리~흉벽 거리 (cm), 좌/우, 크기(small/large), tension 여부

**알고리즘:**
- U-Net 폐 세그멘테이션 → 폐 마스크 경계선 추출
- 폐 마스크 경계 vs 흉벽(늑골 안쪽) 사이 거리 계산
- Rule: 거리 > 2cm → large pneumothorax
- 종격동 위치 분석: 기관 중심선이 한쪽으로 편위 → tension 경고
- SIIM-ACR Pneumothorax 데이터셋: 픽셀 단위 기흉 마스크 (12K장)

**학습 데이터:** SIIM-ACR Pneumothorax (12,047장, 세그멘테이션 마스크) — Kaggle 공개

**프론트엔드 출력:** "좌측 기흉, 폐 경계~흉벽 2.3cm → Large. 종격동 편위 없음 → Tension 아님" + 기흉 영역 마스크 오버레이

---

### 3-4. Consolidation (경화)

**전문의 판독 기준:**
- 균일한 음영 증가 (해당 폐엽이 뿌옇게 하얘짐)
- Air bronchogram — 주변 폐포는 물 찼는데 기관지는 공기 남아서 검은 가지처럼 보임
- Silhouette sign으로 위치 특정:
  - 심장 좌측 경계 소실 → 좌상엽 설엽(lingula)
  - 심장 우측 경계 소실 → 우중엽
  - 좌측 횡격막 소실 → 좌하엽
  - 우측 횡격막 소실 → 우하엽

**정량 지표:** 위치(어떤 폐엽), Silhouette sign(+/-), Air bronchogram(+/-), 면적(%)

**알고리즘:**
- YOLOv8 bbox → 경화 영역 탐지 (VinDr-CXR에 Consolidation bbox 있음)
- U-Net 폐엽 세그멘테이션 → bbox가 어떤 폐엽에 위치하는지 매핑
- Silhouette sign 탐지: 심장/횡격막 경계의 gradient 강도 측정 → 경계 소실 여부
- Air bronchogram: 경화 영역 내에서 선형의 저음영 구조물 탐지 (선택, 고난도)

**학습 데이터:** VinDr-CXR (Consolidation bbox) + JSRT (폐 세그멘테이션)

**프론트엔드 출력:** "좌하엽 경화, Silhouette sign(+, 좌측 횡격막 소실)" + 경화 영역 bbox + 폐엽 매핑

---

### 3-5. Edema (폐부종)

**전문의 판독 기준 — 4단계 진행:**
1. Cephalization: 상엽 혈관이 하엽보다 굵어짐 (초기, 매우 미세)
2. Interstitial edema: 폐문 주위 흐려짐, Kerley B line (CP angle 근처 짧은 수평선)
3. Alveolar edema: 양쪽 폐문 주위 대칭적 음영 — "butterfly/bat wing 패턴"
4. 흉수 동반: 양쪽 CP angle 둔화

**정량 지표:** 분포 패턴(편측/양측/대칭), butterfly 패턴 여부, 동반 소견(CTR, 흉수)

**알고리즘:**
- DenseNet-121 Edema 확률 + 양측 대칭성 분석
- 양측 대칭성: 좌/우 폐 마스크 내 음영 분포의 대칭도 (pixel intensity histogram 비교)
- Butterfly 패턴: 폐문 주위 vs 주변부의 음영 비율 (중심부 > 주변부면 butterfly)
- 동반 소견 교차: CTR > 0.50 + 양측 대칭 + CP angle 둔화 → "CHF 폐부종" 가능성 높음
- 감별: CTR 정상 + 비대칭 + 급성 → "ARDS" 가능성

**학습 데이터:** VinDr-CXR (Edema bbox) + CheXmask (폐 세그멘테이션)

**프론트엔드 출력:** "양측 폐부종, butterfly 패턴, CTR 0.57 동반 → CHF 의심" + 대칭성 시각화

---

### 3-6. Enlarged Cardiomediastinum (종격동 확대)

**전문의 판독 기준:**
- 종격동 너비 > 8cm (PA 뷰 기준)
- 대동맥궁(aortic knob) 돌출/석회화
- 기관 편위 (종괴에 의해 밀림)
- Paratracheal stripe > 3mm

**정량 지표:** 종격동 너비 (cm), 대동맥궁 크기, 기관 위치

**알고리즘:**
- U-Net 심장+폐 세그멘테이션 → 종격동 영역 = 좌폐와 우폐 사이 공간
- 종격동 너비 자동 측정 (기관 분기부 레벨에서)
- 기관 중심선 추출 → 편위 여부 확인
- Rule: 종격동 너비 > 8cm → enlarged

**학습 데이터:** CheXmask + JSRT (폐/심장 마스크로 종격동 영역 간접 추출)

**프론트엔드 출력:** "종격동 너비 9.2cm (정상 <8cm), 기관 편위 없음" + 종격동 영역 표시

---

### 3-7. Atelectasis (무기폐)

**전문의 판독 기준:**
- 폐 용적 감소 (해당 폐엽이 쪼그라듦)
- 종격동 이동: 무기폐 쪽으로 기관/심장 끌려감
- 횡격막 거상: 해당 쪽 횡격막이 위로 올라감
- 보상성 과팽창: 정상 폐가 더 투명해짐
- 늑골 간격 좁아짐

**정량 지표:** 좌/우 폐 면적 비율, 종격동 이동 방향/거리, 횡격막 높이 차이

**알고리즘:**
- U-Net 좌/우 폐 면적 계산 → 면적 비율 (정상은 좌:우 ≈ 0.85~0.95)
- 기관 중심선 vs 흉곽 중심 비교 → 종격동 이동 방향 + 거리
- 좌/우 횡격막 최저점 비교 → 높이 차이
- Rule: 폐 면적 감소 + 동측 종격동 이동 → atelectasis
- YOLOv8 bbox (VinDr-CXR에 Atelectasis bbox 있음)

**학습 데이터:** VinDr-CXR (Atelectasis bbox) + CheXmask (폐 세그멘테이션)

**프론트엔드 출력:** "우측 폐 면적 감소 15%, 종격동 우측 이동 1.2cm, 우측 횡격막 거상 → 우측 무기폐"

---

### 3-8. Fracture (골절)

**전문의 판독 기준:**
- 늑골 골절: 각 늑골을 하나씩 따라가며 피질(cortex) 불연속/단절 확인
  - 전위(displacement): 골절편이 어긋나면 명확. 비전위(non-displaced)는 놓치기 쉬움
  - 호발 부위: 제4~9늑골, 액와선(axillary line) 부근 (가장 약한 곳)
  - 전방 늑골/연골 부위: CXR에서 거의 안 보임 → CT 필요
- 쇄골 골절: 쇄골 중간 1/3이 가장 흔함. 전위, 각형성 확인
- 척추 압박 골절: 척추체 높이 감소 (>20%면 의미 있음), 쐐기형(wedge) 변형
- 견갑골 골절: 매우 드묾, 고에너지 외상 시 → 대혈관 손상 동반 가능 → 응급
- 동반 손상 필수 확인: 늑골 골절 → 기흉, 혈흉, 폐 좌상 동반 여부

**정량 지표:** 골절 위치 (몇 번째 늑골, 좌/우, 전방/후방/측방), 전위 여부, 동반 손상

**알고리즘:**
- YOLOv8 bbox → 골절 영역 탐지 (VinDr-CXR에 Rib fracture + Clavicle fracture bbox)
- 고해상도 입력 필수: 골절선은 1~2 픽셀 수준 → 512x512 이상 권장 (224x224에서는 불가)
- Bone Suppression 모델: 폐 실질과 뼈를 분리하면 골절선이 더 명확해짐 (선택)
- 늑골 번호 추정: 폐 세그멘테이션으로 횡격막 위치 파악 → bbox의 상대적 높이로 대략적 번호 추정
- 동반 손상 교차: 골절 탐지 + Pneumothorax Logic → "늑골 골절 + 기흉 동반" 자동 연계
- DenseNet-121은 보조 (전체 이미지에서 골절 가능성만 1차 스크리닝)

**한계:** CXR에서 늑골 골절 민감도 자체가 30~50%. 비전위 골절은 전문의도 놓침. CT가 gold standard.

**학습 데이터:** VinDr-CXR (Rib fracture 1,078건, Clavicle fracture bbox)

**프론트엔드 출력:** "우측 제7늑골 골절 의심 (YOLO conf 0.72)" + bbox + "동반 기흉 없음" + "CT 확인 권장"

---

### 3-9. Lung Lesion (폐 병변/결절)

**전문의 판독 기준:**
- 결절(nodule) < 3cm, 종괴(mass) >= 3cm — 크기가 가장 중요한 분류 기준
- 경계(margin) 분석:
  - 매끈하고 둥근(smooth, well-defined) → 양성 가능성 높음 (육아종, 과오종)
  - 불규칙/침상(irregular, spiculated) → 악성 의심 (폐암)
  - 분엽형(lobulated) → 중간 위험도
- 석회화(calcification) 패턴:
  - 중심부/층상/팝콘 석회화 → 양성 (결핵 후유증, 과오종)
  - 편심/무정형 석회화 → 악성 배제 불가
- 공동(cavitation): 내부가 비어있으면 → 결핵, 폐농양, 괴사성 종양
- 위치: 폐 첨부(결핵 호발), 쇄골 뒤/심장 뒤/횡격막 아래 (숨은 영역, 놓치기 쉬움)
- 이전 영상 비교: 크기 변화 추적 (doubling time) — 2년간 변화 없으면 양성 가능성
- Fleischner Society 가이드라인: 크기별 추적 관찰 주기 권장

**정량 지표:** 크기 (장경 cm), 위치 (폐엽), 경계 형태, 결절 vs 종괴, 개수 (단발/다발)

**알고리즘:**
- YOLOv8 bbox → 결절/종괴 탐지 (VinDr-CXR: Nodule/Mass bbox, 3,796건)
- bbox 장경(pixel→cm 환산)으로 결절 vs 종괴 자동 분류
  - pixel→cm 변환: metadata의 Rows/Columns + 알려진 해부학적 기준점 (척추체 높이 등)
- 폐엽 세그멘테이션과 매핑 → "우상엽 결절" 형태로 위치 특정
- 다발성 결절: bbox 개수로 단발 vs 다발 자동 분류
- 크기 기반 자동 추천:
  - < 6mm → 추적 불필요 (저위험)
  - 6~8mm → 6~12개월 CT 추적
  - > 8mm → 즉시 CT 또는 PET-CT 권장
  - >= 30mm → 종괴, 즉시 조직검사 권장
- DenseNet-121 Lung Lesion 확률은 1차 스크리닝, YOLO가 위치+크기 확정

**학습 데이터:** VinDr-CXR (Nodule/Mass 3,796건 bbox) + JSRT (결절 154장, 위치 어노테이션)

**프론트엔드 출력:** "우상엽 1.8cm 결절 (well-defined), Fleischner 가이드라인: 6~12개월 CT 추적 권장" + bbox + 크기 표시

---

### 3-10. Lung Opacity (폐 음영)

**전문의 판독 기준:**
Lung Opacity는 14개 중 가장 비특이적(non-specific)한 소견. "폐에 뭔가 뿌연 것이 있다"를 의미하며, 그 자체로는 진단이 아니라 **다른 질환의 영상적 표현**임. 전문의는 아래 5가지 특성을 보고 원인을 감별함:

- 위치: 어떤 폐엽에 있는지 (상/중/하, 좌/우)
- 형태:
  - 균일(homogeneous) → Consolidation, 대엽성 폐렴, 무기폐
  - 불균일(heterogeneous/patchy) → 기관지 폐렴, 폐출혈
  - 그물형(reticular) → 간질성 폐질환
  - 둥근(round/oval) → 결절, 종괴
- 경계: 명확(sharp) vs 불명확(ill-defined)
- 분포: 편측 vs 양측, 중심부 vs 주변부, 대칭 vs 비대칭
- 동반 소견: air bronchogram, 흉수, 심비대, 폐 용적 변화 등

**감별 로직 (핵심):**
- Opacity + Air bronchogram + 열 → Consolidation/Pneumonia
- Opacity + CTR > 0.5 + 양측 대칭 → Pulmonary Edema
- Opacity + 폐 면적 감소 + 동측 이동 → Atelectasis
- Opacity + 둥근 형태 + well-defined → Lung Lesion/Mass
- Opacity + 외상력 → 폐 좌상(Pulmonary Contusion)

**정량 지표:** 위치(폐엽), 형태 분류, 면적(%), 동반 소견 목록

**알고리즘:**
- DenseNet-121 Lung Opacity 확률 + YOLOv8 bbox (VinDr-CXR: Lung opacity 5,765건 bbox)
- bbox를 폐엽 세그멘테이션에 매핑 → 위치 특정
- **독립 Clinical Logic 없음** — 대신 "감별 진단 엔진(Differential Diagnosis Engine)"에서 처리:
  - 다른 질환의 Clinical Logic 결과를 종합하여 Lung Opacity의 원인을 자동 추론
  - Consolidation Logic의 Silhouette sign 결과, Edema Logic의 대칭성 결과, Atelectasis Logic의 폐 면적 결과를 입력으로 받음
- bbox 내부 texture 분석: 균일도(homogeneity score)로 형태 분류 (선택, 고난도)

**학습 데이터:** VinDr-CXR (Lung opacity 5,765건 bbox — 22개 label 중 가장 많음)

**프론트엔드 출력:** "좌하엽 음영 (면적 15%), 감별: Consolidation + Silhouette sign(+) → 경화로 판단" + bbox + 원인 감별 결과

---

### 3-11. No Finding (소견 없음)

**전문의 판독 기준:**
"정상"이라고 판독하는 것이 실제로는 가장 어려움. 체계적 접근법(systematic approach)으로 모든 영역을 확인한 후에야 "정상"이라고 할 수 있음:

- 기도(Airway): 기관 중심, 기관지 정상
- 종격동(Mediastinum): 종격동 너비 정상, 대동맥궁 정상, paratracheal stripe < 3mm
- 심장(Heart): CTR < 0.50, 심장 윤곽 정상
- 폐야(Lungs): 양측 폐야 투명, 음영 없음, 폐문(hilum) 대칭, 혈관 문양 정상
- 흉막(Pleura): 양측 CP angle 날카로움, 흉막선 없음, 흉막 비후 없음
- 횡격막(Diaphragm): 양측 횡격막 윤곽 선명, 높이 대칭 (우측이 좌측보다 약간 높은 것은 정상)
- 뼈(Bones): 늑골/쇄골/척추 정상, 골절선 없음
- 연조직(Soft tissue): 비정상 종괴 없음
- 의료기구: 없음 (또는 정상 위치)

**정량 지표:** 전체 체크리스트 통과 여부 (각 항목별 정상/비정상)

**알고리즘:**
- DenseNet-121: 14-label 확률이 **전부** 질환별 최적 threshold 이하
- YOLOv8: 탐지된 bbox가 0개
- Clinical Logic 전수 확인:
  - CTR < 0.50 ✓
  - CP angle 양측 정상 ✓
  - 종격동 너비 < 8cm ✓
  - 기관 중심선 ✓
  - 좌/우 폐 면적 비율 정상 (0.85~0.95) ✓
  - 횡격막 높이 차이 정상 ✓
- **3중 교차 검증 전부 정상일 때만** "No Finding" 확정
- 하나라도 비정상이면 → 해당 질환으로 분류 (No Finding 해제)

**중요:** CheXpert labeler에서 "hyperinflation" 같은 특정 키워드가 있으면 No Finding이 아님. 13개 질환에 해당하지 않더라도 "비정상"일 수 있음.

**프론트엔드 출력:** "전체 정상 — CTR 0.46, CP angle 양측 정상, 종격동 7.1cm, 기관 중심" + 전체 체크리스트 패널 (각 항목 초록색 ✓)

---

### 3-12. Pleural Other (기타 흉막 이상)

**전문의 판독 기준:**
Pleural Effusion과 Pneumothorax를 제외한 나머지 흉막 병변을 포괄하는 카테고리:

- 흉막 비후(Pleural Thickening):
  - 늑골 안쪽 면을 따라 얇은 줄(stripe) 음영 (정상은 보이지 않음)
  - 미만성(diffuse): 한쪽 흉막 전체가 두꺼워짐 → 석면 노출, 이전 감염(결핵), 이전 혈흉
  - 국소성(focal): 한 부분만 두꺼워짐 → 이전 감염 흔적, 종양 가능성
- 흉막 석회화(Pleural Calcification):
  - 석면 노출 이력: 양측 횡격막 표면 + 흉벽에 "holly leaf" 모양 석회화 판(plaque)
  - 이전 결핵: 편측, 불규칙, 시트(sheet) 모양 석회화
  - 이전 농흉/혈흉: 두꺼운 석회화 껍질
- 흉막 종괴/결절:
  - 불규칙 결절성 비후 + 종격동면 침범 → 악성 중피종(Mesothelioma) 의심
  - 전이성 흉막 종양: 다발성 결절
- Fibrothorax: 흉막이 매우 두꺼워져서 폐를 감싸는 "껍질" 형성

**정량 지표:** 비후 두께(mm), 위치(편측/양측), 석회화 유무, 결절성 여부

**알고리즘:**
- YOLOv8 bbox (VinDr-CXR: Pleural thickening bbox, 2,345건)
- DenseNet-121 Pleural Other 확률 (보조 — 양성 1.57%로 극히 낮음)
- 폐 세그멘테이션 마스크 경계 vs 흉벽 사이 간격 측정 → 비후 두께 추정
- Rule: 폐 마스크 외측 경계와 늑골 내면 사이에 연조직 밀도 영역 > 3mm → pleural thickening
- 석면 노출 이력(환자 정보에서) + 양측 석회화 → "석면 관련 흉막 병변" 자동 연계
- pos_weight 63.76 (가장 높은 불균형) → threshold를 낮게 설정하여 민감도 확보

**학습 데이터:** VinDr-CXR (Pleural thickening 2,345건 bbox)

**프론트엔드 출력:** "우측 흉막 비후 (두께 ~5mm, 하부 중심), 석회화 없음" + bbox + 흉막 영역 하이라이트

---

### 3-13. Pneumonia (폐렴)

**전문의 판독 기준:**
Pneumonia는 **임상 진단**이지 영상 진단이 아님. 같은 영상 소견(경화)이라도 임상 정보에 따라 폐렴/폐출혈/폐부종/폐암 등으로 달라짐. 이것이 14개 질환 중 AI가 가장 어려워하는 질환인 이유.

- 영상 소견 (단독으로는 진단 불가):
  - 대엽성 폐렴(Lobar): 한 폐엽 전체를 채우는 균일 경화 + air bronchogram
  - 기관지 폐렴(Bronchopneumonia): 여러 곳에 패치(patch) 형태로 산재된 음영
  - 간질성 폐렴(Interstitial): 양쪽 폐에 미만성 그물(reticular)/간유리(GGO) 패턴
  - 농양(Abscess): 경화 내부에 공동(cavity) + 액기면(air-fluid level)

- 임상 정보 (필수):
  - 체온 > 38°C (또는 < 36°C)
  - 기침 (특히 화농성 객담)
  - WBC > 11,000 또는 < 4,000
  - CRP 상승, Procalcitonin 상승
  - 호흡곤란, 흉통, 빈호흡(RR > 20)

- 감별 진단:
  - 경화 + 열 + WBC↑ → 세균성 폐렴
  - 간질 패턴 + 마른 기침 + 정상 WBC → 비정형 폐렴 (마이코플라즈마, 바이러스)
  - 경화 + CTR > 0.5 + 양측 대칭 → 폐부종 (폐렴 아님)
  - 경화 + 체중 감소 + 흡연력 → 폐암 후 폐색성 폐렴

**정량 지표:** 패턴 분류(대엽성/기관지/간질성), 위치(폐엽), 임상 상관관계 점수

**알고리즘 — 다른 질환과 근본적으로 다른 접근:**
- Pneumonia는 **영상 단독 판단을 하지 않음** — 반드시 임상 정보와 결합
- Step 1: Consolidation Clinical Logic 결과 가져오기 (경화 유무, 위치, Silhouette sign)
- Step 2: 오케스트레이터에서 전달된 환자 정보 파싱:
  - chief_complaint에서 "기침", "가래", "열" 키워드 추출
  - vitals에서 체온, RR 확인
- Step 3: 이전 검사 결과 반영:
  - 혈액검사 결과(WBC, CRP)가 있으면 → 강한 근거
  - 없으면 → "혈액검사 권장" 추천
- Step 4: 감별 진단 Rule:
  - Consolidation(+) + Temp > 38°C + "기침" in complaint → "감염성 폐렴 의심" (high)
  - Consolidation(+) + Temp 정상 + CTR > 0.5 → "심인성 폐부종 가능" (medium)
  - Consolidation(+) + 임상 정보 불충분 → "경화 확인, 폐렴 감별 위해 CBC/CRP 권장" (low)
- Step 5: Bedrock이 전체 맥락(영상+임상+이전검사)을 종합하여 최종 판단
- DenseNet-121 Pneumonia 확률은 **참고값일 뿐**, Clinical Logic의 감별 결과가 우선

**학습 데이터:** DenseNet-121은 MIMIC-CXR로 학습 (기존). 별도 학습 불필요 — Rule 기반.

**프론트엔드 출력:** "좌하엽 경화 확인. 체온 38.2°C + 기침 → 감염성 폐렴 의심. 확정 위해 CBC/CRP 결과 필요." + 경화 bbox + 감별 진단 패널

---

### 3-14. Support Devices (의료 기구)

**전문의 판독 기준:**
응급실/중환자실 환자에서 가장 먼저 확인하는 항목. 기구의 "존재 여부"보다 **"올바른 위치에 있는가"**가 핵심. 잘못된 위치는 즉시 보고 — 생명 위협 가능.

- ETT (Endotracheal Tube, 기관내관):
  - 정상 위치: 기관 분기부(carina) 3~5cm 위, 성대(vocal cord) 아래
  - 너무 깊으면: 우측 주기관지로 진입 → 좌폐 무기폐 + 우폐 과팽창 → 기흉 위험
  - 너무 얕으면: 성대 손상, 발관 위험
  - 고개 굴곡/신전에 따라 2cm까지 이동 가능
- CVC (Central Venous Catheter, 중심정맥관):
  - 정상 위치: 상대정맥(SVC) / SVC-우심방 접합부
  - 내경정맥(IJV) 경로: 우측에서 삽입, SVC로 내려감
  - 쇄골하정맥(Subclavian) 경로: 쇄골 아래로 진입
  - 합병증: 기흉 (삽입 시), 혈관 천공, 부정맥 (팁이 심장 안에 너무 깊이)
- NG/OG Tube (비위관/구위관):
  - 정상 위치: 식도를 따라 내려가 위장 내에 팁이 위치
  - 위험: 폐 내 삽입 (기관으로 잘못 들어감) → 흡인성 폐렴
  - 확인: 중심선을 따라 내려가다가 좌측으로 꺾이면 위장 (우측이면 의심)
- Chest Tube (흉관):
  - 기흉용: 폐 첨부(apex) 방향으로 향해야
  - 흉수용: 폐 기저부(base) 후방에 위치해야
  - 마지막 side hole이 흉막강 내에 있어야 (피하조직에 있으면 실패)
- Pacemaker / ICD:
  - 리드선 위치: 우심방(RA lead), 우심실(RV lead), 관상정맥동(CS lead, 양심실형)
  - 리드 이탈(dislodgement): 리드가 심실 밖으로 나온 것 → 페이싱 실패

**정량 지표:** 기구 유형, 팁 위치 (해부학적 랜드마크 기준 거리), 정상/비정상 판정

**알고리즘:**
- Step 1: 기구 탐지 — DenseNet-121이 Support Devices를 잘 탐지 (금속 구조물은 CNN이 쉽게 학습)
  - 높은 음영의 선형/곡선 구조물은 배경과 대비가 매우 커서 탐지 용이
- Step 2: 기구 유형 분류 — YOLOv8로 기구별 bbox + class 분류
  - ETT, CVC, NG tube, Chest tube, Pacemaker 각각 별도 클래스
  - 학습 데이터: Object-CXR 데이터셋 (10,000장, 기구 bbox) 또는 별도 어노테이션
- Step 3: 팁 위치 추출 — 각 기구의 팁(끝점) 좌표 자동 추출
  - 기구 bbox 내에서 가장 말단의 고음영 포인트 = 팁
- Step 4: 해부학적 랜드마크와 비교
  - Carina 위치: U-Net으로 기관 분기부 자동 탐지 (또는 폐 세그멘테이션에서 좌/우 폐 분기점)
  - ETT 팁~Carina 거리 계산 → Rule: 3~5cm이면 정상, < 3cm이면 "너무 깊음" 경고
  - CVC 팁 위치: 심장 세그멘테이션 상단(SVC 추정 영역)과 비교
- Step 5: 비정상 위치 경고
  - ETT in right bronchus → ALERT "우측 주기관지 삽입, 좌폐 무기폐 위험"
  - NG tube in lung → ALERT "폐 내 삽입 의심, 확인 필요"
  - Chest tube subcutaneous → "흉관 팁 피하조직 내 위치"

**학습 데이터:**
- DenseNet-121: MIMIC-CXR (기존, Support Devices 라벨)
- YOLOv8 기구 분류: Object-CXR (10,000장, Kaggle) 또는 VinDr-CXR 커스텀 어노테이션
- Carina 탐지: CheXmask 폐 세그멘테이션에서 간접 추출 가능

**프론트엔드 출력:**
```
[기구 위치 오버레이]
1. ETT — 팁 위치: carina 상방 4.2cm → 정상 ✓
2. CVC (우측 IJV) — 팁 위치: SVC → 정상 ✓
3. NG tube — 팁 위치: 위장 내 → 정상 ✓
```
+ 각 기구를 다른 색 bbox로 표시 + 팁에 점 마커 + 랜드마크(carina) 표시

---

## 4. 알고리즘별 모델 + 데이터셋 매핑 요약

### Layer 1: Segmentation 모델

| 대상 | 모델 | 데이터셋 | Dice | 비고 |
|------|------|---------|------|------|
| 폐 (좌/우) | U-Net + EfficientNet-B4 encoder | JSRT(247) + Montgomery(138) + CheXmask(676K) | 0.97+ | 가장 성숙한 영역 |
| 심장 | U-Net | JSRT(247) + CheXmask | 0.93+ | CTR 계산의 기반 |
| 뼈 (선택) | U-Net or Bone Suppression | 별도 학습 필요 | - | 골절 탐지 보조 |

**추천: CheXmask** (2024년 발표, 676K장 대규모, Scientific Data 논문)
- MIMIC-CXR, CheXpert, VinDr-CXR 등 10개 데이터셋의 폐+심장 마스크
- HybridGNet으로 생성된 마스크지만 품질 검증됨
- 우리 MIMIC-CXR 이미지에 대한 마스크가 이미 포함되어 있을 가능성 높음

### Layer 2: Detection 모델

| 모델 | 용도 | 데이터셋 | 비고 |
|------|------|---------|------|
| DenseNet-121 | 14-label 분류 (있다/없다) | MIMIC-CXR (94K PA) | 기존 유지 |
| YOLOv8 | 22개 질환 바운딩 박스 | VinDr-CXR (18K, 방사선과 17명 bbox) | 신규 추가 |

**VinDr-CXR이 핵심** — 22개 local label에 대해 방사선과 전문의 17명이 바운딩 박스를 그린 데이터셋
- Kaggle 대회 버전: kaggle.com/c/vinbigdata-chest-xray-abnormalities-detection
- PhysioNet 정식 버전: physionet.org/content/vindr-cxr/1.0.0/
- 우리 14개 질환 중 대부분이 커버됨:
  - Atelectasis, Cardiomegaly, Consolidation, Edema, Lung Opacity, Pleural Effusion, Pneumothorax, Nodule/Mass, Rib fracture, Clavicle fracture, Pleural thickening 등

### Layer 2 추가: Pneumothorax Segmentation

| 모델 | 데이터셋 | 비고 |
|------|---------|------|
| U-Net | SIIM-ACR Pneumothorax (12,047장, 픽셀 마스크) | Kaggle 공개, 기흉 전용 |

### Layer 3: Clinical Logic (코드 기반, 학습 불필요)

| 질환 | Rule | 입력 | 출력 | 구현 난이도 |
|------|------|------|------|------------|
| Cardiomegaly | CTR > 0.50 | Heart seg + Lung seg | CTR 수치 | 쉬움 |
| Pleural Effusion | CP angle 둔화 | Lung seg 하단 | 양, 좌/우 | 중간 |
| Pneumothorax | 폐 경계~흉벽 > 2cm | Lung seg + 흉벽 | 크기, tension | 중간 |
| Atelectasis | 폐 면적 감소 + 동측 이동 | Lung seg 양측 | 면적 비율, 방향 | 중상 |
| Consolidation | Silhouette sign | Heart/Diaphragm 경계 | 폐엽 위치 | 중상 |
| Edema | 양측 대칭 + butterfly | Lung seg + intensity | 패턴, 동반소견 | 중간 |
| Enlarged CM | 종격동 > 8cm | Lung seg 사이 공간 | 너비 | 중간 |
| Fracture | 고해상도 bbox + 늑골 번호 | YOLO bbox + 폐 seg 높이 | 위치, 동반손상 | 어려움 |
| Lung Lesion | bbox 크기 < 3cm / >= 3cm | YOLO bbox + 폐엽 seg | 크기, 위치, 추천 | 중간 |
| Lung Opacity | 감별 진단 엔진 (다른 Logic 종합) | 다른 질환 결과 전체 | 원인 감별 | 중상 |
| No Finding | 전체 체크리스트 통과 | 모든 Logic 결과 | 정상 확정 | 쉬움 |
| Pleural Other | 폐 마스크~흉벽 간격 > 3mm | Lung seg 외측 경계 | 비후 두께, 위치 | 중간 |
| Pneumonia | 경화 + 임상정보 종합 | Clinical Logic + 환자정보 | 감별 진단 | 중간 (Rule) |
| Support Devices | 팁~carina 거리 | YOLO 기구 bbox + carina | 위치 적절성 | 중상 |

---

## 5. 프론트엔드 표시 — 기존 vs 변경

### 기존 (Grad-CAM)
```
[원본 CXR] [뭉뚱그린 빨간 히트맵] [확률 숫자]
→ "Pneumonia 0.87" — 어디인지 모름, 근거 불명
```

### 변경 후 (Clinical Logic)
```
[원본 CXR + 해부학 오버레이]
├── 심장 윤곽선 (파란색) + CTR: 0.48
├── 폐 윤곽선 (초록색) + 좌/우 면적
├── 경화 영역 bbox (빨간색) + "좌하엽"
└── CP angle 표시 + "정상"

[소견 패널]
1. Consolidation — 좌하엽, Silhouette sign(+), 면적 12%
2. CTR 0.48 — 정상 (심인성 배제)
3. CP angle — 양측 정상 (흉수 없음)
4. 감별: 경화 + 체온 38.2°C + 기침 → 감염성 폐렴 의심

[신뢰도] DenseNet ✓ / YOLO ✓ / Clinical Logic ✓ — 3중 일치
```

---

## 6. 구현 우선순위 (MVP → Full)

### Phase 1 — MVP: 분류 + 세그멘테이션 기반 (2주 내)
1. DenseNet-121 전체 데이터 학습 (94,380장) — CSV 전처리 이미 완료
2. U-Net 폐+심장 세그멘테이션 (CheXmask 또는 JSRT)
3. CTR 자동 계산 — Cardiomegaly Clinical Logic (가장 쉬운 Rule)
4. 종격동 너비 자동 측정 — Enlarged Cardiomediastinum Logic (폐 seg 사이 공간)
5. 좌/우 폐 면적 비율 계산 — Atelectasis 기초 수치 (추후 Logic에서 사용)
6. 기관 중심선 추출 — Tension Pneumothorax, 종격동 이동 판단의 기반
7. 프론트엔드에 CTR 수치 + 심장/폐 윤곽 + 종격동 너비 표시

### Phase 2 — Detection: 병변 탐지 + 위치 특정 (1주)
8. YOLOv8 학습 (VinDr-CXR 18K, 22개 local label bbox)
9. 바운딩 박스를 폐엽 세그멘테이션에 매핑 (위치 자동 특정: "좌하엽", "우상엽" 등)
10. Lung Lesion: bbox 크기로 결절(<3cm) vs 종괴(>=3cm) 자동 분류 + Fleischner 추천
11. Fracture: bbox 위치 + 폐 seg 높이로 늑골 번호 대략 추정
12. Support Devices: 기구 유형별 bbox 분류 (ETT/CVC/NG tube/Chest tube/Pacemaker)
13. Pleural Other: bbox로 흉막 비후 영역 탐지
14. SIIM-ACR U-Net 학습 — Pneumothorax 픽셀 마스크 (12,047장)
15. 프론트엔드에 bbox + 폐엽 라벨 + 기구 위치 표시

### Phase 3a — Clinical Logic 핵심 7개 (1주)
16. Cardiomegaly: CTR > 0.50 판정 + 좌/우심실 방향 분석 (Phase 1에서 수치 완성)
17. Pleural Effusion: CP angle 곡률 분석 + 횡격막 선명도 + 양 추정 (소량/중등/대량)
18. Pneumothorax: 폐 경계~흉벽 거리 계산 + >2cm=Large + 종격동 편위=Tension 경고
19. Atelectasis: 폐 면적 감소 + 동측 종격동 이동 + 횡격막 거상 교차 확인
20. Consolidation: Silhouette sign 탐지 (심장/횡격막 경계 gradient → 소실 여부 → 폐엽 특정)
21. Edema: 양측 대칭성 분석 (좌/우 intensity histogram) + butterfly 패턴 + CTR 동반 교차
22. Enlarged Cardiomediastinum: 종격동 > 8cm 판정 + 기관 편위 확인 (Phase 1에서 수치 완성)

### Phase 3b — Clinical Logic 나머지 7개 (1주)
23. Fracture: 동반 손상 교차 탐지 (골절 bbox + Pneumothorax Logic → "늑골 골절 + 기흉 동반" 자동 연계)
24. Lung Lesion: Fleischner Society 가이드라인 자동 추천 엔진 (<6mm 추적불필요 / 6~8mm CT추적 / >8mm 즉시CT / >=30mm 조직검사)
25. Lung Opacity: 감별 진단 엔진 구현 (다른 질환 Logic 결과 종합 → Opacity 원인 자동 추론)
26. No Finding: 전체 8영역 체크리스트 (CTR + CP angle + 종격동 + 기관 + 폐 면적 + 횡격막 + YOLO bbox=0 + DenseNet 전부 threshold 이하)
27. Pleural Other: 폐 마스크 외측 경계~늑골 내면 간격 측정 → >3mm이면 비후 판정 + 석면 이력 교차
28. Pneumonia: 5단계 감별 알고리즘 (Consolidation Logic → 환자정보 파싱 → 이전 검사 반영 → 감별 Rule → 확률 산출)
29. Support Devices: 팁 위치 추출 + Carina 랜드마크 거리 계산 + 비정상 위치 ALERT (ETT 우기관지/NG tube 폐내 등)

### Phase 4 — Cross-Validation + 감별 진단 (1주)
30. 교차 검증 엔진: DenseNet 확률 vs YOLO bbox vs Clinical Logic 수치 → 3중 일치 확인
31. 불일치 처리: 일치=high, 2/3일치=medium, 불일치=low + "의사 확인 필요" 플래그
32. 감별 진단 로직: 동반 소견 조합 패턴 매칭
    - 경화 + CTR>0.5 + 양측 대칭 → 폐부종 (폐렴 아님)
    - 경화 + 열 + ECG 정상 → 감염성 폐렴
    - 골절 + 기흉 → 외상성 기흉
    - Opacity + 폐 면적 감소 → 무기폐 (폐렴 아님)
    - CTR>0.5 + 흉수 + 부종 → CHF
33. 위험도 자동 분류: Critical(긴장성 기흉, ETT 이탈) / Urgent(STEMI+경화) / Routine(소결절)

### Phase 5 — RAG + Bedrock + 통합 (1주)
34. PubMedBERT + FAISS RAG: MIMIC-IV Note 판독문 임베딩 → 유사 케이스 Top-3 검색
35. Bedrock 프롬프트 설계: 어노테이션 이미지 + 정량 수치 + RAG + 이전 검사 맥락 → JSON 소견
36. 이전 검사 결과 맥락 반영: ECG 정상 → "심인성 배제", 혈액검사 WBC↑ → "감염 확정"
37. 프론트엔드 통합: 해부학 오버레이 + bbox + 수치 패널 + 소견 패널 + 감별 패널 + 신뢰도
38. Grad-CAM 개발자 탭: 디버깅용으로만 숨김 처리

### Phase 6 — 테스트 + 평가 (1주)
39. MIMIC-IV Note 기반 테스트 케이스 3~5개 작성 (실제 환자 기록에서 추출)
40. 오케스트레이터 연동 테스트: ECG → 흉부 → 혈액검사 순차 호출
41. Clinical Logic 정확도 평가: CTR 자동 측정 vs 수동 측정 오차
42. 전체 파이프라인 E2E 테스트: 환자 도착 → 소견서 생성까지
43. AI 판단 vs 실제 의사 판단 비교 (MIMIC-IV Note의 최종 진단과 대조)

---

## 7. 모달 입출력 (v2 변경)

### 입력 (오케스트레이터 → 흉부 모달)
```json
{
  "patient_id": "p10000032",
  "request_id": "req_001",
  "modal": "chest_xray",
  "cxr_image_s3_path": "s3://bucket/image.jpg",
  "patient_info": {
    "age": 67, "sex": "M",
    "chief_complaint": "흉통, 호흡곤란, 기침",
    "vitals": {"HR": 110, "BP": "90/60", "SpO2": 88, "RR": 28, "Temp": 38.2}
  },
  "prior_results": [
    {"modal": "ecg", "summary": "정상 동성리듬, STEMI 아님", "timestamp": "..."}
  ]
}
```

### 출력 (흉부 모달 → 오케스트레이터)
```json
{
  "modal": "chest_xray",
  "timestamp": "2026-03-21T10:05:00",

  "anatomy_measurements": {
    "ctr": 0.48,
    "ctr_status": "normal",
    "heart_width_cm": 11.2,
    "thorax_width_cm": 23.3,
    "left_lung_area_ratio": 0.92,
    "mediastinum_width_cm": 7.1,
    "left_cp_angle": "normal",
    "right_cp_angle": "normal",
    "trachea_midline": true
  },

  "densenet_predictions": {
    "Pneumonia": 0.87, "Consolidation": 0.82, "Lung Opacity": 0.79,
    "Pleural Effusion": 0.15, "Cardiomegaly": 0.08, "...": "..."
  },

  "yolo_detections": [
    {"class": "Consolidation", "bbox": [120, 340, 320, 520], "confidence": 0.84, "lobe": "LLL"},
    {"class": "Lung Opacity", "bbox": [115, 330, 330, 530], "confidence": 0.76, "lobe": "LLL"}
  ],

  "clinical_logic_findings": [
    {
      "finding": "Consolidation",
      "location": "left_lower_lobe",
      "evidence": ["Silhouette sign: 좌측 횡격막 경계 소실", "DenseNet 0.82", "YOLO bbox LLL"],
      "quantitative": {"area_percent": 12.3}
    }
  ],

  "cross_validation": {
    "densenet_yolo_agreement": true,
    "densenet_clinical_agreement": true,
    "overall_confidence": "high"
  },

  "differential_diagnosis": [
    {
      "diagnosis": "감염성 폐렴",
      "probability": "high",
      "reasoning": "좌하엽 경화 + 체온 38.2°C + 기침 + ECG 정상(심인성 배제)"
    }
  ],

  "rag_evidence": [
    {"similar_case": "s12345678", "similarity": 0.91, "impression": "LLL pneumonia, recommend CBC/CRP"}
  ],

  "annotated_image_s3_path": "s3://bucket/annotated_req_001.jpg",

  "alert_flags": [],

  "recommendations": ["혈액검사 CBC/CRP/Blood Culture", "경험적 항생제 고려"],

  "suggested_next_actions": [
    {"action": "order_test", "modal": "lab", "tests": ["CBC", "CRP", "Blood Culture"]},
    {"action": "immediate_action", "description": "경험적 항생제 투여 고려"}
  ]
}
```

---

## 8. Grad-CAM 역할 재정의

Grad-CAM은 프론트엔드에서 완전히 제거하고, 다음 용도로만 사용:

1. **개발/디버깅:** DenseNet-121이 적절한 영역을 보고 판단하는지 검증
2. **모델 품질 관리:** 새 데이터로 재학습 후 히트맵이 해부학적으로 합리적인지 확인
3. **발표 자료:** "모델의 해석 가능성(explainability)을 검증했다"는 근거로 제시
   - "Grad-CAM으로 모델이 적절한 영역을 참조하는지 확인한 후,
     Clinical Logic Layer로 정량적 근거를 생성하도록 설계했다" → 차별점

---

## 9. 발표 시 기대 효과

| 항목 | 일반적인 팀 | 우리 팀 |
|------|-----------|--------|
| 질환 탐지 | DenseNet "있다/없다" | DenseNet + YOLOv8 "어디에 있다" |
| 위치 표시 | Grad-CAM 블롭 | 바운딩 박스 + 폐엽 매핑 |
| 심비대 판정 | "Cardiomegaly 0.72" | "CTR 0.54 (>0.50 → 심비대)" |
| 흉수 판정 | "Pleural Effusion 0.62" | "우측 CP angle 둔화, ~300mL" |
| 감별 진단 | 없음 | "경화 + 발열 + ECG정상 → 폐렴" |
| 신뢰도 | 확률 1개 | 3중 교차 검증 (DenseNet/YOLO/Logic) |
