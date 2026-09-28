import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';

const buttonVariants = {
  primary: 'bg-accent-500 text-white shadow-glow hover:bg-accent-400',
  secondary: 'border border-slate-700 bg-slate-800/80 text-slate-100 hover:border-sky-400/40 hover:bg-slate-700/80',
  ghost: 'text-slate-300 hover:bg-slate-800/70 hover:text-white',
  danger: 'border border-rose-500/40 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20',
} as const;

type ButtonVariant = keyof typeof buttonVariants;

export function Button({
  className = '',
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-sky-400/60 disabled:cursor-not-allowed disabled:opacity-60 ${buttonVariants[variant]} ${className}`}
      {...props}
    />
  );
}

const badgeVariants = {
  idle: 'border-slate-700 bg-slate-800/80 text-slate-300',
  running: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
  completed: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200',
  failed: 'border-rose-500/30 bg-rose-500/10 text-rose-200',
  queued: 'border-sky-500/30 bg-sky-500/10 text-sky-200',
  local: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200',
} as const;

type BadgeVariant = keyof typeof badgeVariants;

export function Badge({ children, variant = 'idle' }: { children: ReactNode; variant?: BadgeVariant }) {
  return <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${badgeVariants[variant]}`}>{children}</span>;
}

export function Card({ children, className = '', ...props }: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={`rounded-2xl border border-slate-800/90 bg-slate-900/80 shadow-glow backdrop-blur-sm ${className}`} {...props}>
      {children}
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <Card className="p-8 text-center">
      <div className="mx-auto max-w-md space-y-3">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        {description ? <p className="text-sm leading-6 text-slate-400">{description}</p> : null}
        {action ? <div className="pt-2">{action}</div> : null}
      </div>
    </Card>
  );
}
