export function StagePlaceholder({
  stage,
  title,
  description,
  items,
}: {
  stage: string;
  title: string;
  description: string;
  items: string[];
}) {
  return (
    <section className="panel border-dashed p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">{stage}</p>
          <h2 className="mt-2 text-xl font-black">{title}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-600">
            {description}
          </p>
        </div>
        <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-800">
          尚未实现
        </span>
      </div>
      <ul className="mt-5 grid gap-2 text-sm text-stone-600 sm:grid-cols-2">
        {items.map((item) => (
          <li className="rounded-xl bg-stone-50 px-3 py-2" key={item}>
            · {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
