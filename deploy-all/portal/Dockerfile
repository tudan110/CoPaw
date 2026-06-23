# -----------------------------------------------------------------------------
# Portal Dockerfile for k3s deployment
# Build context: project root directory
# Build command: docker build -f deploy-all/portal/Dockerfile -t portal:0.1.0 .
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Stage 1: Build the React application
# -----------------------------------------------------------------------------
FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY portal/package.json portal/pnpm-lock.yaml portal/pnpm-workspace.yaml ./

RUN pnpm install --frozen-lockfile

COPY portal/ .

RUN pnpm run build

# -----------------------------------------------------------------------------
# Stage 2: Pure nginx runtime
# -----------------------------------------------------------------------------
FROM nginx:alpine AS production

COPY --from=builder /app/dist /usr/share/nginx/html
COPY deploy-all/portal/nginx.conf /etc/nginx/nginx.conf
COPY deploy-all/portal/docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh

# nginx:alpine 基础镜像里 /var/cache/nginx 的 owner 可能是 uid 1000(残留),
# 而 worker 跑 nginx 用户(uid 101),写 client_temp 会 EACCES,大 body POST
# 直接 nginx 500（请求不会到上游）。显式 chown 让 owner 跟着 worker 走。
RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh \
    && chown -R nginx:nginx /var/cache/nginx

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
