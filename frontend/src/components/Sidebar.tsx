import { NavLink } from 'react-router-dom';

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/renders', label: 'Projects' },
  { to: '/library', label: 'Library' },
  { to: '/settings', label: 'Settings' },
];

export function Sidebar() {
  return (
    <aside className="hidden w-64 flex-col border-r border-slate-800 bg-slate-950/90 px-5 py-6 lg:flex">
      <div className="space-y-1 border-b border-slate-800 pb-5">
        <div className="text-xs uppercase tracking-[0.3em] text-sky-300/80">ClippyRipoff</div>
        <div className="text-lg font-semibold text-white">AI Gaming Shorts Generator</div>
        <div className="inline-flex items-center gap-2 pt-2 text-xs text-cyan-200">
          <span className="h-2 w-2 rounded-full bg-cyan-400" />
          LOCAL
        </div>
      </div>

      <nav className="mt-6 flex flex-1 flex-col gap-2">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              [
                'rounded-xl px-4 py-3 text-sm font-medium transition',
                isActive ? 'bg-slate-800 text-white shadow-glow' : 'text-slate-300 hover:bg-slate-900 hover:text-white',
              ].join(' ')
            }
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
