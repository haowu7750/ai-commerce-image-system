export const dashboardStats = [
  { label: "演示项目", value: "3", note: "静态数据" },
  { label: "待人工确认", value: "2", note: "仅状态示例" },
  { label: "高风险阻断", value: "1", note: "门禁示例" },
] as const;

export const demoProjects = [
  {
    id: "DEMO-001",
    name: "厨房收纳盒场景图测试",
    platform: "拼多多",
    status: "资料待补充",
    next: "锁定商品关键事实",
  },
  {
    id: "DEMO-002",
    name: "宠物饮水碗主图优化",
    platform: "拼多多",
    status: "处理中",
    next: "确认参考图用途",
  },
  {
    id: "DEMO-003",
    name: "旅行分装瓶套装",
    platform: "拼多多",
    status: "待运营验收",
    next: "人工验收 Mock 任务",
  },
] as const;

export const productFacts = [
  { label: "商品名称", value: "透明厨房收纳盒", source: "人工填写" },
  { label: "材质", value: "PET", source: "商品资料" },
  { label: "规格", value: "中号 · 单只装", source: "Mock ERP 快照" },
  { label: "真实用途", value: "冰箱内分类收纳果蔬", source: "人工确认" },
  { label: "禁改项", value: "盒体比例、透明度、卡扣结构", source: "运营约束" },
  { label: "不可宣称", value: "抗菌、永久保鲜、零甲醛", source: "合规规则" },
] as const;

export const referenceCandidates = [
  {
    id: "ref-kitchen",
    title: "真实冰箱收纳场景",
    note: "只参考空间层次和自然光，不复制商品外观。",
    accent: "from-emerald-100 to-stone-100",
  },
  {
    id: "ref-counter",
    title: "厨房台面使用场景",
    note: "只参考生活感和道具比例，不复制图中文字。",
    accent: "from-amber-100 to-orange-50",
  },
] as const;
