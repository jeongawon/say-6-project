# blood_docker — 프로젝트 구조 및 작동 방식 설명

이 문서는 `blood_docker` 폴더의 전체 구조와 각 파일의 역할, 그리고 Docker 컨테이너가 어떻게 동작하는지를 처음 보는 사람도 이해할 수 있도록 설명합니다.

---

## 이 프로젝트가 하는 일

응급실 환자의 초기 혈액검사 수치(WBC, Hemoglobin, Creatinine 등)를 입력하면, XGBoost 머신러닝 모델이 **6시간 후 수치 악화 확률**을 예측해서 보여주는 웹 서비스입니다.

- 백엔드: Python FastAPI (예측 API 서버)
- 프론트엔드: HTML + nginx (화면 UI)
- 모델: XGBoost 5개 앙상블 (`.pkl` 파일로 저장됨)

---

## 폴더 구조

```
blood_docker/
├── docker-compose.yml        ← 두 컨테이너를 함께 실행하는 설정 파일
├── .dockerignore             ← Docker 이미지에 포함하지 않을 파일 목록
├── README.md                 ← 이 문서
│
├── backend/                  ← [컨테이너 1] FastAPI 예측 서버
│   ├── Dockerfile            ← backend 이미지 빌드 설정
│   ├── requirements.txt      ← Python 패키지 목록 (버전 고정)
│   ├── final_models.pkl      ← 학습된 XGBoost 모델 파일 (핵심)
│   └── app/
│       ├── __init__.py       ← Python 패키지 인식용 빈 파일
│       ├── main.py           ← FastAPI 앱 및 API 엔드포인트 정의
│       ├── model.py          ← 모델 로딩 및 예측 로직
│       └── schema.py         ← 입력/출력 데이터 형식 정의
│
└── frontend/                 ← [컨테이너 2] nginx 웹서버
    ├── Dockerfile            ← frontend 이미지 빌드 설정
    ├── nginx.conf            ← nginx 프록시 및 정적 파일 서빙 설정
    └── index.html            ← 사용자가 보는 화면 (HTML/CSS/JS)
```

---

## 전체 작동 흐름

```
사용자 브라우저
      │
      │  HTTP 요청 (포트 80)
      ▼
┌─────────────────────┐
│  frontend 컨테이너   │  ← nginx가 실행 중
│  (nginx:alpine)     │
│                     │
│  / → index.html     │  ← 화면 파일 직접 반환
│  /api/* → 프록시    │  ← API 요청은 backend로 전달
└────────┬────────────┘
         │
         │  내부 네트워크 (app-network)
         │  http://backend:8000/
         ▼
┌─────────────────────┐
│  backend 컨테이너    │  ← FastAPI + uvicorn이 실행 중
│  (python:3.11-slim) │
│                     │
│  POST /predict      │  ← 혈액검사 수치 받아서 예측
│  GET  /health       │  ← 서버 상태 확인
└────────┬────────────┘
         │
         │  pickle.load()
         ▼
   final_models.pkl
   (XGBoost 5개 모델)
```

**중요한 점**: backend 컨테이너는 외부 인터넷에 직접 노출되지 않습니다. 오직 frontend(nginx)를 통해서만 접근할 수 있어서 보안상 안전합니다. 외부에서 열려 있는 포트는 **80번 하나뿐**입니다.

---

## 각 파일 상세 설명

### docker-compose.yml

두 개의 컨테이너(backend, frontend)를 하나의 명령어로 함께 실행하고 관리하는 파일입니다.

```yaml
services:
  backend:
    build:
      context: ./backend      # backend/ 폴더 안의 Dockerfile을 사용해 이미지 빌드
    expose:
      - "8000"                # 포트 8000을 외부가 아닌 내부 컨테이너끼리만 공유
    healthcheck:              # 30초마다 /health 엔드포인트를 호출해 서버 상태 확인
      interval: 30s           # 확인 주기
      start_period: 20s       # 서버 시작 후 첫 체크까지 대기 시간 (모델 로딩 시간 고려)

  frontend:
    build:
      context: ./frontend
    ports:
      - "80:80"               # 외부 포트 80 → 컨테이너 포트 80 (유일한 외부 노출 포트)
    depends_on:
      backend:
        condition: service_healthy  # backend가 완전히 준비된 후에만 frontend 시작

networks:
  app-network:                # 두 컨테이너가 같은 가상 네트워크 안에 있어 서로 통신 가능
    driver: bridge
```

