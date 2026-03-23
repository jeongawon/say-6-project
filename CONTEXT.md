# Dr. AI Radiologist — 작업 컨텍스트

> 마지막 업데이트: 2026-03-23
> S3 동기화: `aws s3 sync s3://pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an/context/ ./context/`

## 프로젝트 한 줄 요약
5명 팀, 응급실 AI 소견서 자동 생성. 나(박현우)는 흉부 X-Ray 모달 담당.

## 현재 상태
- 6개 Layer + Layer 2b 전부 Lambda 배포 완료
- 통합 파이프라인 배포 완료 (6-Layer E2E ~40초)
- Layer 2b (YOLOv8) 통합 연동 완료 (3-way 병렬)
- Layer 1 세그멘테이션 마스크 L/R 중심선 보정 완료
- YOLO bbox SVG 오버레이 추가 완료
- Gap Analysis v3: 98% Match Rate (48항목, Critical 0건)
- GitHub 팀 레포 feature/MIMIC-CXR 브랜치 생성 완료

## 엔드포인트
- Integrated: https://emsptg6o6iwonhhbxyxvasm7ga0yjluu.lambda-url.ap-northeast-2.on.aws/
- Layer 1: https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/
- Layer 2: https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/
- Layer 2b: https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/
- Layer 3: https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/
- Layer 5: https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/
- Layer 6: https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/

## AWS
- 계정: 666803869796, IAM: aws-say2-11
- S3: pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an
- 공유버킷 say1-pre-project-1~7: 읽기 전용!

## GitHub
- 팀 레포: https://github.com/jeongawon/say-6-project.git
- 내 브랜치: feature/MIMIC-CXR
- GitHub ID: still-dev

## 남은 작업
- [ ] 프로젝트 폴더 정리 후 feature 브랜치에 push
- [ ] 발표 자료 준비
- [ ] 오케스트레이터 팀 통합

## 상세 정보
- API 스펙: docs/API_REFERENCE.md 참고
- 폴더 구조: PROJECT_STRUCTURE.md 참고
- 일별 기록: docs/record_daily.md 참고
- 설계 vs 구현 Gap: docs/03-analysis/integrated-orchestrator.analysis.md 참고
