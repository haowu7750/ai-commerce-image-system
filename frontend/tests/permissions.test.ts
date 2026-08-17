import { describe, expect, it } from "vitest";

import {
  canAccess,
  parseRole,
  ROLE_POLICIES,
} from "../lib/permissions";

describe("角色权限骨架", () => {
  it("只解析三个已确认角色", () => {
    expect(parseRole("operator")).toBe("operator");
    expect(parseRole("designer")).toBe("designer");
    expect(parseRole("admin")).toBe("admin");
    expect(parseRole("reviewer")).toBeNull();
    expect(parseRole(undefined)).toBeNull();
  });

  it("运营可访问生图页，美工和管理员不可访问", () => {
    expect(canAccess("operator", "/image-studio")).toBe(true);
    expect(canAccess("designer", "/image-studio")).toBe(false);
    expect(canAccess("admin", "/image-studio")).toBe(false);
    expect(canAccess("operator", "/batch-image")).toBe(true);
    expect(canAccess("designer", "/batch-image")).toBe(false);
    expect(canAccess("admin", "/batch-image")).toBe(false);
  });

  it("管理员首页不授予运营业务路径", () => {
    expect(ROLE_POLICIES.admin.allowedPrefixes).toEqual(["/admin"]);
    expect(canAccess("admin", "/projects")).toBe(false);
  });
});