`depends_on: condition: service_healthy`의 의미: backend가 단순히 실행 중인 것을 넘어서, 모델 로딩까지 완료되어 실제로 요청을 처리할 수 있는 상태가 된 후에 frontend를 시작합니다.

---

### backend/Dockerfile

Python FastAPI 서버를 실행할 Docker 이미지를 만드는 설정 파일입니다.

```dockerfile
FROM python:3.11-slim
# python:3.11-slim을 베이스로 사용합니다.
# slim 버전은 불필요한 패키지가 제거된 가벼운 버전입니다. (약 130MB)

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
# gcc(C 컴파일러)를 설치합니다.
# XGBoost, numpy 등 일부 패키지는 설치 시 C 코드를 컴파일해야 합니다.
# 설치 후 apt 캐시를 삭제해 이미지 크기를 줄입니다.

WORKDIR /app
# 컨테이너 안의 작업 디렉토리를 /app으로 설정합니다.
# 이후 모든 COPY, CMD 명령은 이 경로 기준으로 동작합니다.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# requirements.txt를 소스코드보다 먼저 복사하고 패키지를 설치합니다.
# 이렇게 하면 소스코드만 변경됐을 때 패키지 재설치 없이 캐시를 재사용해
# 빌드 시간이 크게 단축됩니다.

COPY app/ ./app/
COPY final_models.pkl .
# 소스코드와 모델 파일을 컨테이너 안으로 복사합니다.
# 컨테이너 내부 경로: /app/app/, /app/final_models.pkl

EXPOSE 8000
# 이 컨테이너가 8000번 포트를 사용한다는 것을 문서화합니다.
# (실제 포트 개방은 docker-compose의 expose/ports 설정이 담당)

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
# Docker가 주기적으로 /health 엔드포인트를 호출해 서버 상태를 확인합니다.
# healthy 상태가 되어야 frontend 컨테이너가 시작됩니다.

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# 컨테이너 시작 시 실행할 명령어입니다.
# uvicorn: FastAPI를 실행하는 ASGI 서버
# --host 0.0.0.0: 컨테이너 외부에서 접근 가능하도록 모든 IP에서 수신
# --port 8000: 8000번 포트에서 대기
```

---

### backend/requirements.txt

컨테이너 안에 설치할 Python 패키지 목록입니다. 버전을 `==`으로 고정해서 언제 빌드해도 동일한 환경이 만들어지도록 합니다.

```
fastapi==0.135.1    # API 프레임워크. URL 라우팅, 요청/응답 처리를 담당
uvicorn==0.41.0     # FastAPI를 실행하는 ASGI 웹서버
pydantic==2.12.5    # 입력 데이터 유효성 검사 및 타입 변환
pandas==2.3.3       # 예측 입력값을 DataFrame으로 변환할 때 사용
numpy==1.26.4       # None 값을 NaN으로 변환하는 등 수치 처리
xgboost==3.2.0      # 실제 예측을 수행하는 머신러닝 모델 라이브러리
scikit-learn==1.8.0 # predict_proba() 등 XGBoost와 함께 사용되는 ML 유틸리티
```

---

### backend/app/main.py

FastAPI 앱의 진입점입니다. 서버 시작/종료 처리와 API 엔드포인트 3개를 정의합니다.

```python
models = {}  # 모델을 메모리에 보관하는 딕셔너리

@asynccontextmanager
async def lifespan(app):
    # 서버가 시작될 때 딱 1번 실행됩니다.
    # 요청이 들어올 때마다 모델을 로딩하면 매우 느리기 때문에
    # 서버 시작 시 미리 메모리에 올려두고 재사용합니다.
    models['final'] = load_models()   # final_models.pkl 로딩
    yield                             # 서버 실행 중 (요청 처리)
    models.clear()                    # 서버 종료 시 메모리 해제

# 엔드포인트 3개:
GET  /          → {"status": "ok"} 반환. 서버가 살아있는지 확인용
GET  /health    → 모델 로딩 여부까지 포함한 상세 상태 반환. Docker 헬스체크가 사용
POST /predict   → 혈액검사 수치(JSON)를 받아 예측 결과(JSON) 반환
```

