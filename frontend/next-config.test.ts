import { describe, expect, it } from "vitest";

import nextConfig from "./next.config.mjs";

describe("next dev config", () => {
  it("allows local browser origins used by Docker port publishing", () => {
    expect(nextConfig.allowedDevOrigins).toEqual(expect.arrayContaining(["127.0.0.1", "localhost"]));
  });
});
