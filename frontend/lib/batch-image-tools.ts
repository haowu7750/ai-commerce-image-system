import type { BatchImageMode } from "@/lib/api";

export type SupportedBatchMode = Exclude<BatchImageMode, "replace_product">;

export type BatchTool = {
  mode: SupportedBatchMode;
  title: string;
  shortTitle: string;
  description: string;
  badge: string;
  accent: string;
};

export const batchTools: BatchTool[] = [
  {
    mode: "scene_replace",
    title: "批量场景替换",
    shortTitle: "场景替换",
    description: "一张商品参考图搭配多张场景图，批量生成自然融合的商品场景图。",
    badge: "场",
    accent: "from-violet-500 to-indigo-500",
  },
  {
    mode: "pattern_extract",
    title: "批量印花提取",
    shortTitle: "印花提取",
    description: "从商品原图提取印花，校正透视并输出可复用的平面图。",
    badge: "印",
    accent: "from-fuchsia-500 to-pink-500",
  },
  {
    mode: "resize",
    title: "批量改尺寸",
    shortTitle: "智能改尺寸",
    description: "智能重排到目标比例，保留商品、文字和关键版式，不变形不裁切。",
    badge: "尺",
    accent: "from-cyan-500 to-blue-500",
  },
  {
    mode: "buyer_show",
    title: "批量买家秀",
    shortTitle: "买家秀",
    description: "把真实商品自然融入生活化晒单场景，批量生成买家秀候选。",
    badge: "秀",
    accent: "from-amber-500 to-orange-500",
  },
  {
    mode: "angle_fission",
    title: "批量角度裂变",
    shortTitle: "角度裂变",
    description: "按统一镜头计划生成整体角度与细节图，保持商品结构一致。",
    badge: "角",
    accent: "from-emerald-500 to-teal-500",
  },
  {
    mode: "custom_edit",
    title: "自定义批量",
    shortTitle: "自定义批量",
    description: "一条提示词应用到一批图，支持固定参考图与逐张配对参考图。",
    badge: "自",
    accent: "from-slate-600 to-slate-800",
  },
];

export const batchToolByMode = Object.fromEntries(
  batchTools.map((tool) => [tool.mode, tool]),
) as Record<SupportedBatchMode, BatchTool>;

export function isSupportedBatchMode(value: string): value is SupportedBatchMode {
  return batchTools.some((tool) => tool.mode === value);
}
