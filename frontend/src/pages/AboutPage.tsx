import { Link } from 'react-router-dom';
import { ArrowRight, Captions, CheckCircle2, Film, Gauge, Scissors, ShieldCheck, Sparkles } from 'lucide-react';
import { Badge, Button, Card } from '../components/ui';

const workflow = [
  {
    icon: Film,
    title: 'Bring in a video',
    description: 'Start with gameplay you own or have permission to reuse.',
  },
  {
    icon: Captions,
    title: 'Transcribe locally',
    description: 'Whisper creates a transcript without requiring a paid API key.',
  },
  {
    icon: Sparkles,
    title: 'Review suggestions',
    description: 'Candidate moments are explainable suggestions, not promises of virality.',
  },
  {
    icon: Scissors,
    title: 'Trim and render',
    description: 'Adjust boundaries, add burned-in captions, and render a vertical Short.',
  },
];

const principles = [
  'Human review stays in the loop before a clip is rendered.',
  'The pipeline is designed for 1080×1920 YouTube Shorts.',
  'Source videos, transcripts, candidates, and renders remain in the local workspace.',
  'The project does not upload or publish videos automatically.',
];

export function AboutPage() {
  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-3xl border border-accent-500/20 bg-gradient-to-br from-accent-500/15 via-surface-900 to-surface-900 p-6 shadow-subtle sm:p-10">
        <div className="absolute -right-20 -top-24 h-64 w-64 rounded-full bg-accent-500/10 blur-3xl" />
        <div className="relative max-w-3xl">
          <Badge variant="queued">Project overview</Badge>
          <h2 className="mt-5 text-3xl font-semibold tracking-tight text-white sm:text-5xl">
            Turn gameplay footage into focused vertical Shorts.
          </h2>
          <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300 sm:text-lg">
            ClippyRipoff is a local video workspace for analyzing gameplay, choosing moments, refining trims, and rendering captioned 1080×1920 videos.
            It helps organize the editing pipeline without taking creative decisions away from you.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link to="/login">
              <Button>
                Sign in to get started
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <span className="inline-flex items-center gap-2 rounded-xl border border-surface-600 bg-surface-800/80 px-4 py-2 text-sm text-slate-300">
              <ShieldCheck className="h-4 w-4 text-success-400" />
              Local-first workflow
            </span>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="rounded-xl border border-accent-500/25 bg-accent-500/10 p-2.5 text-accent-300">
              <Gauge className="h-5 w-5" />
            </div>
            <h3 className="text-lg font-semibold text-white">What it does</h3>
          </div>
          <p className="mt-4 text-sm leading-7 text-slate-400">
            The workspace wraps a Python video pipeline with a browser interface. Analyze a source, inspect candidate moments, make manual trim adjustments, and keep track of render jobs and finished files in one place.
          </p>
        </Card>
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="rounded-xl border border-success-500/25 bg-success-500/10 p-2.5 text-success-300">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <h3 className="text-lg font-semibold text-white">What it does not claim</h3>
          </div>
          <p className="mt-4 text-sm leading-7 text-slate-400">
            Candidate detection is intentionally explainable and reviewable. The project does not claim that a clip will go viral, and it does not automatically upload or publish anything.
          </p>
        </Card>
      </section>

      <section className="space-y-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500">The workflow</div>
          <h3 className="mt-2 text-2xl font-semibold text-white">From source video to finished Short</h3>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {workflow.map(({ icon: Icon, title, description }, index) => (
            <Card key={title} className="p-5">
              <div className="flex items-center justify-between">
                <div className="rounded-xl border border-surface-600 bg-surface-800 p-2.5 text-accent-300">
                  <Icon className="h-5 w-5" />
                </div>
                <span className="text-xs font-semibold text-slate-600">0{index + 1}</span>
              </div>
              <h4 className="mt-5 font-semibold text-white">{title}</h4>
              <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p>
            </Card>
          ))}
        </div>
      </section>

      <Card className="p-6 sm:p-8">
        <div className="grid gap-8 lg:grid-cols-[0.8fr_1.2fr] lg:items-start">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Built around control</div>
            <h3 className="mt-2 text-2xl font-semibold text-white">A practical editing pipeline, not an autopilot.</h3>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2">
            {principles.map((principle) => (
              <li key={principle} className="flex gap-3 rounded-xl border border-surface-700 bg-surface-800/60 p-4 text-sm leading-6 text-slate-300">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success-400" />
                <span>{principle}</span>
              </li>
            ))}
          </ul>
        </div>
      </Card>
    </div>
  );
}