---

### backend/app/model.py

모델 파일을 로딩하고 실제 예측을 수행하는 핵심 로직입니다.

```python
MODEL_PATH = Path(__file__).parent.parent / 'final_models.pkl'
# __file__ = /app/app/model.py
# .parent   = /app/app/
# .parent   = /app/
# 최종 경로 = /app/final_models.pkl

FEATURE_COLS = [
    'creatinine_0h', 'glucose_0h', 'hemoglobin_0h', 'lactate_0h',
    'platelet_0h', 'potassium_0h', 'sodium_0h', 'wbc_0h',
    'troponin_t_0h', 'bnp_0h',
    'has_lactate_0h', 'has_troponin_t_0h', 'has_bnp_0h'  # 측정 여부 플래그
]
# XGBoost 모델이 학습 시 사용한 13개 피처 컬럼입니다.
# 순서와 이름이 학습 때와 정확히 일치해야 합니다.

def build_features(input_values):
    # 선택 검사 3개(Lactate, Troponin T, BNP)는 측정 안 할 수도 있습니다.
    # 값이 있으면 1, 없으면 0으로 플래그를 추가합니다.
    # 모델이 "이 검사를 했는지 여부" 자체도 예측에 활용합니다.
    row['has_lactate_0h']    = 1 if lactate 입력됨 else 0
    row['has_troponin_t_0h'] = 1 if troponin 입력됨 else 0
    row['has_bnp_0h']        = 1 if bnp 입력됨 else 0
    # None → NaN 변환 후 13개 컬럼 순서에 맞게 DataFrame 생성

def predict(models, input_values):
    # 5개 모델(label별로 하나씩)을 각각 실행합니다.
    # predict_proba(X)[0][1] = 악화가 일어날 확률 (0.0 ~ 1.0)
    # 확률이 0.5 이상이면 warnings 목록에 추가합니다.
```

예측 대상 5가지:

| 모델 키 | 예측 내용 |
|---|---|
| `label_hb_down_6h` | Hemoglobin 감소 확률 |
| `label_creatinine_up_6h` | Creatinine 증가 확률 |
| `label_potassium_worse_6h` | Potassium 악화 확률 |
| `label_lactate_up_6h` | Lactate 증가 확률 |
| `label_troponin_up_6h` | Troponin T 상승 확률 |

---

### backend/app/schema.py

API의 입력과 출력 데이터 형식을 Pydantic으로 정의합니다. FastAPI는 이 정의를 기반으로 자동으로 데이터 유효성 검사와 API 문서를 생성합니다.

```python
class BloodTestInput(BaseModel):
    # 10개 혈액검사 수치. 모두 Optional이라 입력 안 해도 됩니다.
    # 입력하지 않으면 None으로 처리되고, 모델에서 NaN으로 변환됩니다.
    creatinine_0h:  Optional[float] = None   # 크레아티닌 (mg/dL)
    glucose_0h:     Optional[float] = None   # 혈당 (mg/dL)
    hemoglobin_0h:  Optional[float] = None   # 헤모글로빈 (g/dL)
    lactate_0h:     Optional[float] = None   # 젖산 (mmol/L)
    platelet_0h:    Optional[float] = None   # 혈소판 (K/uL)
    potassium_0h:   Optional[float] = None   # 포타슘 (mEq/L)
    sodium_0h:      Optional[float] = None   # 나트륨 (mEq/L)
    wbc_0h:         Optional[float] = None   # 백혈구 (K/uL)
    troponin_t_0h:  Optional[float] = None   # 트로포닌 T (ng/mL)
    bnp_0h:         Optional[float] = None   # BNP (pg/mL)

class PredictionResult(BaseModel):
    # 5개 예측 확률 (0.0 ~ 1.0)
    hemoglobin_down:  float
    creatinine_up:    float
    potassium_worse:  float
    lactate_up:       float
    troponin_up:      float
    # 0.5 이상인 항목의 한국어 이름 목록 (예: ["Hemoglobin 감소", "Lactate 증가"])
    warnings:         list[str]
    # Troponin T를 입력하지 않았을 때 표시할 안내 메시지
    troponin_note:    Optional[str] = None
```

