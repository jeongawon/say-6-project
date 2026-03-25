---
name: architecture-v2-deprecated
description: v2 아키텍처 폐기. IAM 제약으로 Step Functions/Claim-Check 구현 실패. v2 AWS 리소스 전부 삭제. GitHub feature/MIMIC-CXR-v2에 코드 보존.
type: project
---

v2 아키텍처 고도화 시도 → **폐기** (2026-03-24).

**Why:** SKKU AWS Academy 환경에서 iam:CreateRole, states:*, lambda:InvokeFunction, s3:PutObject 모두 차단. Step Functions + Claim-Check 설계 구현 불가.

**How to apply:**
- v2 AWS 리소스: **전부 삭제 완료** (Lambda 3개, Step Functions, API Gateway, ECR 2개, ONNX 모델)
- v2 코드: GitHub `feature/MIMIC-CXR-v2` 브랜치에 보존 (75파일, 참조용)
- v1 코드: `feature/MIMIC-CXR` 브랜치 (정상 동작 중, 변경 없음)
- IAM 제약 목록: CONTEXT.md "IAM 제약" 섹션 참고
- v2 문제점 54개: `docs/v2-issues-and-lessons.md`
- Docker 빌드 필수: `--provenance=false --platform linux/amd64`
- Lambda 태그 필수: `project=pre-*team` (SKKU_TagEnforcementPolicy)
- CORS: Function URL에 위임, Lambda 코드에서 설정하면 중복됨
- S3 컨텍스트: `context/CONTEXT.md`, `context/record_daily.md` 최신화 완료
- v3 방향: Function URL 기반, S3 PutObject 불필요 설계, RAG Lambda 분리
