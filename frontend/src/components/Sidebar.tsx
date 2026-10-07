import { NavLink } from 'react-router-dom';
import { CircleHelp, FolderKanban, LayoutDashboard, LibraryBig, ListVideo, Search, Settings2 } from 'lucide-react';

const links = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/projects', label: 'Projects', icon: FolderKanban },
  { to: '/analyze', label: 'Analysis', icon: Search },
  { to: '/renders', label: 'Render Queue', icon: ListVideo },
  { to: '/library', label: 'Library', icon: LibraryBig },
  { to: '/settings', label: 'Settings', icon: Settings2 },
  { to: '/about', label: 'About the project', icon: CircleHelp },
];

export function Sidebar() {
  return (
    <aside className="hidden w-64 flex-col border-r border-surface-700 bg-surface-900 px-4 py-5 lg:flex">
      <div className="space-y-3 border-b border-surface-700 pb-5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.28em] text-slate-500">ClippyRipoff</div>
          <div className="mt-1 text-lg font-semibold text-white">Local video workspace</div>
          <p className="mt-2 text-sm leading-6 text-slate-400">Organize analysis, trims, renders, and finished Shorts on this machine.</p>
        </div>
        <div className="inline-flex items-center gap-2 rounded-full border border-surface-600 bg-surface-800 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-300">
          <span className="h-2 w-2 rounded-full bg-success-500" />
          Local
        </div>
      </div>

      <nav className="mt-5 flex flex-1 flex-col gap-1.5">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/60',
                isActive ? 'border-accent-500/30 bg-accent-500/10 text-white' : 'border-transparent text-slate-300 hover:border-surface-700 hover:bg-surface-800 hover:text-white',
              ].join(' ')
            }
          >
            <link.icon className="h-4 w-4 shrink-0" />
            <span>{link.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
