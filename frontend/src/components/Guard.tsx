import { Navigate, Outlet } from 'react-router-dom';
import { getToken, getStoredUser } from '../api/client';
import type { Role } from '../api/types';

export function RequireAuth({ roles }: { roles: Role[] }) {
  const token = getToken();
  const user = getStoredUser();
  if (!token || !user) {
    return <Navigate to="/login" replace />;
  }
  if (!roles.includes(user.role)) {
    return <Navigate to="/403" replace />;
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
