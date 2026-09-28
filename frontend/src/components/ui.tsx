import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';

const buttonVariants = {
  primary: 'border border-accent-500 bg-accent-500 text-white hover:bg-accent-400',
  secondary: 'border border-surface-600 bg-surface-800 text-slate-100 hover:bg-surface-700',
  ghost: 'border border-transparent bg-transparent text-slate-300 hover:border-surface-700 hover:bg-surface-800 hover:text-white',
  danger: 'border border-danger-500/30 bg-danger-500/10 text-danger-100 hover:bg-danger-500/20',
} as const;

type ButtonVariant = keyof typeof buttonVariants;

export function Button({
  className = '',
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/70 disabled:cursor-not-allowed disabled:opacity-50 ${buttonVariants[variant]} ${className}`}
      {...props}
    />
  );
}

const badgeVariants = {
  neutral: 'border-surface-600 bg-surface-800 text-slate-300',
  running: 'border-warning-500/30 bg-warning-500/10 text-warning-200',
  completed: 'border-success-500/30 bg-success-500/10 text-success-100',
  failed: 'border-danger-500/30 bg-danger-500/10 text-danger-100',
  queued: 'border-accent-500/30 bg-accent-500/10 text-accent-300',
  local: 'border-surface-600 bg-surface-800 text-slate-100',
  info: 'border-slate-600 bg-slate-800 text-slate-100',
} as const;

type BadgeVariant = keyof typeof badgeVariants;

export function Badge({ children, variant = 'neutral' }: { children: ReactNode; variant?: BadgeVariant }) {
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.16em] ${badgeVariants[variant]}`}>{children}</span>;
}

export function Card({ children, className = '', ...props }: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={`rounded-2xl border border-surface-700 bg-surface-900 shadow-subtle ${className}`} {...props}>
      {children}
    </div>
  );
}

const fieldBase = 'w-full rounded-xl border border-surface-600 bg-surface-800 px-3 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accent-400 focus:ring-2 focus:ring-accent-400/20';

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${fieldBase} ${props.className ?? ''}`.trim()} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${fieldBase} ${props.className ?? ''}`.trim()} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${fieldBase} ${props.className ?? ''}`.trim()} />;
}

export function StatCard({ label, value, detail }: { label: string; value: ReactNode; detail?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      {detail ? <div className="mt-2 text-sm leading-6 text-slate-400">{detail}</div> : null}
    </Card>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <Card className="p-8 text-center">
      <div className="mx-auto max-w-lg space-y-3">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        {description ? <p className="text-sm leading-6 text-slate-400">{description}</p> : null}
        {action ? <div className="pt-2">{action}</div> : null}
      </div>
    </Card>
  );
}
