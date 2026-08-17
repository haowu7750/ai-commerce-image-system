import Link from "next/link";

import { AccessGate } from "@/components/access-gate";
import { batchTools } from "@/lib/batch-image-tools";

export default function BatchImagePage() {
  return (
    <AccessGate requiredRole="operator">
      <div className="mx-auto max-w-[1500px]">
        <div className="rounded-[32px] border border-indigo-100 bg-gradient-to-br from-white via-white to-indigo-50 p-7 shadow-card md:p-10">
          <p className="eyebrow !text-indigo-600">电商效率工具</p>
          <h1 className="mt-3 text-3xl font-black tracking-tight md:text-5xl">批量电商图片处理</h1>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-stone-600 md:text-base">
            选择一种独立任务，上传图片、配置参数、查看进度；AI 结果仍需运营逐张验收后才能保存和下载。
          </p>
        </div>

        <section className="mt-7 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {batchTools.map((tool) => (
            <Link
              className="group rounded-[28px] border border-stone-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:border-indigo-200 hover:shadow-card"
              href={`/batch-image/${tool.mode}`}
              key={tool.mode}
            >
              <span className={`inline-grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br ${tool.accent} text-xl font-black text-white shadow-lg`}>
                {tool.badge}
              </span>
              <h2 className="mt-5 text-xl font-black">{tool.title}</h2>
              <p className="mt-2 min-h-14 text-sm leading-6 text-stone-500">{tool.description}</p>
              <span className="mt-5 inline-flex items-center gap-2 text-sm font-black text-indigo-600">
                进入工具 <span aria-hidden>→</span>
              </span>
            </Link>
          ))}
        </section>

        <div className="mt-7 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-900">
          当前版本只支持点击后立即执行，不提供定时无人值守任务。AI 候选图不会自动发布，也不会自动写回 ERP。
        </div>
      </div>
    </AccessGate>
  );
}
