export const roleKeys = ["operator", "designer", "admin"] as const;

export type UserRole = (typeof roleKeys)[number];

export type NavItem = {
  label: string;
  href: string;
  note?: string;
  available: boolean;
};

export type RolePolicy = {
  label: string;
  home: string;
  summary: string;
  boundaries: string[];
  allowedPrefixes: string[];
  nav: NavItem[];
};

export const ROLE_POLICIES: Record<UserRole, RolePolicy> = {
  operator: {
    label: "电商运营",
    home: "/workspace",
    summary: "负责商品事实、内容、设计结果及写回准备的最终业务确认。",
    boundaries: [
      "可以确认商品事实、内容版本、提示词和设计结果。",
      "不能查看完整 ERP 密钥或修改全局权限。",
      "任何 AI 结果都必须人工验收，高风险内容不得确认。",
    ],
    allowedPrefixes: [
      "/workspace",
      "/projects",
      "/content-lab",
      "/image-studio",
      "/tasks",
      "/results",
      "/erp",
    ],
    nav: [
      { label: "运营工作台", href: "/workspace", available: true },
      { label: "商品项目", href: "/projects", available: true },
      { label: "内容 AI", href: "/content-lab", available: true },
      { label: "AI 生图", href: "/image-studio", available: true },
      { label: "美工协作", href: "/tasks", available: true },
      { label: "结果汇总", href: "/results", available: true },
      { label: "Mock ERP", href: "/erp", available: true },
    ],
  },
  designer: {
    label: "美工",
    home: "/designer",
    summary: "仅处理分配给自己的设计任务和必要商品摘要。",
    boundaries: [
      "不能修改商品事实、标题或 SKU 最终版。",
      "不能操作 ERP，也不能将设计结果标为最终上架版本。",
      "可以更新任务状态、提出问题并提交多版设计结果。",
    ],
    allowedPrefixes: ["/designer"],
    nav: [{ label: "我的任务", href: "/designer", available: true }],
  },
  admin: {
    label: "管理员",
    home: "/admin",
    summary: "维护用户、规则、Prompt 和系统设置，不自动拥有业务审核权。",
    boundaries: [
      "管理员身份不能确认商品内容、设计结果或 ERP 写回。",
      "需要参与运营时，必须另外获得电商运营角色。",
      "配置和用户操作由服务端权限校验并写入审计。",
    ],
    allowedPrefixes: ["/admin"],
    nav: [{ label: "系统管理", href: "/admin", available: true }],
  },
};

export function parseRole(value: string | string[] | undefined): UserRole | null {
  const candidate = Array.isArray(value) ? value[0] : value;
  return roleKeys.includes(candidate as UserRole)
    ? (candidate as UserRole)
    : null;
}

export function canAccess(role: UserRole, pathname: string): boolean {
  return ROLE_POLICIES[role].allowedPrefixes.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/"),
  );
}

export function roleHref(role: UserRole, pathname: string): string {
  void role;
  return pathname;
}