---

### frontend/Dockerfile

nginx 웹서버 이미지를 만드는 설정 파일입니다.

```dockerfile
FROM nginx:1.27-alpine
# nginx:alpine은 약 40MB의 매우 가벼운 이미지입니다.
# 정적 파일 서빙과 프록시만 하면 되므로 Python 환경이 필요 없습니다.

RUN rm /etc/nginx/conf.d/default.conf
# nginx 기본 설정 파일을 삭제합니다.
# 기본 설정은 단순 정적 파일 서빙만 하므로 프록시 기능이 없습니다.

COPY nginx.conf /etc/nginx/conf.d/default.conf
# 커스텀 설정 파일로 교체합니다.
# /api/* 요청을 backend로 프록시하는 설정이 포함되어 있습니다.

COPY index.html /usr/share/nginx/html/index.html
# 프론트엔드 HTML 파일을 nginx가 서빙하는 기본 경로에 복사합니다.

CMD ["nginx", "-g", "daemon off;"]
# nginx를 포그라운드(foreground)로 실행합니다.
# Docker 컨테이너는 메인 프로세스가 종료되면 컨테이너도 종료됩니다.
# 기본적으로 nginx는 백그라운드(daemon)로 실행되어 메인 프로세스가 바로 끝나버리므로
# "daemon off" 옵션으로 포그라운드 실행을 강제합니다.
```

---

### frontend/nginx.conf

nginx의 동작 방식을 정의하는 핵심 설정 파일입니다.

```nginx
server {
    listen 80;       # 80번 포트에서 HTTP 요청 수신
    server_name _;   # 모든 도메인/IP에서 오는 요청 처리

    root /usr/share/nginx/html;   # 정적 파일의 루트 경로
    index index.html;

    # 규칙 1: 일반 페이지 요청 → index.html 반환
    location / {
        try_files $uri $uri/ /index.html;
        # 요청한 파일이 없으면 index.html을 반환합니다.
        # SPA(Single Page Application) 방식에서 필요한 설정입니다.
    }

    # 규칙 2: /api/ 로 시작하는 요청 → backend 컨테이너로 전달 (프록시)
    location /api/ {
        proxy_pass http://backend:8000/;
        # 'backend'는 docker-compose에서 정의한 서비스 이름입니다.
        # Docker 내부 DNS가 자동으로 backend 컨테이너의 IP로 변환해줍니다.
        # 예: /api/predict → http://backend:8000/predict

        proxy_set_header Host            $host;
        proxy_set_header X-Real-IP       $remote_addr;
        # 원래 클라이언트 IP를 backend에 전달합니다. (로깅 등에 활용)

        proxy_read_timeout 60s;          # 예측에 최대 60초 허용
        proxy_connect_timeout 10s;       # backend 연결 시도 최대 10초
    }

    # 규칙 3: /health → backend 헬스체크 엔드포인트로 전달
    location /health {
        proxy_pass http://backend:8000/health;
    }

    # 보안 헤더: 클릭재킹, MIME 스니핑, XSS 공격 방어
    add_header X-Frame-Options        "SAMEORIGIN"   always;
    add_header X-Content-Type-Options "nosniff"      always;
    add_header X-XSS-Protection       "1; mode=block" always;

    # gzip 압축: HTML, CSS, JS, JSON 응답을 압축해서 전송 속도 향상
    gzip on;
    gzip_types text/plain text/css application/javascript application/json;
    gzip_min_length 1024;   # 1KB 이상인 파일만 압축
}
```

---

### .dockerignore

Docker 이미지를 빌드할 때 포함하지 않을 파일/폴더를 지정합니다. `.gitignore`와 같은 개념입니다.

