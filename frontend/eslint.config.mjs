import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// eslint-config-next 16 ships flat configs, so there is no FlatCompat shim here. Linting is part of
// `make frontend-test`, not the build: `next build` should fail on types and tests, not on style.
const config = [
  ...nextVitals,
  ...nextTypescript,
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "src/lib/api/schema.d.ts"],
  },
];

export default config;
