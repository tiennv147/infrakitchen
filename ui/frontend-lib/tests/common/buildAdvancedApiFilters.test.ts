import { describe, expect, it } from "vitest";

import { buildAdvancedApiFilters } from "../../src/common/components/filter_panel/buildAdvancedApiFilters";

describe("buildAdvancedApiFilters", () => {
  it("returns an empty object when there are no clauses", () => {
    expect(buildAdvancedApiFilters({})).toEqual({});
    expect(buildAdvancedApiFilters({ filter: "not-an-array" })).toEqual({});
  });

  it("uses the bare field name for eq and field__operator otherwise", () => {
    expect(
      buildAdvancedApiFilters({
        filter: [
          { field: "name", operator: "eq", value: "shop" },
          { field: "labels", operator: "contains", value: ["prod"] },
          { field: "status", operator: "not_eq", value: "error" },
        ],
      }),
    ).toEqual({
      name: "shop",
      labels__contains: ["prod"],
      status__not_eq: "error",
    });
  });

  it("emits true for is_none regardless of value", () => {
    expect(
      buildAdvancedApiFilters({
        filter: [{ field: "parent_id", operator: "is_none", value: undefined }],
      }),
    ).toEqual({ parent_id__is_none: true });
  });

  it("skips clauses without a field or with empty values", () => {
    expect(
      buildAdvancedApiFilters({
        filter: [
          { field: "", operator: "eq", value: "x" },
          { field: "a", operator: "eq", value: "" },
          { field: "b", operator: "eq", value: null },
          { field: "c", operator: "in", value: [] },
          { field: "d", operator: "eq", value: 0 },
        ],
      }),
    ).toEqual({ d: 0 });
  });
});
