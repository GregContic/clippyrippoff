import { Card } from './ui';

const steps = [
  { key: 'queued', label: 'Queued' },
  { key: 'preparing', label: 'Preparing' },
  { key: 'downloading', label: 'Downloading' },
  { key: 'uploading', label: 'Uploading' },
  { key: 'transcribing', label: 'Transcribing' },
  { key: 'detecting', label: 'Detecting Highlights' },
  { key: 'ranking', label: 'Detecting Highlights' },
  { key: 'complete', label: 'Completed' },
];

export function AnalysisProgress({ stage, message, status }: { stage?: string | null; message?: string | null; status: string }) {
  const currentIndex = Math.max(0, steps.findIndex((step) => step.key === stage));
  const failed = status === 'failed';

  return (
    <Card className={`p-5 ${failed ? 'border-rose-500/30 bg-rose-500/10' : ''}`}>
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-white">{failed ? 'Analysis failed' : 'Analyzing video...'}</div>
          <div className={`mt-1 text-sm ${failed ? 'text-rose-100' : 'text-slate-400'}`}>
            {message ?? 'Working locally on this machine.'}
          </div>
        </div>
        <div className={`text-xs uppercase tracking-[0.24em] ${failed ? 'text-rose-200' : 'text-slate-500'}`}>{status}</div>
      </div>

      {!failed ? (
        <div className="mt-5 space-y-3">
          {steps.map((step, index) => {
            const isComplete = index < currentIndex || stage === 'complete';
            const isActive = index === currentIndex && stage !== 'complete';
            return (
              <div key={step.key} className="flex items-center gap-3">
                <div className={`h-2.5 w-2.5 rounded-full ${isComplete ? 'bg-accent-400' : isActive ? 'bg-accent-300' : 'bg-slate-600'}`} />
                <div className="flex-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className={isActive || isComplete ? 'text-white' : 'text-slate-400'}>{step.label}</span>
                    <span className="text-xs text-slate-500">{isComplete ? 'Done' : isActive ? 'Active' : 'Pending'}</span>
                  </div>
                  {isActive ? <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-800"><div className="h-full w-1/2 rounded-full bg-accent-500" /></div> : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </Card>
  );
}
