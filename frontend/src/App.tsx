import { useMemo } from 'react';
import { FluentProvider } from '@fluentui/react-components';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import type { SiteSettings } from './api/types';
import { getToken, getStoredUser } from './api/client';
import { Layout } from './components/Layout';
import { CHANGE_PASSWORD_PATH, RequireAuth, RequirePasswordChanged, roleHome } from './components/Guard';
import { SettingsProvider, ThemeModeProvider, useSettings, useThemeMode } from './context';
import { buildThemes, resolveBrandColors } from './theme';
import { AppThemeProvider } from './appTheme';

import { LoginPage } from './pages/Login';
import { ForbiddenPage } from './pages/Forbidden';
import { NotFoundPage } from './pages/NotFound';
import { AccountPage } from './pages/Account';
import { ChangePasswordPage } from './pages/ChangePassword';

import { StudentAssignmentList } from './pages/student/AssignmentList';
import { StudentAssignmentDetail } from './pages/student/AssignmentDetail';
import { StudentProblemPage } from './pages/student/ProblemDetail';
import { StudentSubmissionPage } from './pages/student/SubmissionDetail';

import { TeacherProblemList } from './pages/teacher/ProblemList';
import { TeacherProblemEdit } from './pages/teacher/ProblemEdit';
import TeacherStudentList from './pages/teacher/StudentList';
import { TeacherAssignmentList } from './pages/teacher/AssignmentList';
import { TeacherAssignmentNew } from './pages/teacher/AssignmentNew';
import { TeacherAssignmentOverview } from './pages/teacher/AssignmentOverview';
import { TeacherAssignmentStudents } from './pages/teacher/AssignmentStudents';
import { TeacherStudentScores } from './pages/teacher/StudentScores';
import { TeacherSubmissionPage } from './pages/teacher/SubmissionDetail';

import { AdminTeacherList } from './pages/admin/TeacherList';
import { AdminTeacherDetail } from './pages/admin/TeacherDetail';
import { AdminStudentList } from './pages/admin/StudentList';
import { AdminSettingsPage } from './pages/admin/SettingsPage';
import { AuditLogPage } from './pages/admin/AuditLogPage';

function HomeRedirect() {
  const user = getStoredUser();
  if (!getToken() || !user) return <Navigate to="/login" replace />;
  // PW-02：未改密时连首页也要拦到改密页（这条路由不在守卫内，少一跳重定向）。
  if (user.must_change_password) return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  return <Navigate to={roleHome(user.role)} replace />;
}

/** 审计关闭时 /admin/audit 直接送回系统设置（后端同口径 403 AUDIT_DISABLED）。 */
function AdminAuditRoute() {
  const { effective } = useSettings();
  if (effective?.audit_enabled === false) {
    return (
      <Navigate
        to="/admin/settings"
        replace
        state={{ auditNotice: '审计功能当前已关闭：不再记录新日志（历史日志仍保留）。可在此页的「审计日志」卡片重新开启。' }}
      />
    );
  }
  return <AuditLogPage />;
}

function ThemedApp() {
  const { effective } = useSettings();
  const { isDark } = useThemeMode();
  const { light: lightBrand, dark: darkBrand } = resolveBrandColors(effective);
  const themes = useMemo(() => buildThemes(lightBrand, darkBrand), [lightBrand, darkBrand]);

  const theme = isDark ? themes.dark : themes.light;
  return (
    <FluentProvider theme={theme} style={{ minHeight: '100vh', backgroundColor: 'transparent' }}>
      <AppThemeProvider value={theme}>
      <HashRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Layout />}>
            <Route element={<RequireAuth />}>
              {/* 改密页本身必须可达：它躲在 RequirePasswordChanged 之外，
                  但仍要求已登录（后端 /auth/password 走 JWT）。 */}
              <Route path="/change-password" element={<ChangePasswordPage />} />
              {/* PW-02：路由级强制改密拦截——下面这些路由在 must_change_password=true 时全部重定向。 */}
              <Route element={<RequirePasswordChanged />}>
                <Route path="/" element={<HomeRedirect />} />
                <Route path="/403" element={<ForbiddenPage />} />
                <Route path="/account" element={<AccountPage />} />
                <Route element={<RequireAuth roles={['student']} />}>
                  <Route path="/student/assignments" element={<StudentAssignmentList />} />
                  <Route path="/student/assignments/:id" element={<StudentAssignmentDetail />} />
                  <Route path="/student/assignments/:id/problems/:pid" element={<StudentProblemPage />} />
                  <Route path="/student/submissions/:sid" element={<StudentSubmissionPage />} />
                </Route>
                <Route element={<RequireAuth roles={['teacher']} />}>
                  <Route path="/teacher/problems" element={<TeacherProblemList />} />
                  <Route path="/teacher/problems/:id" element={<TeacherProblemEdit />} />
                  <Route path="/teacher/assignments" element={<TeacherAssignmentList />} />
                  <Route path="/teacher/assignments/new" element={<TeacherAssignmentNew />} />
                  <Route path="/teacher/assignments/:id" element={<TeacherAssignmentOverview />} />
                  <Route path="/teacher/assignments/:id/students" element={<TeacherAssignmentStudents />} />
                  <Route path="/teacher/assignments/:id/students/:sid" element={<TeacherStudentScores />} />
                  <Route path="/teacher/students" element={<TeacherStudentList />} />
                  <Route path="/teacher/submissions/:sid" element={<TeacherSubmissionPage />} />
                </Route>
                <Route element={<RequireAuth roles={['admin']} />}>
                  <Route path="/admin/teachers" element={<AdminTeacherList />} />
                  <Route path="/admin/teachers/:id" element={<AdminTeacherDetail />} />
                  <Route path="/admin/students" element={<AdminStudentList />} />
                  <Route path="/admin/audit" element={<AdminAuditRoute />} />
                  <Route path="/admin/settings" element={<AdminSettingsPage />} />
                </Route>
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </HashRouter>
      </AppThemeProvider>
    </FluentProvider>
  );
}

export default function App({ initialSettings }: { initialSettings: SiteSettings | null }) {
  return (
    <SettingsProvider initial={initialSettings}>
      <ThemeModeProvider>
        <ThemedApp />
      </ThemeModeProvider>
    </SettingsProvider>
  );
}
