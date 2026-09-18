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
    throw new ApiError(0, { code: 'NETWORK_ERROR', message: '无法连接服务器，请检查网络或稍后重试' });
  }

  if (resp.status === 401 && !options.anonymous) {
    redirectToLogin();
    throw new ApiError(401, { code: 'UNAUTHORIZED', message: '登录已过期，请重新登录' });
  }

  if (resp.status === 204) {
    return undefined as T;
  }

  const text = await resp.text();
  const data = text ? (JSON.parse(text) as unknown) : null;

  if (!resp.ok) {
    const body = (data ?? { code: 'UNKNOWN', message: `请求失败（HTTP ${resp.status}）` }) as Partial<ApiErrorBody>;
    throw new ApiError(resp.status, {
      code: body.code ?? 'UNKNOWN',
      message: body.message ?? `请求失败（HTTP ${resp.status}）`,
    });
  }

  return data as T;
}
