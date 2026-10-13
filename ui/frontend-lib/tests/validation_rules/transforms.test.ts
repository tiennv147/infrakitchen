import { describe, expect, it } from "vitest";

import { transformValidationRulesByVariable } from "../../src/validation_rules/graphql/transforms";

describe("transformValidationRulesByVariable", () => {
  it("maps GraphQL camelCase fields to the REST snake_case shape", () => {
    expect(
      transformValidationRulesByVariable({
        variableName: "instance_type",
        rules: [
          {
            id: null,
            targetType: "string",
            description: "Allowed sizes",
            minValue: null,
            maxValue: null,
            regexPattern: "^t3\\.",
            maxLength: 32,
          },
        ],
      }),
    ).toEqual({
      variable_name: "instance_type",
      rules: [
        {
          id: undefined,
          target_type: "string",
          description: "Allowed sizes",
          min_value: null,
          max_value: null,
          regex_pattern: "^t3\\.",
          max_length: 32,
        },
      ],
    });
  });
});
