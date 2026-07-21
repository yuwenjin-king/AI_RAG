/** 后端共享类型（与 backend/app/schemas 对齐）。 */

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface KnowledgeBase {
  id: number;
  tenant_id: string;
  name: string;
  description?: string;
  retrieval_config?: Record<string, any>;
  prompt_template_id?: string | null;
  is_active: boolean;
  created_at?: string;
}

export type DocStatus = 'pending' | 'parsing' | 'chunking' | 'embedding' | 'indexed' | 'failed';

export interface DocumentItem {
  id: number;
  tenant_id: string;
  knowledge_base_id?: number | null;
  title: string;
  content_type: string;
  size_bytes: number;
  status: DocStatus;
  embedding_status: string;
  error?: string | null;
  meta?: Record<string, any>;
  created_at?: string;
}

export interface Citation {
  chunk_id?: number | null;
  doc_id: number;
  title?: string;
  page_no?: number | null;
  bbox?: [number, number, number, number] | null;
  snippet?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  citations?: Citation[];
  degraded?: string[];
  conversation_id?: number;
}

export interface UploadUrlResp {
  doc_id: number;
  object_key: string;
  upload_url: string | null;
  direct_upload_url: string | null;
}

export interface LocateResp {
  chunk_id: number;
  doc_id: number;
  title: string;
  page_no?: number | null;
  bbox?: [number, number, number, number] | null;
  preview_url?: string | null;
}

export interface SceneConfig {
  id?: number;
  tenant_id?: string;
  scene_id: string;
  name: string;
  knowledge_base_ids: number[];
  retrieval_config?: Record<string, any>;
  prompt_template?: string | null;
  model_route?: Record<string, any>;
  permission_rules?: Record<string, any>;
  is_active: boolean;
}
