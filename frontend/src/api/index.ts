import dayjs from 'dayjs';
import { downloadBlob, request } from './client';
import type {
  LoginResponse,
  SiteSettings,
  BrandColorSource,
  BgMode,
  User,
  TeacherItem,
  StudentItem,
  CreateTeacherBody,
  CreateStudentBody,
  ImportResult,
  ProblemSummary,
  ProblemDetail,
  ProblemBody,
  ProblemDraft,
  GroupItem,
  GroupMembershipAction,
  BoundStudentItem,
  BatchResult,
  SuccessResult,
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

export function updateSettings(body: {
  brand_color?: string;
  brand_color_dark?: string;
  brand_color_source?: BrandColorSource;
  bg_dual?: boolean;
  bg_opacity?: number;
}): Promise<SiteSettings> {
  return request<SiteSettings>('/admin/settings', { method: 'PUT', body });
}

export function uploadBgImage(file: File | Blob, mode: BgMode = 'light'): Promise<{ url: string }> {
  const form = new FormData();
  form.append('file', file, file instanceof File ? file.name : `${mode}.jpg`);
  return request<{ url: string }>(`/admin/settings/bg_image?mode=${mode}`, { method: 'POST', form });
}

export function deleteBgImage(mode: BgMode = 'light'): Promise<SiteSettings> {
  return request<SiteSettings>(`/admin/settings/bg_image?mode=${mode}`, { method: 'DELETE' });
}

/* ---------- account ---------- */

export function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  return request<void>('/auth/password', {
    method: 'POST',
    body: { old_password: oldPassword, new_password: newPassword },
  });
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

export function importStudents(file: File): Promise<ImportResult> {
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

/* ---------- admin: 学生批量操作 ---------- */

/** 批量把学生加入 / 移出分组；后端单事务，整批成功或整批失败。 */
export function adminBatchGroupMembers(
  studentIds: number[],
  groupIds: number[],
  action: GroupMembershipAction,
): Promise<BatchResult> {
  return request<BatchResult>('/admin/students/group_members', {
    method: 'POST',
    body: { student_ids: studentIds, group_ids: groupIds, action },
  });
}

/** 批量重置密码（后端只算一次 hash 复用到 N 行）。仅管理员有此接口。 */
export function adminBatchResetPassword(studentIds: number[], newPassword: string): Promise<SuccessResult> {
  return request<SuccessResult>('/admin/students/batch_reset_password', {
    method: 'POST',
    body: { student_ids: studentIds, new_password: newPassword },
  });
}

/** 批量启用 / 停用学生账号。 */
export function adminBatchActive(studentIds: number[], isActive: boolean): Promise<SuccessResult> {
  return request<SuccessResult>('/admin/students/batch_active', {
    method: 'POST',
    body: { student_ids: studentIds, is_active: isActive },
  });
}

/* ---------- 分组（管理员：完整 CRUD；教师端只读，见 listTeacherGroups） ---------- */

export function listGroups(): Promise<GroupItem[]> {
  return request<GroupItem[]>('/admin/groups');
}

/** 新建分组；重名返回 409 GROUP_NAME_EXISTS。 */
export function createGroup(name: string): Promise<GroupItem> {
  return request<GroupItem>('/admin/groups', { method: 'POST', body: { name } });
}

/** 重命名分组；404 GROUP_NOT_FOUND / 409 GROUP_NAME_EXISTS。 */
export function renameGroup(id: number, name: string): Promise<GroupItem> {
  return request<GroupItem>(`/admin/groups/${id}`, { method: 'PATCH', body: { name } });
}

/** 删除分组，成员关系级联删除。 */
export function deleteGroup(id: number): Promise<void> {
  return request<void>(`/admin/groups/${id}`, { method: 'DELETE' });
}

/* ---------- teacher: 学生与分组（教师端无任何密码相关接口） ---------- */

/** 我绑定的学生（含分组）。 */
export function listTeacherStudents(): Promise<BoundStudentItem[]> {
  return request<BoundStudentItem[]>('/teacher/students');
}

/** 全站分组定义，教师端只读。 */
export function listTeacherGroups(): Promise<GroupItem[]> {
  return request<GroupItem[]>('/teacher/groups');
}

/** 批量调整自己绑定学生的组成员关系；含未绑定学生时后端 403 整批拒绝。 */
export function teacherBatchGroupMembers(
  studentIds: number[],
  groupIds: number[],
  action: GroupMembershipAction,
): Promise<BatchResult> {
  return request<BatchResult>('/teacher/students/group_members', {
    method: 'POST',
    body: { student_ids: studentIds, group_ids: groupIds, action },
  });
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

/** 保存题目草稿（每题仅一份，新草稿覆盖旧草稿）；正式保存成功后由服务端清空。 */
export function saveProblemDraft(id: number, draft: ProblemDraft): Promise<void> {
  return request<void>(`/teacher/problems/${id}/draft`, { method: 'PUT', body: draft });
}

/** 丢弃草稿，回到已保存内容。 */
export function deleteProblemDraft(id: number): Promise<void> {
  return request<void>(`/teacher/problems/${id}/draft`, { method: 'DELETE' });
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

/**
 * 导出场次学生成绩 xlsx（浏览器直接落盘）。
 * tz_offset 传本地时区的分钟偏移（dayjs().utcOffset()），后端按它转换 UTC 时间。
 */
export function exportAssignmentStudents(id: number): Promise<void> {
  return downloadBlob(`/teacher/assignments/${id}/export?tz_offset=${dayjs().utcOffset()}`, `学生成绩-${id}.xlsx`);
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
