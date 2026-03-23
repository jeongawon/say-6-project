"""통합 오케스트레이터 설정"""
import os

# === 기존 Layer 엔드포인트 (절대 수정 금지) ===
LAYER1_URL = os.environ.get("LAYER1_URL",
    "https://jwhljyevn3hm44nhvs5zcdstmi0tmuvi.lambda-url.ap-northeast-2.on.aws/")
LAYER2_URL = os.environ.get("LAYER2_URL",
    "https://pk67s3qrp3b3xluqkcp6neqly40kduol.lambda-url.ap-northeast-2.on.aws/")
LAYER2B_URL = os.environ.get("LAYER2B_URL",
    "https://yoaval7laoc4ngnkr7uod7dufm0nmxib.lambda-url.ap-northeast-2.on.aws/")
LAYER3_URL = os.environ.get("LAYER3_URL",
    "https://ihq6gjldxbulfke5xd2xexnoqe0vyrxt.lambda-url.ap-northeast-2.on.aws/")
LAYER5_URL = os.environ.get("LAYER5_URL",
    "https://rn32hjcarfgqhopm266iidoeey0lkbkt.lambda-url.ap-northeast-2.on.aws/")
LAYER6_URL = os.environ.get("LAYER6_URL",
    "https://ofii46d5p6446ceahn3ucb5f2a0xcvej.lambda-url.ap-northeast-2.on.aws/")

# === Layer별 타임아웃 (초) ===
LAYER_TIMEOUTS = {
    "layer1": 120,
    "layer2": 180,
    "layer2b": 180,
    "layer3": 30,
    "layer5": 120,
    "layer6": 120,
}

# === 기본 옵션값 ===
DEFAULT_OPTIONS = {
    "report_language": "ko",
    "include_rag": True,
    "top_k": 3,
    "skip_layers": [],
    "return_mask": True,
    "return_annotated_image": True,
}

# === S3 설정 ===
WORK_BUCKET = os.environ.get("WORK_BUCKET",
    "pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an")
SAMPLE_S3_PREFIX = "web/test-integrated/samples"
