import type { ApiErrorBody, User } from './types';

const TOKEN_KEY = 'qinglan-token';
const USER_KEY = 'qinglan-user';

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.code = body.code;
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuth(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function redirectToLogin(): void {
  clearAuth();
  if (!window.location.hash.startsWith('#/login')) {
    window.location.hash = '#/login';
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  anonymous?: boolean;
}

const NETWORK_ERROR_BODY: ApiErrorBody = {
  code: 'NETWORK_ERROR',
  message: '无法连接服务器，请检查网络或稍后重试',
};

const UNAUTHORIZED_BODY: ApiErrorBody = {
  code: 'UNAUTHORIZED',
  message: '登录已过期，请重新登录',
};

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token && !options.anonymous) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  let payload: BodyInit | undefined;
  if (options.form) {
    payload = options.form;
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(options.body);
  }

  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: payload,
    });
  } catch {
    throw new ApiError(0, NETWORK_ERROR_BODY);
  }

  if (resp.status === 401 && !options.anonymous) {
    redirectToLogin();
    throw new ApiError(401, UNAUTHORIZED_BODY);
  }

  if (resp.status === 204) {
    return undefined as T;
  }

  const text = await resp.text();
  if (!text) {
    return null as T;
  }
  let data: unknown;
  try {
    data = JSON.parse(text) as unknown;
  } catch {
    // 后端崩溃时 Starlette 返回纯文本（如 "Internal Server Error"），
    // 不能直接把 SyntaxError 抛给页面。
    if (!resp.ok) {
      data = null;
    } else {
      throw new ApiError(resp.status, { code: 'UNKNOWN', message: '服务器响应格式异常，请稍后重试' });
    }
  }

  if (!resp.ok) {
    const body = (data ?? { code: 'UNKNOWN', message: `请求失败（HTTP ${resp.status}）` }) as Partial<ApiErrorBody>;
    throw new ApiError(resp.status, {
      code: body.code ?? 'UNKNOWN',
      message: body.message ?? `请求失败（HTTP ${resp.status}）`,
    });
  }

  return data as T;
}

/**
 * 从 Content-Disposition 解析文件名：优先 RFC5987 的 `filename*=UTF-8''...`，
 * 再回退到普通的 `filename="..."`，最后回退到调用方给的文件名。
 */
function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;

  const encoded = /filename\*\s*=\s*([^']*)''([^;]*)/i.exec(header);
  if (encoded?.[2]) {
    const name = encoded[2].trim().replace(/^"|"$/g, '');
    if (name) {
      try {
        return decodeURIComponent(name);
      } catch {
        return name;
      }
    }
  }

  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  const base = plain?.[1]?.trim();
  if (!base) return fallback;
  try {
    return decodeURIComponent(base);
  } catch {
    return base;
  }
}

/**
 * 下载受 JWT 保护的二进制接口（如成绩导出）。
 *
 * 必须手动 fetch：`<a href>` 直链带不上 Authorization 头，会被后端判为 401。
 * 错误响应先用 text() 取出再尝试 JSON.parse，避免对非 JSON 错误体直接 .json() 抛解析异常。
 */
export async function downloadBlob(path: string, fallbackFilename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, { method: 'GET', headers });
  } catch {
    throw new ApiError(0, NETWORK_ERROR_BODY);
  }

  if (resp.status === 401) {
    redirectToLogin();
    throw new ApiError(401, UNAUTHORIZED_BODY);
  }

  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    let body: Partial<ApiErrorBody> | null = null;
    if (text) {
      try {
        body = JSON.parse(text) as Partial<ApiErrorBody>;
      } catch {
        body = null;
      }
    }
    throw new ApiError(resp.status, {
      code: body?.code ?? 'DOWNLOAD_FAILED',
      message: body?.message ?? `下载失败（HTTP ${resp.status}）`,
    });
  }

  const blob = await resp.blob();
  const filename = filenameFromDisposition(resp.headers.get('Content-Disposition'), fallbackFilename);
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // 立刻 revoke 会让部分浏览器（Firefox）拿不到数据，留一个短延时。
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