```
**/__pycache__     # Python 컴파일 캐시 (컨테이너 안에서 재생성됨)
**/*.pyc           # 컴파일된 Python 바이트코드
**/.DS_Store       # macOS 메타데이터 파일
**/*.ipynb         # Jupyter 노트북 (학습용, 서비스에 불필요)
**/*.csv           # 데이터 파일 (서비스에 불필요, 이미지 크기 절약)
**/.env            # 환경변수 파일 (보안상 이미지에 포함하면 안 됨)
```

이 파일이 없으면 불필요한 파일들이 이미지에 포함되어 이미지 크기가 커지고, 빌드 시간도 늘어납니다.

---

## 컨테이너 시작 순서

```
docker compose up --build 실행
         │
         ├─ backend 이미지 빌드 (python:3.11-slim + 패키지 설치)
         ├─ frontend 이미지 빌드 (nginx:alpine + 파일 복사)
         │
         ├─ backend 컨테이너 시작
         │       └─ uvicorn 실행 → FastAPI 앱 로딩 → final_models.pkl 로딩
         │       └─ /health 응답 가능 → healthcheck 통과 → "healthy" 상태
         │
         └─ frontend 컨테이너 시작 (backend가 healthy 상태가 된 후)
                 └─ nginx 실행 → 포트 80 수신 대기
                 └─ 서비스 준비 완료
```

---

## 로컬에서 실행하기

```bash
# 1. 이 폴더로 이동
cd blood_docker

# 2. 모델 파일 확인 (없으면 복사)
ls backend/final_models.pkl

# 3. 빌드 및 실행
docker compose up --build

# 4. 브라우저에서 접속
# http://localhost

# 5. 백그라운드 실행
docker compose up -d --build

# 6. 로그 확인
docker compose logs -f

# 7. 종료
docker compose down
```

---

## API 직접 테스트

서버가 실행 중일 때 터미널에서 직접 예측 API를 호출할 수 있습니다.

```bash
curl -X POST http://localhost/api/predict \
  -H "Content-Type: application/json" \
  -d '{
    "wbc_0h": 14.3,
    "hemoglobin_0h": 8.5,
    "platelet_0h": 95.0,
    "creatinine_0h": 2.1,
    "sodium_0h": 132.0,
    "potassium_0h": 5.2,
    "glucose_0h": 180.0,
    "lactate_0h": 3.8,
    "troponin_t_0h": 0.08,
    "bnp_0h": null
  }'
```

응답 예시:

```json
{
  "hemoglobin_down": 0.7231,
  "creatinine_up": 0.8814,
  "potassium_worse": 0.4102,
  "lactate_up": 0.6543,
  "troponin_up": 0.3201,
  "warnings": ["Hemoglobin 감소", "Creatinine 증가", "Lactate 증가"],
  "troponin_note": null
}
```

---

## AWS 배포 방법

### EC2 단일 서버 (간단)

```bash
# EC2에 코드 업로드
scp -r -i your-key.pem blood_docker/ ec2-user@<EC2_IP>:~/

# EC2 접속 후
ssh -i your-key.pem ec2-user@<EC2_IP>

# Docker 설치 (Amazon Linux 2023)
sudo yum install -y docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

# docker compose 설치
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 재접속 후 실행
exit && ssh -i your-key.pem ec2-user@<EC2_IP>
cd blood_docker
docker-compose up -d --build
```

EC2 보안 그룹에서 포트 80 인바운드를 허용해야 외부에서 접속 가능합니다.

### ECR + ECS (확장성 필요 시)

```bash
REGION=ap-northeast-2
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

# ECR 리포지토리 생성
aws ecr create-repository --repository-name blood5-backend  --region $REGION
aws ecr create-repository --repository-name blood5-frontend --region $REGION

# ECR 로그인
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

# 빌드 & 태그 & 푸시
docker build -t blood5-backend  ./backend
docker build -t blood5-frontend ./frontend

docker tag blood5-backend  $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/blood5-backend:latest
docker tag blood5-frontend $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/blood5-frontend:latest

docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/blood5-backend:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/blood5-frontend:latest
```
