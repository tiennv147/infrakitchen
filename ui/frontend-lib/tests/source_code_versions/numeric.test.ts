import { describe, expect, it } from "vitest";

import {
  formatNumericDisplayValue,
  normalizeNumericField,
  parseNumericField,
} from "../../src/source_code_versions/utils/numeric";

describe("normalizeNumericField", () => {
  it("returns empty string for empty values", () => {
    expect(normalizeNumericField(null)).toBe("");
    expect(normalizeNumericField(undefined)).toBe("");
    expect(normalizeNumericField("")).toBe("");
  });

  it("stringifies numbers", () => {
    expect(normalizeNumericField(0)).toBe("0");
    expect(normalizeNumericField(1.5)).toBe("1.5");
  });
});

describe("parseNumericField", () => {
  it("parses numeric strings and numbers", () => {
    expect(parseNumericField("42")).toBe(42);
    expect(parseNumericField("-1.25")).toBe(-1.25);
    expect(parseNumericField(7)).toBe(7);
  });

  it("returns null for empty, NaN and infinite values", () => {
    expect(parseNumericField("")).toBeNull();
    expect(parseNumericField(null)).toBeNull();
    expect(parseNumericField("abc")).toBeNull();
    expect(parseNumericField(Infinity)).toBeNull();
  });
});

describe("formatNumericDisplayValue", () => {
  it.each([
    ["10", "10"],
    ["1.500", "1.5"],
    ["2.000", "2"],
    ["0.10", "0.1"],
    [3.25, "3.25"],
    [null, ""],
  ])("formats %s as %s", (input, expected) => {
    expect(formatNumericDisplayValue(input)).toBe(expected);
  });
});
