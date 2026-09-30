import { useEffect, useSyncExternalStore } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { getCachedUser, getToken, subscribeAuth, updateStoredUser } from '../api/client';
import { getMe } from '../api';
import type { Role, User } from '../api/types';

/** PW-02：强制改密页的路径——拦截期间唯一可访问的应用内路由。 */
export const CHANGE_PASSWORD_PATH = '/change-password';

/**
 * 响应式的登录态。`getStoredUser()` 读的是 localStorage，改了不会重渲染；
 * PW-02 的拦截要在「改密成功」「后端回 403」时立即放开，所以统一走这条订阅。
 */
export function useAuthUser(): User | null {
  return useSyncExternalStore(subscribeAuth, getCachedUser, getCachedUser);
}

export function RequireAuth({ roles }: { roles?: Role[] }) {
  const user = useAuthUser();
  if (!getToken() || !user) {
    return <Navigate to="/login" replace />;
  }
  if (roles && !roles.includes(user.role)) {
    return <Navigate to="/403" replace />;
  }
  return <Outlet />;
}

/**
 * PW-02 强制改密拦截（路由级，不是可关闭的弹窗）。
 *
 * `must_change_password=true` 时除 `/change-password` 外一律重定向；
 * 挂载时再拉一次 `/auth/me` 校准本地登录态——localStorage 里可能是旧的 false
 * （例如管理员刚重置过密码），刷新页面也能据此恢复拦截态。
 * 后端同时用 403 MUST_CHANGE_PASSWORD 兜底（见 `api/client.ts`）。
 */
export function RequirePasswordChanged() {
  const user = useAuthUser();
  const { pathname } = useLocation();

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    getMe()
      .then((me) => {
        if (cancelled) return;
        const current = getCachedUser();
        if (!current) return;
        const patch: Partial<User> = {};
        if (me.username !== current.username) patch.username = me.username;
        if (me.display_name !== current.display_name) patch.display_name = me.display_name;
        if (me.role !== current.role) patch.role = me.role;
        if (me.must_change_password !== current.must_change_password) {
          patch.must_change_password = me.must_change_password;
        }
        if (Object.keys(patch).length > 0) updateStoredUser(patch);
      })
      // 拉取失败（含 401 已被 client 处理成跳登录）不打断渲染，本地状态照常工作。
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (user?.must_change_password && pathname !== CHANGE_PASSWORD_PATH) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  }
  return <Outlet />;
}

export function roleHome(role: Role): string {
  switch (role) {
    case 'admin':
      return '/admin/teachers';
    case 'teacher':
      return '/teacher/assignments';
    case 'student':
      return '/student/assignments';
  }
}
