import { request } from './client';
import type {
  LoginResponse,
  SiteSettings,
  User,
  TeacherItem,
  StudentItem,
  CreateTeacherBody,
  CreateStudentBody,
  ImportResult,
  ProblemSummary,
  ProblemDetail,
  ProblemBody,
  TestCase,
  CaseBody,
  AssignmentSummary,
  AssignmentDetail,
  AssignmentBody,
  AssignmentOverview,
  AssignmentStudentRow,
  TeacherSubmissionDetail,
  StudentAssignmentItem,
  StudentAssignmentDetail,
  StudentProblemDetail,
  StudentSubmissionDetail,
  CreateSubmissionResponse,
} from './types';

/* ---------- auth ---------- */

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/auth/login', { method: 'POST', body: { username, password }, anonymous: true });
}

export function getMe(): Promise<User> {
  return request<User>('/auth/me');
}

/* ---------- settings ---------- */

export function getSettings(): Promise<SiteSettings> {
  return request<SiteSettings>('/settings', { anonymous: true });
}

export function updateSettings(body: { brand_color?: string; bg_opacity?: number }): Promise<SiteSettings> {
  return request<SiteSettings>('/admin/settings', { method: 'PUT', body });
}

export function uploadBgImage(file: File): Promise<{ url: string }> {
  const form = new FormData();
  form.append('file', file);
  return request<{ url: string }>('/admin/settings/bg_image', { method: 'POST', form });
}

export function deleteBgImage(): Promise<void> {
  return request<void>('/admin/settings/bg_image', { method: 'DELETE' });
}

/* ---------- admin: teachers ---------- */

export function listTeachers(): Promise<TeacherItem[]> {
  return request<TeacherItem[]>('/admin/teachers');
}

export function createTeacher(body: CreateTeacherBody): Promise<TeacherItem> {
  return request<TeacherItem>('/admin/teachers', { method: 'POST', body });
}

export function updateTeacherActive(id: number, is_active: boolean): Promise<TeacherItem> {
  return request<TeacherItem>(`/admin/teachers/${id}`, { method: 'PATCH', body: { is_active } });
}

export function resetTeacherPassword(id: number, new_password: string): Promise<void> {
  return request<void>(`/admin/teachers/${id}/reset_password`, { method: 'POST', body: { new_password } });
}

export function getTeacherStudents(id: number): Promise<{ student_ids: number[] }> {
  return request<{ student_ids: number[] }>(`/admin/teachers/${id}/students`);
}

export function putTeacherStudents(id: number, studentIds: number[]): Promise<{ student_ids: number[] }> {
  return request<{ student_ids: number[] }>(`/admin/teachers/${id}/students`, { method: 'PUT', body: { student_ids: studentIds } });
}

/* ---------- admin: students ---------- */

export function listStudents(): Promise<StudentItem[]> {
  return request<StudentItem[]>('/admin/students');
}

export function createStudent(body: CreateStudentBody): Promise<StudentItem> {
  return request<StudentItem>('/admin/students', { method: 'POST', body });
}

export function importStudentsCsv(file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append('file', file);
  return request<ImportResult>('/admin/students/import', { method: 'POST', form });
}

export function updateStudentActive(id: number, is_active: boolean): Promise<StudentItem> {
  return request<StudentItem>(`/admin/students/${id}`, { method: 'PATCH', body: { is_active } });
}

export function resetStudentPassword(id: number, new_password: string): Promise<void> {
  return request<void>(`/admin/students/${id}/reset_password`, { method: 'POST', body: { new_password } });
}

/* ---------- teacher: problems ---------- */

export function listTeacherProblems(): Promise<ProblemSummary[]> {
  return request<ProblemSummary[]>('/teacher/problems');
}

export function createTeacherProblem(body: ProblemBody): Promise<ProblemDetail> {
  return request<ProblemDetail>('/teacher/problems', { method: 'POST', body });
}

export function getTeacherProblem(id: number): Promise<ProblemDetail> {
  return request<ProblemDetail>(`/teacher/problems/${id}`);
}

export function updateTeacherProblem(id: number, body: ProblemBody): Promise<ProblemDetail> {
  return request<ProblemDetail>(`/teacher/problems/${id}`, { method: 'PUT', body });
}

export function deleteTeacherProblem(id: number): Promise<void> {
  return request<void>(`/teacher/problems/${id}`, { method: 'DELETE' });
}

export function createCase(problemId: number, body: CaseBody): Promise<TestCase> {
  return request<TestCase>(`/teacher/problems/${problemId}/cases`, { method: 'POST', body });
}

export function updateCase(caseId: number, body: CaseBody): Promise<TestCase> {
  return request<TestCase>(`/teacher/cases/${caseId}`, { method: 'PUT', body });
}

export function deleteCase(caseId: number): Promise<void> {
  return request<void>(`/teacher/cases/${caseId}`, { method: 'DELETE' });
}

/* ---------- teacher: assignments ---------- */

export function listTeacherAssignments(): Promise<AssignmentSummary[]> {
  return request<AssignmentSummary[]>('/teacher/assignments');
}

export function createAssignment(body: AssignmentBody): Promise<AssignmentDetail> {
  return request<AssignmentDetail>('/teacher/assignments', { method: 'POST', body });
}

export function getTeacherAssignment(id: number): Promise<AssignmentDetail> {
  return request<AssignmentDetail>(`/teacher/assignments/${id}`);
}

export function updateAssignment(id: number, body: AssignmentBody): Promise<AssignmentDetail> {
  return request<AssignmentDetail>(`/teacher/assignments/${id}`, { method: 'PUT', body });
}

export function releaseAssignment(id: number): Promise<void> {
  return request<void>(`/teacher/assignments/${id}/release`, { method: 'POST' });
}

export function getAssignmentOverview(id: number): Promise<AssignmentOverview> {
  return request<AssignmentOverview>(`/teacher/assignments/${id}/overview`);
}

export function getAssignmentStudents(id: number): Promise<AssignmentStudentRow[]> {
  return request<AssignmentStudentRow[]>(`/teacher/assignments/${id}/students`);
}

/* ---------- teacher: submissions ---------- */

export function getTeacherSubmission(id: number): Promise<TeacherSubmissionDetail> {
  return request<TeacherSubmissionDetail>(`/teacher/submissions/${id}`);
}

export function rejudgeSubmission(id: number): Promise<void> {
  return request<void>(`/teacher/submissions/${id}/rejudge`, { method: 'POST' });
}

export function setManualScore(id: number, manual_score: number | null): Promise<void> {
  return request<void>(`/teacher/submissions/${id}/score`, { method: 'PATCH', body: { manual_score } });
}

/* ---------- student ---------- */

export function listStudentAssignments(): Promise<StudentAssignmentItem[]> {
  return request<StudentAssignmentItem[]>('/student/assignments');
}

export function getStudentAssignment(id: number): Promise<StudentAssignmentDetail> {
  return request<StudentAssignmentDetail>(`/student/assignments/${id}`);
}

export function getStudentProblem(assignmentId: number, problemId: number): Promise<StudentProblemDetail> {
  return request<StudentProblemDetail>(`/student/assignments/${assignmentId}/problems/${problemId}`);
}

export function createSubmission(assignmentId: number, problemId: number, code_text: string): Promise<CreateSubmissionResponse> {
  return request<CreateSubmissionResponse>(`/student/assignments/${assignmentId}/problems/${problemId}/submissions`, {
    method: 'POST',
    body: { code_text },
  });
}

export function getStudentSubmission(id: number): Promise<StudentSubmissionDetail> {
  return request<StudentSubmissionDetail>(`/student/submissions/${id}`);
}
