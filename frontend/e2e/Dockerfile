# The browser-and-unit-test image. Playwright's own image carries the browsers and their system
# libraries; the test package comes from the lockfile, so the version tested is the version pinned in
# package.json. The whole dashboard is copied (not just e2e/) because `make frontend-test` runs lint,
# typecheck and Vitest here too - one pinned toolchain for every frontend gate.
FROM mcr.microsoft.com/playwright:v1.64.1-noble
WORKDIR /e2e
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --allow-build=unrs-resolver
COPY frontend/ ./
CMD ["pnpm", "exec", "playwright", "test"]
