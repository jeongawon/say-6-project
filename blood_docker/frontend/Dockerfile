# ── Frontend Dockerfile ────────────────────────────────────
# nginx로 정적 HTML 서빙 + /api/ 프록시
FROM nginx:1.27-alpine

# 기본 nginx 설정 제거 후 커스텀 설정 적용
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 프론트엔드 파일 복사
COPY index.html /usr/share/nginx/html/index.html

EXPOSE 80

# nginx 포그라운드 실행
CMD ["nginx", "-g", "daemon off;"]
