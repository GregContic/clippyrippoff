import { Route, Routes, useLocation } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { DashboardPage } from './pages/DashboardPage';
import { AnalyzePage } from './pages/AnalyzePage';
import { RendersPage } from './pages/RendersPage';
import { LibraryPage } from './pages/LibraryPage';
import { SettingsPage } from './pages/SettingsPage';

function useRouteTitle(pathname: string) {
  if (pathname.startsWith('/analyze/')) {
    return { title: 'Analysis', subtitle: 'Review candidates and render selected clips.' };
  }
  if (pathname.startsWith('/renders')) {
    return { title: 'Render Queue', subtitle: 'Track local render jobs and finished Shorts.' };
  }
  if (pathname.startsWith('/library')) {
    return { title: 'Library', subtitle: 'Rendered Shorts stored in output/shorts/.' };
  }
  if (pathname.startsWith('/settings')) {
    return { title: 'Settings', subtitle: 'Read-only project configuration for V1.' };
  }
  return { title: 'Dashboard', subtitle: 'Paste a YouTube URL and start a local analysis.' };
}

export function App() {
  const location = useLocation();
  const route = useRouteTitle(location.pathname);

  return (
    <div className="min-h-screen bg-surface-950 text-slate-100 bg-app-radial">
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar title={route.title} subtitle={route.subtitle} />
          <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
            <div className="mx-auto w-full max-w-7xl">
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/analyze/:videoId" element={<AnalyzePage />} />
                <Route path="/renders" element={<RendersPage />} />
                <Route path="/library" element={<LibraryPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Routes>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
