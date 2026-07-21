import { Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import ChatPage from './pages/ChatPage';
import KnowledgeBasesPage from './pages/KnowledgeBasesPage';
import DocumentsPage from './pages/DocumentsPage';
import DocumentPreviewPage from './pages/DocumentPreviewPage';
import AdminPage from './pages/AdminPage';

export default function App() {
  return (
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
  );
}
