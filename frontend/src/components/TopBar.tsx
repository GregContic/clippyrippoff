import { Badge } from './ui';

export function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="flex flex-col gap-3 border-b border-slate-800/80 px-6 py-5 md:flex-row md:items-center md:justify-between lg:px-8">
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-white md:text-2xl">{title}</h1>
          <Badge variant="local">LOCAL</Badge>
        </div>
        {subtitle ? <p className="mt-1 text-sm text-slate-400">{subtitle}</p> : null}
      </div>
    </header>
  );
}
