# Web app image for container hosts and the local demo-profile stack (DEPLOYMENT §3). On
# Vercel the same app builds natively and this file is unused.
# NEXT_PUBLIC_API_BASE_URL is compiled into the client bundle, so it is a build argument.
FROM node:22.22.0-bookworm-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22.22.0-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
COPY --from=build /app ./
USER node
EXPOSE 3000
CMD ["pnpm", "start", "--port", "3000"]
