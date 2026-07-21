import { api, uploadFile } from './client';
import type {
  DocumentItem,
  KnowledgeBase,
  LocateResp,
  Page,
  SceneConfig,
  UploadUrlResp,
} from './types';

/* ===== 知识库 ===== */
export const KBApi = {
  list: () => api<Page<KnowledgeBase>>('/api/v1/knowledge-bases?page=1&page_size=200'),
  create: (body: Partial<KnowledgeBase>) =>
    api<KnowledgeBase>('/api/v1/knowledge-bases', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: number, body: Partial<KnowledgeBase>) =>
    api<KnowledgeBase>(`/api/v1/knowledge-bases/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  remove: (id: number) =>
    api<{ ok: boolean }>(`/api/v1/knowledge-bases/${id}`, { method: 'DELETE' }),
};

/* ===== 文档 ===== */
export const DocApi = {
  uploadUrl: (filename: string, contentType = 'application/octet-stream', kbId?: number) =>
    api<UploadUrlResp>('/api/v1/documents/upload-url', {
      method: 'POST',
      body: JSON.stringify({ filename, content_type: contentType, knowledge_base_id: kbId }),
    }),
  /** 直传（multipart）—— MinIO 不可用或小文件用此；服务端存对象存储后触发 ingest。 */
  directUpload: (docId: number, file: File) =>
    uploadFile(`/api/v1/documents/${docId}/upload`, file),
  /** 预签名 PUT 上传完成后调用，触发 ingest。 */
  finalize: (docId: number) =>
    api<DocumentItem>(`/api/v1/documents/${docId}/finalize`, { method: 'POST' }),
  list: (params: { kbId?: number; status?: string; page?: number; page_size?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.kbId) q.set('knowledge_base_id', String(params.kbId));
    if (params.status) q.set('status', params.status);
    q.set('page', String(params.page ?? 1));
    q.set('page_size', String(params.page_size ?? 50));
    return api<Page<DocumentItem>>(`/api/v1/documents?${q.toString()}`);
  },
  locate: (docId: number, chunkId: number) =>
    api<LocateResp>(`/api/v1/documents/${docId}/locate?chunk_id=${chunkId}`),
};

/* ===== 场景配置 ===== */
export const SceneApi = {
  get: (sceneId: string) => api<SceneConfig | null>(`/api/v1/admin/scenes/${sceneId}`),
  upsert: (sceneId: string, body: Omit<SceneConfig, 'id' | 'tenant_id'>) =>
    api<SceneConfig>(`/api/v1/admin/scenes/${sceneId}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
};
