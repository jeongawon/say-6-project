# v2 구현 과정 문제점 및 개선 기록

> 작성일: 2026-03-24
> 프로젝트: Dr. AI Radiologist v2 아키텍처 고도화
> 결론: **설계와 실제 배포 환경의 괴리로 인해 3번의 아키텍처 전환 발생**

---

## 1. 아키텍처 전환 이력

| 단계 | 설계 | 실제 | 전환 이유 |
|------|------|------|----------|
| **1차 설계** | API Gateway → Step Functions (Express, 동기) | 불가 | API GW 29초 타임아웃 |
| **2차 설계** | API Gateway → Step Functions (비동기 폴링) | 불가 | `states:StartExecution` 권한 없음 |
| **3차 설계** | Gateway Lambda → Lambda A/B (boto3 invoke) | 불가 | `lambda:InvokeFunction` 권한 없음 |
| **최종 구현** | Gateway Lambda → Lambda A/B (HTTP Function URL) | **동작** | IAM 권한 불필요 |

**교훈: 설계 전에 IAM 권한을 반드시 먼저 확인해야 한다.**

---

## 2. IAM 권한 문제 (가장 큰 블로커)

교육 환경(SKKU AWS Academy)에서 `aws-say2-11` 사용자의 IAM 제약:

| 권한 | 상태 | 영향 |
|------|:----:|------|
| `iam:CreateRole` | **차단** | 새 IAM 역할 생성 불가 → 기존 `say-2-lambda-bedrock-role` 강제 사용 |
| `iam:PutRolePolicy` | **차단** | 인라인 정책 추가 불가 → 역할에 권한 추가 불가 |
| `iam:AttachRolePolicy` | **차단** | 관리형 정책 연결 불가 |
| `iam:GetRole` (일부) | **차단** | 일부 역할 정책 확인 불가 |
| `s3:PutObject` | **차단** (Lambda 역할) | Claim-Check 패턴 사용 불가, 이미지 S3 저장 불가 |
| `states:StartExecution` | **차단** | Step Functions 호출 불가 |
| `states:DescribeExecution` | **차단** | Step Functions 상태 조회 불가 |
| `lambda:InvokeFunction` | **차단** (Lambda 역할) | Lambda→Lambda boto3 호출 불가 |

### `say-2-lambda-bedrock-role`이 가진 권한

| 권한 | 상태 |
|------|:----:|
| `s3:GetObject` | **있음** — 모델 다운로드 가능 |
| `bedrock:InvokeModel` | **있음** — 소견서 생성 가능 |
| `logs:*` | **있음** — CloudWatch 로깅 |
| `s3:PutObject` | **없음** |
| `states:*` | **없음** |
| `lambda:InvokeFunction` | **없음** |

### 개선 방법
- **Lambda Function URL (HTTP 호출)** 로 우회: IAM 권한 없이 Lambda 간 통신 가능
- **인메모리 데이터 전달**: S3 Claim-Check 대신 HTTP 본문으로 결과 직접 전달

---

## 3. SKKU_TagEnforcementPolicy 문제

Lambda 생성 시 태그 정책에 의한 차단:

```
explicit deny in identity-based policy: arn:aws:iam::666803869796:policy/SKKU_TagEnforcementPolicy
```

### 정책 내용

```json
{
  "Condition": {
    "StringNotLike": {
      "aws:RequestTag/project": "pre-*team"
    }
  }
}
```

### 해결 과정

| 시도 | 태그 | 결과 |
|------|------|------|
| v1 방식 복사 | `name=say2-preproject-6team-hyunwoo` | **실패** — 정책은 `project` 키 요구 |
| `project` 키 | `project=say2-preproject-6team` | **실패** — 값 패턴 불일치 |
| 정책 문서 확인 | `project=pre-6team` | **성공** — `pre-*team` 패턴 매칭 |

### 교훈
- v1은 정책 생성(2025-07) 이전에 배포되어 태그 없이 가능했음
- 정책 문서를 `aws iam get-policy-version`으로 직접 확인해야 정확

---

## 4. Docker 빌드 문제

### 4.1 이미지 매니페스트 오류

```
The image manifest, config or layer media type for the source image is not supported
```

- **원인**: Mac M4 (ARM)에서 Docker 빌드 시 attestation manifest 포함
- **해결**: `--provenance=false` 플래그 추가

### 4.2 플랫폼 불일치

- **원인**: ARM 이미지를 Lambda에 배포 (faiss-cpu ARM 버전 없음)
- **해결**: `--platform linux/amd64` 플래그 추가
- **참고**: v1 DEPLOY_GUIDE.md에 이미 팁으로 기록되어 있었음

