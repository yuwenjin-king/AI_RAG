import { lazy, Suspense, useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Spin } from 'antd';
import AppLayout from './components/AppLayout';
import LoginPage from './pages/LoginPage';
import { useAuth } from './stores/auth';
import { useTenant } from './stores/tenant';
import { fetchMe } from './api/auth';

// 路由级懒加载（plan_four §4）：拆分 chunk——pdfjs-dist 仅 /preview 需要，
// 不再打进首屏主 bundle。其余页面同样按需加载，缩小初始体积。
const ChatPage = lazy(() => import('./pages/ChatPage'));
const KnowledgeBasesPage = lazy(() => import('./pages/KnowledgeBasesPage'));
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'));
const DocumentPreviewPage = lazy(() => import('./pages/DocumentPreviewPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));

function PageFallback() {
  return (
    <div style={{ minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Spin />
    </div>
  );
}

/**
 * 启动守卫：调 /auth/me 探测登录态。
 * - authenticated=true  → 主应用（status=authed）
 * - authenticated=false → 认证未开启，匿名直进（status=guest）
 * - 401                 → 登录页（status=needs-login）
 */
export default function App() {
  const status = useAuth((s) => s.status);
  const setProfile = useAuth((s) => s.setProfile);
  const setStatus = useAuth((s) => s.setStatus);
  const tenantId = useTenant((s) => s.tenantId);
  const setTenantId = useTenant((s) => s.setTenantId);

  useEffect(() => {
    if (status !== 'unknown') return;
    let cancelled = false;
    fetchMe()
      .then((p) => {
        if (cancelled) return;
        setProfile(p);
        setStatus(p.authenticated ? 'authed' : 'guest');
        // 登录态：确保活动租户是成员租户（防止本地存的旧值越权）
        if (p.authenticated) {
          const members = new Set([p.tenant_id, ...Object.keys(p.memberships || {})]);
          if (!members.has(tenantId)) setTenantId(p.tenant_id);
        }
      })
      .catch(() => {
        if (!cancelled) setStatus('needs-login');
      });
    return () => {
      cancelled = true;
    };
    // 仅在未探测时执行一次；tenantId 仅在闭包内读取
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  if (status === 'unknown') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (status === 'needs-login') {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/knowledge-bases" element={<KnowledgeBasesPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/preview/:docId/:chunkId" element={<DocumentPreviewPage />} />
          <Route path="/admin" element={<AdminPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
