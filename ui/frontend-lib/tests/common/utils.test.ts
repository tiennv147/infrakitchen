import { describe, expect, it } from "vitest";

import { formatLabel, getRepoNameFromUrl } from "../../src/common/utils";

describe("getRepoNameFromUrl", () => {
  it.each([
    [
      "https://github.com/electrolux-oss/infrakitchen",
      "electrolux-oss/infrakitchen",
    ],
    [
      "https://github.com/electrolux-oss/infrakitchen.git",
      "electrolux-oss/infrakitchen",
    ],
    ["https://gitlab.com/group/sub/project.git", "sub/project"],
    ["ssh://git@github.com/org/repo.git", "org/repo"],
    ["git@github.com:org/repo.git", "org/repo"],
  ])("parses %s", (url, expected) => {
    expect(getRepoNameFromUrl(url)).toBe(expected);
  });

  it("falls back for URLs without owner/repo", () => {
    expect(getRepoNameFromUrl("https://github.com/")).toBe(
      "Unknown Repository",
    );
    expect(getRepoNameFromUrl("not a url")).toBe("not a url");
  });
});

describe("formatLabel", () => {
  it("title-cases words and keeps known acronyms", () => {
    expect(formatLabel("source_code_url")).toBe("Source Code URL");
    expect(formatLabel("integration_id")).toBe("Integration ID");
    expect(formatLabel("ssh_key")).toBe("SSH Key");
  });

  it("uses provider display names", () => {
    expect(formatLabel("github")).toBe("GitHub");
    expect(formatLabel("aws_account")).toBe("AWS Account");
  });
});
