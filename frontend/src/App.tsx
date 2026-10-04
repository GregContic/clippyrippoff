import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { Button } from './components/ui';
import { AnalyzePage } from './pages/AnalyzePage';
import { DashboardPage } from './pages/DashboardPage';
import { RendersPage } from './pages/RendersPage';
import { LibraryPage } from './pages/LibraryPage';
import { SettingsPage } from './pages/SettingsPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { ProjectWorkspacePage } from './pages/ProjectWorkspacePage';
import { LoginPage } from './pages/LoginPage';

function useRouteTitle(pathname: string) {
  if (pathname === '/' || pathname === '') {
    return { title: 'Dashboard', subtitle: 'Workspace overview, recent projects, and next actions.' };
  }
  if (pathname === '/projects') {
    return { title: 'Projects', subtitle: 'Browse analyzed videos and open any project workspace.' };
  }
  if (pathname === '/analyze') {
    return { title: 'Analysis', subtitle: 'Start a new analysis job from a supported video URL.' };
  }
  if (pathname.startsWith('/projects/')) {
    return { title: 'Project Workspace', subtitle: 'Manage candidates, renders, and files for one video.' };
  }
  if (pathname.startsWith('/analyze/')) {
    return { title: 'Project Workspace', subtitle: 'Review candidates and render selected clips.' };
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
  return { title: 'Projects', subtitle: 'Paste a YouTube URL and manage your local video workspaces.' };
}

export function App() {
  const { user, loading, logout } = useAuth();
  const location = useLocation();
  const route = useRouteTitle(location.pathname);

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center bg-surface-950 text-sm text-slate-400">Checking session…</div>;
  }
  if (!user) {
    return location.pathname === '/login' ? <LoginPage /> : <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (location.pathname === '/login') {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="min-h-screen bg-surface-950 text-slate-100">
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar
            title={route.title}
            subtitle={route.subtitle}
            actions={<><span className="text-sm text-slate-400">{user.username}</span><Button type="button" variant="ghost" onClick={() => void logout()}>Sign out</Button>{location.pathname.startsWith('/projects/') || location.pathname.startsWith('/analyze/') ? <Button type="button" variant="secondary" onClick={() => window.history.back()}>Back</Button> : undefined}</>}
          />
          <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
            <div className="mx-auto w-full max-w-7xl">
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/projects" element={<ProjectsPage />} />
                <Route path="/projects/:videoId" element={<ProjectWorkspacePage />} />
                <Route path="/analyze" element={<AnalyzePage />} />
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
