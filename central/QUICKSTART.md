# Quick Start Guide

## 🚀 5분 안에 시작하기

### 1. 레포지토리 클론

```bash
git clone <repository-url>
cd emergency-multimodal-orchestrator
```

### 2. 로컬 테스트 (배포 전 검증)

```bash
# 단위 테스트
python tests/local_test.py

# 전체 워크플로우 시뮬레이션
python tests/full_workflow_simulation.py
```

**예상 출력**:
```
✓ PASS: Chest Pain Patient
✓ PASS: Pneumonia Detection
✓ PASS: Low Confidence Handling
✓ PASS: Normal Findings
✓ PASS: Modal Connectors

Total: 5/5 tests passed
```

### 3. AWS 배포

```bash
# 배포 스크립트 실행
chmod +x deploy/scripts/deploy.sh
./deploy/scripts/deploy.sh
```

### 4. API 테스트

```bash
# 환경변수 설정
export API_ENDPOINT="<your-api-endpoint>"

# 테스트 요청
curl -X POST $API_ENDPOINT/case \
  -H "Content-Type: application/json" \
  -d @test_request.json
```

## 📋 체크리스트

### 배포 전
- [ ] AWS CLI 설정 완료 (`aws configure`)
- [ ] SAM CLI 설치 완료 (`sam --version`)
- [ ] Bedrock 접근 권한 확인
- [ ] 로컬 테스트 통과

### 배포 후
- [ ] API 엔드포인트 확인
- [ ] 테스트 요청 성공
- [ ] CloudWatch Logs 확인
- [ ] S3 버킷 생성 확인

### 모달 연동 (선택사항)
- [ ] CXR 서비스 배포
- [ ] CXR 엔드포인트 SSM 등록
- [ ] ECG 서비스 배포
- [ ] ECG 엔드포인트 SSM 등록

## 🎯 주요 엔드포인트

### POST /case
새 케이스 생성

**요청**:
```json
{
  "patient": {
    "age": 65,
    "sex": "Male",
    "chief_complaint": "chest pain",
    "vitals": {
      "BP": "145/92 mmHg",
      "HR": "88 bpm",
      "SpO2": "96%"
    }
  }
}
```

**응답**:
```json
{
  "case_id": "a1b2c3d4",
  "status": "processing",
  "message": "Case initiated. Use GET /case/{case_id} to check status."
}
```

### GET /case/{case_id}
케이스 결과 조회

**응답**:
```json
{
  "case_id": "a1b2c3d4",
  "status": "completed",
  "result": {
    "report": "...",
    "modalities_used": ["CXR", "ECG"],
    "risk_level": "high"
  }
}
```

## 🔧 문제 해결

### Lambda Timeout
```yaml
# template.yaml에서 Timeout 증가
Timeout: 120  # 기본 60초
```

### Bedrock 권한 오류
```bash
# IAM 정책 확인
aws iam list-attached-role-policies \
  --role-name <lambda-role-name>
```

### Modal 연결 실패
```bash
# SSM 파라미터 확인
aws ssm get-parameter --name /emergency-orchestrator/cxr-endpoint
```

## 📚 다음 단계

1. **모달 연동**: [MODAL_INTEGRATION_CXR_ECG.md](docs/MODAL_INTEGRATION_CXR_ECG.md)
2. **RAG 설정**: [RAG_SETUP.md](docs/RAG_SETUP.md)
3. **ML 업그레이드**: [UPGRADE_GUIDE.md](docs/UPGRADE_GUIDE.md)
4. **상세 배포**: [DEPLOYMENT.md](DEPLOYMENT.md)

## 💡 팁

- **로컬 테스트 먼저**: 배포 전 반드시 로컬 테스트 실행
- **Mock 모달 활용**: CXR/ECG 연동 전에도 전체 워크플로우 테스트 가능
- **CloudWatch 모니터링**: 배포 후 로그 확인 습관화
- **점진적 연동**: 한 번에 하나씩 모달 연동

## 🆘 도움말

- **이슈**: GitHub Issues
- **문서**: `docs/` 디렉토리
- **예제**: `tests/` 디렉토리
