import { test } from "node:test";
import assert from "node:assert/strict";

import { isQueryOwnedByUser } from "../../supabase/functions/jphouse-run/authorization.mjs";

test("legacy query ownership requires a matching non-empty owner_user_id", () => {
  assert.equal(
    isQueryOwnedByUser(
      { owner_user_id: "00000000-0000-0000-0000-000000000030" },
      "00000000-0000-0000-0000-000000000030",
    ),
    true,
  );
  assert.equal(
    isQueryOwnedByUser({ owner_user_id: "" }, "00000000-0000-0000-0000-000000000030"),
    false,
  );
  assert.equal(
    isQueryOwnedByUser({ owner_user_id: "00000000-0000-0000-0000-000000000031" }, "00000000-0000-0000-0000-000000000030"),
    false,
  );
});