```bash
# 정확한 빌드 명령
docker build --provenance=false --platform linux/amd64 -t <tag> .
```

### 4.3 faiss-cpu 버전

```
ERROR: Could not find a version that satisfies the requirement faiss-cpu==1.7.4
```

- **원인**: 1.7.4는 amd64 Python 3.12에서 미지원
- **해결**: `faiss-cpu>=1.8.0`으로 변경

---

## 5. ONNX 모델 변환 문제

### 5.1 UNet (세그멘테이션)

| 문제 | 해결 |
|------|------|
| `transformers` 버전 호환성 (`all_tied_weights_keys` 에러) | `AutoModel.from_pretrained` 대신 수동 모듈 로드 |
| `albumentations`, `timm` 미설치 | `pip install albumentations timm` |
| ONNX output name 충돌 (`view` 중복) | output names를 `seg_mask`, `view_pred`, `age_pred`, `female_pred`로 변경 |
| opset 17 변환 실패 | opset 18 사용 |
| 외부 데이터 파일 (`unet.onnx.data`) S3 미업로드 | `.onnx.data` 파일도 S3에 업로드 + `model_loader.py`에 다운로드 로직 추가 |

### 5.2 DenseNet

| 문제 | 해결 |
|------|------|
| `onnxscript` 미설치 | `pip install onnxscript` |
| 외부 데이터 파일 (`densenet.onnx.data`) | S3에 함께 업로드 |

### 5.3 YOLOv8

| 문제 | 해결 |
|------|------|
| `onnxslim` 미설치 (경고, 무시 가능) | simplify 없이 export 성공 |
| export 시 `imgsz=1024` 사용 | `inference_yolo.py`의 `INPUT_SIZE`도 640→1024로 변경 |

---

## 6. Lambda 추론 코드 문제

### 6.1 입력 차원 불일치

```
Got invalid dimensions for input: image
  index: 1 Got: 3 Expected: 1
  index: 2 Got: 512 Expected: 320
```

| 항목 | 코드 (잘못) | 모델 (정확) | 수정 |
|------|------------|------------|------|
| UNet 채널 | 3 (RGB) | **1 (Grayscale)** | `pil_image.convert("L")` |
| UNet 크기 | 512×512 | **320×320** | `INPUT_SIZE = (320, 320)` |
| UNet 정규화 | [0, 1] | **[0, 255] (모델 내부 정규화)** | 0-255 그대로 전달 |

### 6.2 Function URL 이벤트 형식

Lambda A/B가 Step Functions 이벤트 형식만 지원 → Function URL은 `body` 필드에 JSON string으로 전달

```python
# 추가된 코드
if "body" in event and isinstance(event.get("body"), str):
    event = json.loads(event["body"])
```

### 6.3 Lambda 응답 크기 제한 (6MB)

- **원인**: Preprocess가 원본 X-Ray(1.9MB JPEG)를 PNG base64로 반환 시 6MB 초과
- **해결**: 이미지 1024px 리사이즈 + JPEG quality=85 재인코딩

### 6.4 Lambda B의 `statusCode` 필드 문제

```python
# 잘못 — Function URL이 statusCode를 HTTP 상태로 해석, body 비어짐
return {"statusCode": 200, "run_id": ..., "report": ...}

# 수정 — statusCode 대신 status 사용
return {"status": "ok", "run_id": ..., "report": ...}
```

---

## 7. CORS 문제

### 7.1 CORS 헤더 중복 (최종 블로커)

```
access-control-allow-origin: *                    ← Gateway Lambda 코드
access-control-allow-origin: http://localhost:8080  ← Function URL 자동
```

- **증상**: curl로 성공, 브라우저에서 CORS 에러
- **원인**: Function URL이 자동으로 CORS 헤더 추가 + Lambda 코드도 추가 → 중복
- **해결**: Gateway Lambda에서 CORS 헤더 제거 (Function URL에 위임)
- **진단 시간**: 이 문제 하나에 가장 오래 걸림 (curl 성공 = 백엔드 정상이라 의심 못함)

### 7.2 `file://` 프로토콜

- 로컬 HTML 파일을 `file://`로 열면 CORS 동작이 달라짐
- **해결**: `python3 -m http.server 8080`으로 로컬 HTTP 서버 사용

---

## 8. Lambda B 성능 문제

### 8.1 콜드 스타트 60초+

