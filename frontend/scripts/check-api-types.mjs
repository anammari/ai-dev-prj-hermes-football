#!/usr/bin/env node
/**
 * Fail when the committed API types no longer match `openapi.yaml`.
 *
 * The backend has a contract-drift test; this is the dashboard's half of the same promise. Without it,
 * a contract change would compile fine here and fail in the browser as a renamed field.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const committed = new URL("../src/lib/api/schema.d.ts", import.meta.url).pathname;
const temp = mkdtempSync(join(tmpdir(), "hermes-api-"));
const generated = join(temp, "schema.d.ts");

try {
  execFileSync("node", ["node_modules/openapi-typescript/bin/cli.js", "../openapi.yaml", "-o", generated], {
    stdio: "pipe",
  });
  const a = readFileSync(committed, "utf8");
  const b = readFileSync(generated, "utf8");
  if (a !== b) {
    console.error("src/lib/api/schema.d.ts is stale: run `pnpm gen:api` and commit the result.");
    process.exit(1);
  }
  console.log("API types match openapi.yaml");
} finally {
  rmSync(temp, { recursive: true, force: true });
}
