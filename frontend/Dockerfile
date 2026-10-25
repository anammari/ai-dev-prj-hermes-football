# The dashboard image: build once, run the traced server.
#
# The build context is the repository root, because the API types are generated from `openapi.yaml`
# and a dashboard that compiles against a stale copy of the contract is exactly the drift the backend
# test suite exists to prevent. `pnpm check:api` fails the image build if the committed types are not
# what the contract produces today.
FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
# One native postinstall (unrs-resolver, reached through openapi-typescript) has to be allowed
# explicitly; pnpm 12 refuses build scripts by default.
RUN pnpm install --frozen-lockfile --allow-build=unrs-resolver

FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
COPY openapi.yaml /openapi.yaml
RUN pnpm check:api && pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