| 원인 | 시간 | 해결 |
|------|------|------|
| FastEmbed 모델 HuggingFace 다운로드 | ~40초 | Dockerfile에서 사전 다운로드 (`RUN python -c "from fastembed import TextEmbedding; ..."`) |
| FAISS 인덱스 S3 다운로드 (183MB) | ~10초 | warm 상태 유지 (Lambda 컨테이너 재사용) |
| 메타데이터 S3 다운로드 (176MB) | ~10초 | 동일 |
| fastembed read-only filesystem | 즉시 실패 | `ENV FASTEMBED_CACHE_PATH=/var/task/fastembed_cache` |

### 8.2 v1과의 차이

v1은 Layer 5 (RAG)가 **별도 Lambda**로 30초 타임아웃 내 동작했음:
- Dockerfile에서 FastEmbed 사전 다운로드
- 독립 컨테이너라 콜드 스타트가 해당 Lambda만 영향

v2는 Lambda B에 Clinical Logic + RAG + Bedrock을 **통합**해서 더 무거움.

---

## 9. 설계했지만 사용하지 않는 것들

| 구성 요소 | 설계 문서 | 구현 여부 | 배포 여부 | 사용 여부 |
|----------|----------|:---------:|:---------:|:---------:|
| Step Functions 상태 머신 | Plan/Design | state_machine.json 작성 | **배포됨** | **미사용** |
| API Gateway REST API | Plan/Design | setup-api-gw.sh 작성 | **배포됨** | **미사용** |
| 비동기 폴링 패턴 (GET /status) | Design | 프론트 코드 포함 | API GW에 설정 | **미사용** |
| Claim-Check 패턴 (S3 저장) | Design | result_store.py 작성 | Lambda에 포함 | **미사용** |
| shared/result_store.py | Design | 코드 존재 | Docker에 COPY | **미사용** |
| shared/config.py | Design | 코드 존재 | Docker에 COPY | **일부 사용** (S3_BUCKET만) |
| deploy.sh (bash 스크립트) | Plan | 작성 완료 | 미실행 | **미사용** (deploy_v2.py로 대체) |

---

## 10. 최종 아키텍처 vs 원래 설계

### 원래 설계 (Step Functions + Claim-Check)

```
[Browser] → [API Gateway] → [Step Functions EXPRESS]
                                ├→ [Lambda A preprocess] → S3 저장
                                ├→ [Lambda A seg/densenet/yolo 병렬] → S3 저장
                                └→ [Lambda B] → S3 읽기 → S3 저장
                             → [API Gateway 응답]
```

### 최종 구현 (Lambda Direct HTTP)

```
[Browser] → [Gateway Lambda Function URL]
                ├→ S3에서 이미지 읽기 (s3_key 지원)
                ├→ [Lambda A Function URL] × 1 (preprocess)
                ├→ [Lambda A Function URL] × 3 (seg/densenet/yolo 병렬, ThreadPool)
                └→ [Lambda B Function URL] × 1 (clinical + RAG + bedrock)
             → [Browser 직접 응답]
```

### 차이점 요약

| 항목 | 원래 설계 | 최종 구현 |
|------|----------|----------|
| 오케스트레이션 | Step Functions | Gateway Lambda (ThreadPoolExecutor) |
| Lambda 간 통신 | Claim-Check (S3 URI) | HTTP Function URL (인메모리) |
| 데이터 저장 | S3 runs/{run_id}/ | 없음 (인메모리만) |
| API 진입점 | API Gateway REST | Lambda Function URL |
| 타임아웃 관리 | Step Functions 5분 | Gateway Lambda 300초 |
| CORS | API Gateway Mock | Function URL 자동 |
| 비용 | Lambda + S3 + Step Functions + API GW | Lambda만 |

---

## 11. 다음 버전(v3) 개선 권장사항

1. **IAM 권한 사전 확인**: 설계 전에 `iam:GetPolicy`, `sts:GetCallerIdentity`로 가용 권한 파악
2. **Step Functions 불필요**: Lambda Function URL + ThreadPool이 더 단순하고 비용 효율적
3. **Claim-Check 불필요**: 인메모리 전달이 30초 이내 가능 (이미지 리사이즈 전제)
4. **Lambda B 분리 고려**: RAG를 별도 Lambda로 분리하면 콜드 스타트 영향 최소화
5. **FastEmbed Dockerfile 사전 다운로드 필수**: v1에서 이미 적용된 패턴
6. **ONNX 외부 데이터 파일**: `.onnx.data` 파일 항상 함께 관리
7. **CORS는 Function URL에 위임**: Lambda 코드에서 CORS 헤더 직접 설정하지 말 것
