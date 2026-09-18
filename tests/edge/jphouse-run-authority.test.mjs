import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

test("the unused legacy Edge Function is removed rather than left as a bypass path", () => {
  assert.equal(existsSync(resolve("supabase/functions/jphouse-run")), false);
});
