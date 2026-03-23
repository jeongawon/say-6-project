# Layer 1 Segmentation 배포 계획

> **Summary**: Layer 1 세그멘테이션 모델을 Lambda 엔드포인트로 배포하고, 테스트 웹페이지를 CloudFront로 호스팅
>
> **Project**: Dr. AI Radiologist (MIMIC-CXR)
> **Author**: hyunwoo
> **Date**: 2026-03-22
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | Layer 1 모델(HF 사전학습)은 SageMaker에서만 테스트 가능. 팀원/교수 공유 불가, 프론트엔드 연동 불가 |
| **Solution** | 레이어별 Lambda 엔드포인트 + CloudFront 테스트 페이지. 각 레이어 독립 배포 → 최종 오케스트레이터 통합 |
| **Function/UX Effect** | 브라우저에서 샘플 CXR 클릭 → 세그멘테이션 마스크 + CTR 즉시 확인. 실시간 데모 가능 |
| **Core Value** | 레이어별 독립 배포/테스트 체계 확립. Layer 2~6 완성 시 동일 패턴으로 확장 |

---

## 1. 현재 상태

### 1.1 완료된 것
- [x] Layer 1 모델: `ianpan/chest-x-ray-basic` (HF 사전학습, Dice 0.95+)
- [x] 모델 S3 저장: `s3://work-bucket/models/segmentation/chest-x-ray-basic/`
- [x] 추론 코드: `layer1_segmentation/segmentation_model.py`
- [x] SageMaker에서 추론 테스트 성공 (CTR 0.6007, View: PA, Age: 57.3)
- [x] 샘플 이미지 3장 S3 업로드: `s3://work-bucket/web/test-layer1/samples/`
- [x] 테스트 웹페이지 HTML 작성: `deploy/test_page/index.html`
- [x] Lambda 핸들러 코드 작성: `deploy/layer1_segmentation/lambda_function.py`

### 1.2 아직 안 된 것
- [ ] Lambda 함수 배포 (Docker 컨테이너 이미지 필요)
- [ ] Lambda Function URL 생성
- [ ] 테스트 페이지 S3 업로드 + CloudFront 배포
- [ ] 엔드-투-엔드 테스트

### 1.3 환경 제약
| 환경 | 가능한 것 | 불가능한 것 |
|------|-----------|-------------|
| **로컬 CLI** (`aws-say2-11`) | Lambda, ECR, S3, CloudFront, IAM 조회 | SageMaker, Docker 빌드 |
| **SageMaker Studio** | S3, SageMaker 학습/추론 | Docker, Lambda, ECR, CloudFront |

**핵심 문제**: Docker 이미지를 빌드할 환경이 없음
- 로컬: Docker 미설치
- SageMaker Studio: Docker daemon 없음

---

## 2. 아키텍처

### 2.1 레이어별 Lambda 엔드포인트

```
[CloudFront] ← S3 정적 웹페이지 (테스트 UI)
     │
     ▼
[Lambda Function URL] ← 각 레이어별 독립 엔드포인트
     │
     ├── /layer1-segmentation  ← 지금 배포
     ├── /layer2-densenet      ← DenseNet 학습 완료 후
     ├── /layer2-yolo          ← 나중에
     ├── /layer3-clinical      ← 나중에
     └── /orchestrator         ← 최종 통합 (handler.py)
```

### 2.2 Layer 1 Lambda 구성
- **런타임**: Container Image (PyTorch + transformers 필요)
- **메모리**: 3008 MB
- **타임아웃**: 120초
- **Ephemeral Storage**: 2048 MB (/tmp에 모델 캐시)
- **Cold Start 흐름**: S3에서 모델 다운로드 → /tmp 캐시 → 추론
- **Warm Start**: /tmp 캐시 사용 (즉시 추론)

---

## 3. Docker 빌드 문제 해결 방안

### 옵션 비교

| 방안 | 장점 | 단점 | 난이도 |
|------|------|------|--------|
| **A. AWS CodeBuild** | 클라우드에서 빌드, 로컬 Docker 불필요 | CodeBuild 프로젝트 설정 필요 | 중 |
| **B. EC2에서 빌드** | 간단, Docker 사용 가능 | EC2 비용, 수동 설정 | 중 |
| **C. 로컬 Docker Desktop 설치** | 가장 직접적 | Windows Docker 설치 필요 | 하 |
| **D. ONNX 변환 + zip 배포** | Docker 불필요, cold start 빠름 | 모델 변환 작업, trust_remote_code 호환 이슈 | 상 |

