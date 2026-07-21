import { useEffect, useRef, useState } from 'react';
import { Alert, Card, Spin, Typography } from 'antd';
import { useParams } from 'react-router-dom';
import * as pdfjsLib from 'pdfjs-dist';
// vite 以 URL 形式提供 worker
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { DocApi } from '../api/resources';
import type { LocateResp } from '../api/types';

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

const { Title, Text, Paragraph } = Typography;

export default function DocumentPreviewPage() {
  const { docId, chunkId } = useParams<{ docId: string; chunkId: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [loc, setLoc] = useState<LocateResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    if (!docId || !chunkId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const info = await DocApi.locate(Number(docId), Number(chunkId));
        if (cancelled) return;
        setLoc(info);
        if (!info.preview_url) {
          setLoading(false);
          return;
        }
        const pdf = await pdfjsLib.getDocument({ url: info.preview_url }).promise;
        if (cancelled) return;
        const pageNo = info.page_no ?? 1;
        const page = await pdf.getPage(pageNo);
        const canvas = canvasRef.current!;
        const viewport = page.getViewport({ scale: 1.6 });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
        // 按 bbox 画高亮层（归一化坐标 × 视口尺寸）
        if (overlayRef.current && info.bbox) {
          const [x0, y0, x1, y1] = info.bbox;
          Object.assign(overlayRef.current.style, {
            left: `${x0 * viewport.width}px`,
            top: `${y0 * viewport.height}px`,
            width: `${(x1 - x0) * viewport.width}px`,
            height: `${(y1 - y0) * viewport.height}px`,
          });
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [docId, chunkId]);

  return (
    <Card>
      <Title level={4}>{loc?.title || `文档 #${docId}`}</Title>
      <Paragraph type="secondary">
        区域级溯源：第 {loc?.page_no ?? '?'} 页 / bbox ={' '}
        {loc?.bbox ? `[${loc.bbox.map((n) => n.toFixed(3)).join(', ')}]` : '（无）'}
      </Paragraph>

      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}

      {loading && <Spin tip="加载原文与定位…" />}

      {!loading && loc && !loc.preview_url && (
        <Alert
          type="info"
          message="原文预览不可用（对象存储未配置 / 未上传原文件）"
          description="后端已返回页码与 bbox 定位信息；配置 MinIO 或上传原始 PDF 后可在此看到高亮渲染。"
        />
      )}

      {loc?.preview_url && (
        <div style={{ position: 'relative', display: 'inline-block' }}>
          <canvas ref={canvasRef} />
          <div
            ref={overlayRef}
            style={{
              position: 'absolute',
              border: '2px solid #ff4d4f',
              background: 'rgba(255, 77, 79, 0.18)',
              boxSizing: 'border-box',
              pointerEvents: 'none',
            }}
          />
        </div>
      )}
    </Card>
  );
}
