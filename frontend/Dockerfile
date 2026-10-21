FROM node:24-alpine AS build
WORKDIR /app

RUN npm install --global pnpm@11.25.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# Explicit copies keep local .env files and server secrets out of the build.
COPY index.html tsconfig.json vite.config.ts eslint.config.js ./
COPY src ./src
COPY public ./public

ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_API_MODE=real
ENV VITE_FEATURE_AUTH=true

RUN node -e "const u = new URL(process.env.VITE_API_URL); if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password) throw new Error('VITE_API_URL must be a public HTTP(S) backend URL without credentials');"
RUN pnpm run lint && pnpm run typecheck && pnpm test && pnpm run build

FROM nginx:stable-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
