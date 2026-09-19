import imageCompression from 'browser-image-compression';
import chroma from 'chroma-js';

export const MAX_BG_BYTES = 5 * 1024 * 1024;
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const ACCEPT_ATTR = '.jpg,.jpeg,.png,.webp';

const COMPRESS_TARGET_MB = 2;
const COMPRESS_MAX_EDGE = 2560;

export function formatMB(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

const EXT_BY_TYPE: Record<string, string> = { 'image/png': '.png', 'image/webp': '.webp', 'image/jpeg': '.jpg' };

function renameToType(file: File, type: string): File {
  const ext = EXT_BY_TYPE[type] ?? '.jpg';
  return new File([file], `${file.name.replace(/\.[^.]+$/, '')}${ext}`, { type });
}

// 服务端按扩展名校验格式，所以压缩后要把文件名同步成真实输出格式
export async function compressImage(file: File, type: string = file.type): Promise<File> {
  const out = await imageCompression(file, {
    maxSizeMB: COMPRESS_TARGET_MB,
    maxWidthOrHeight: COMPRESS_MAX_EDGE,
    initialQuality: 0.85,
    useWebWorker: true,
    fileType: type,
  });
  return renameToType(out, type);
}

const SAMPLE_EDGE = 64;
const HUE_BUCKET_DEG = 15;

// 取"最能代表这张图"的颜色：丢掉近黑/近白/灰的像素，按色相分桶投票（饱和度高的票更重），
// 再把中选色校正到适合当品牌色的明度/饱和度区间。
export async function extractBrandColor(file: Blob): Promise<string | null> {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement('canvas');
  canvas.width = SAMPLE_EDGE;
  canvas.height = SAMPLE_EDGE;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) {
    bitmap.close();
    return null;
  }
  ctx.drawImage(bitmap, 0, 0, SAMPLE_EDGE, SAMPLE_EDGE);
  bitmap.close();

  const { data } = ctx.getImageData(0, 0, SAMPLE_EDGE, SAMPLE_EDGE);
  const buckets = new Map<number, { r: number; g: number; b: number; n: number; score: number }>();
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 200) continue;
    const [hue, sat, light] = chroma(data[i], data[i + 1], data[i + 2]).hsl();
    if (!Number.isFinite(hue) || sat < 0.12 || light < 0.12 || light > 0.9) continue;
    const key = Math.floor(hue / HUE_BUCKET_DEG);
    const bucket = buckets.get(key) ?? { r: 0, g: 0, b: 0, n: 0, score: 0 };
    bucket.r += data[i];
    bucket.g += data[i + 1];
    bucket.b += data[i + 2];
    bucket.n += 1;
    bucket.score += 0.5 + sat;
    buckets.set(key, bucket);
  }

  const best = [...buckets.values()].sort((a, b) => b.score - a.score)[0];
  if (!best) return null;

  const [hue, sat, light] = chroma(best.r / best.n, best.g / best.n, best.b / best.n).hsl();
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
  return chroma
    .hsl(Number.isFinite(hue) ? hue : 210, clamp(sat, 0.5, 0.85), clamp(light, 0.34, 0.5))
    .hex();
}
