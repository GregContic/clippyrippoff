import { Card } from './ui';

const steps = [
  { key: 'preparing', label: 'Preparing' },
  { key: 'downloading', label: 'Downloading' },
  { key: 'transcribing', label: 'Transcribing' },
  { key: 'detecting', label: 'Detecting moments' },
  { key: 'ranking', label: 'Ranking candidates' },
  { key: 'complete', label: 'Complete' },
];

export function AnalysisProgress({ stage, message, status }: { stage?: string | null; message?: string | null; status: string }) {
  const currentIndex = Math.max(0, steps.findIndex((step) => step.key === stage));

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-white">Analyzing video...</div>
          <div className="mt-1 text-sm text-slate-400">{message ?? 'Working locally on this machine.'}</div>
        </div>
        <div className="text-xs uppercase tracking-[0.24em] text-slate-500">{status}</div>
      </div>

      <div className="mt-5 space-y-3">
        {steps.map((step, index) => {
          const isComplete = index < currentIndex || stage === 'complete';
          const isActive = index === currentIndex && stage !== 'complete';
          return (
            <div key={step.key} className="flex items-center gap-3">
              <div className={`h-2.5 w-2.5 rounded-full ${isComplete ? 'bg-cyan-400' : isActive ? 'bg-sky-300 shadow-[0_0_0_6px_rgba(56,189,248,0.14)]' : 'bg-slate-600'}`} />
              <div className="flex-1">
                <div className="flex items-center justify-between text-sm">
                  <span className={isActive || isComplete ? 'text-white' : 'text-slate-400'}>{step.label}</span>
                  <span className="text-xs text-slate-500">{isComplete ? 'Done' : isActive ? 'Active' : 'Pending'}</span>
                </div>
                {isActive ? <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full w-1/2 animate-pulse rounded-full bg-gradient-to-r from-sky-400 to-cyan-300" /></div> : null}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