### 선택: A. AWS CodeBuild

**이유**:
- 로컬 환경 변경 불필요 (Docker 설치 X)
- AWS CLI로 모든 것 제어 가능 (로컬 IAM 권한 내)
- 한 번 설정하면 Layer 2, 3 등 추가 시 재사용
- 비용: 프리티어 100분/월 무료

### CodeBuild 플로우
```
1. buildspec.yml + Dockerfile → S3 업로드
2. aws codebuild create-project (ECR 푸시 권한)
3. aws codebuild start-build
4. CodeBuild가 Docker 빌드 → ECR 푸시
5. aws lambda create-function --image-uri (ECR 이미지)
6. aws lambda create-function-url-config
7. 테스트 페이지 S3 업로드 + CloudFront 배포
```

---

## 4. 구현 순서

### Phase 1: 인프라 준비 (AWS CLI, 로컬에서 실행)
1. ECR 리포지토리 생성
2. CodeBuild 프로젝트 생성 (buildspec.yml)
3. S3에 빌드 소스 업로드

### Phase 2: Docker 빌드 + Lambda 배포 (CodeBuild + AWS CLI)
4. CodeBuild 빌드 실행 → ECR에 이미지 푸시
5. Lambda 함수 생성 (ECR 이미지)
6. Lambda Function URL 생성 + CORS 설정

### Phase 3: 테스트 페이지 배포 (AWS CLI)
7. S3에 index.html + 샘플 이미지 업로드
8. S3 정적 웹호스팅 설정
9. CloudFront 배포 생성

### Phase 4: 검증
10. CloudFront URL로 접속
11. 샘플 이미지 클릭 → Lambda 호출 → 결과 확인
12. Cold start / Warm start 성능 측정

---

## 5. 필요 파일 목록

| 파일 | 위치 | 상태 | 용도 |
|------|------|------|------|
| `lambda_function.py` | `deploy/layer1_segmentation/` | ✅ 완료 | Lambda 핸들러 |
| `Dockerfile` | `deploy/layer1_segmentation/` | ✅ 완료 | 컨테이너 이미지 |
| `buildspec.yml` | `deploy/layer1_segmentation/` | ❌ 미작성 | CodeBuild 빌드 정의 |
| `index.html` | `deploy/test_page/` | ✅ 완료 | 테스트 웹페이지 |
| `setup_layer1_test.py` | 루트 | ✅ 완료 | 모델 S3 저장 + 샘플 준비 |
| `deploy_layer1.sh` | `deploy/` | ❌ 미작성 | AWS CLI 배포 스크립트 |

---

## 6. 비용 예측

| 서비스 | 예상 비용 | 비고 |
|--------|-----------|------|
| ECR | ~$0.20/월 | 이미지 저장 (~2GB) |
| Lambda | $0 | 프리티어 100만 요청 |
| CodeBuild | $0 | 프리티어 100분/월 |
| CloudFront | $0 | 프리티어 1TB/월 |
| S3 | $0 | 프리티어 5GB |
| **합계** | **~$0.20/월** | |

---

## 7. 리스크

| Risk | Impact | Mitigation |
|------|--------|------------|
| CodeBuild IAM 권한 부족 | 빌드 실패 | 교육계정 IAM 정책 확인, 필요시 관리자 요청 |
| Lambda 컨테이너 cold start 느림 (~15초) | UX 저하 | 첫 요청 후 warm 유지, Provisioned Concurrency 검토 |
| trust_remote_code 모델 Lambda 호환 | 추론 실패 | SageMaker에서 이미 검증됨, 동일 Python/패키지 버전 사용 |
| S3 퍼블릭 액세스 차단 | CloudFront 접근 불가 | OAC 설정으로 CloudFront만 허용 |

---

## 8. 향후 확장

Layer 2~6 완성 시 동일 패턴 적용:
1. `deploy/layer{N}_{name}/lambda_function.py` + `Dockerfile` 작성
2. CodeBuild로 ECR 푸시
3. Lambda 생성 + Function URL
4. 테스트 페이지에 탭 추가
5. 최종: `handler.py` 오케스트레이터가 각 Lambda Function URL 순차 호출

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-22 | Initial draft — Lambda + CloudFront 배포 계획 | hyunwoo |
