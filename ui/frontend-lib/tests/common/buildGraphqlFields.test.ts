import { describe, expect, it } from "vitest";

import {
  buildGraphqlFields,
  buildNestedSelection,
  buildSelection,
} from "../../src/common/graphql/buildGraphqlFields";

describe("buildGraphqlFields", () => {
  it("converts snake_case fields to camelCase", () => {
    expect(buildGraphqlFields(["id", "created_at", "updated_by"])).toBe(
      ["id", "createdAt", "updatedBy"].join("\n      "),
    );
  });

  it("merges dotted paths into nested selections", () => {
    expect(
      buildGraphqlFields(["template.id", "template.display_name", "name"]),
    ).toBe(
      ["template {", "  id", "  displayName", "}", "name"].join("\n      "),
    );
  });

  it("uses raw selections from the field map first and dedupes them", () => {
    const fieldMap = { creator: "creator { id displayName }" };
    expect(buildGraphqlFields(["name", "creator", "creator"], fieldMap)).toBe(
      ["creator { id displayName }", "name"].join("\n      "),
    );
  });
});

describe("selection helpers", () => {
  it("joins fields", () => {
    expect(buildSelection(["id", "name"])).toBe("id\n  name");
  });

  it("wraps nested fields", () => {
    expect(buildNestedSelection("owner", "id")).toBe("owner {\n    id\n  }");
  });
});
