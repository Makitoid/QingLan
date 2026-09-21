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
  StudentListQuery,
  TeacherGroups,
  TempCredential,
  BatchResetMode,
  BatchResetResult,
  AuditLogPage,
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
  ClassItem,
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

/**
 * 把可选筛选参数拼成 query string：空串 / null / undefined 一律不上送，
 * 保证「参数缺省时行为与旧接口完全一致」（LI-01）。
 */
function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    usp.set(key, String(value));
  });
  const s = usp.toString();
  return s ? `?${s}` : '';
}

/** LI-02：布尔筛选 → 后端约定的 '1' / '0'；null / undefined = 不筛选。 */
function flagParam(value?: boolean | null): string | undefined {
  if (value === null || value === undefined) return undefined;
  return value ? '1' : '0';
}

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

/** LI-01：`q` 匹配工号 / 姓名，缺省时与旧接口行为一致。 */
export function listTeachers(q?: string): Promise<TeacherItem[]> {
  return request<TeacherItem[]>(`/admin/teachers${queryString({ q: q?.trim() })}`);
}

/** PW-01：新建教师不再传密码——后端统一发放初始密码并置 `must_change_password=1`。 */
export function createTeacher(body: CreateTeacherBody): Promise<TeacherItem> {
  return request<TeacherItem>('/admin/teachers', { method: 'POST', body });
}

export function updateTeacherActive(id: number, is_active: boolean): Promise<TeacherItem> {
  return request<TeacherItem>(`/admin/teachers/${id}`, { method: 'PATCH', body: { is_active } });
}

/**
 * PW-04：重置教师密码——无请求体，后端生成 8 位随机密码并在响应里返回给管理员转告本人。
 * 一次性凭证只能经响应拿到，所以这里返回 `TempCredential`（PW-09）。
 */
export function resetTeacherPassword(id: number): Promise<TempCredential> {
  return request<TempCredential>(`/admin/teachers/${id}/reset_password`, { method: 'POST' });
}

/** BD-06：admin 直绑写接口（PUT）已删除，这里只保留只读查看。 */
export function getTeacherStudents(id: number): Promise<{ student_ids: number[] }> {
  return request<{ student_ids: number[] }>(`/admin/teachers/${id}/students`);
}

/** BD-02：读取该教师可教的组别（层 2）。 */
export function getTeacherGroups(id: number): Promise<TeacherGroups> {
  return request<TeacherGroups>(`/admin/teachers/${id}/groups`);
}

/** BD-02：全量替换该教师可教的组别；后端写审计 `teacher_group_assign`。 */
export function putTeacherGroups(id: number, groupIds: number[]): Promise<TeacherGroups> {
  return request<TeacherGroups>(`/admin/teachers/${id}/groups`, {
    method: 'PUT',
    body: { group_ids: groupIds },
  });
}

/* ---------- admin: students ---------- */

/** LI-01 / LI-02：`?q=&group_id=&must_change=0|1`，全部缺省即旧行为。 */
export function listStudents(query: StudentListQuery = {}): Promise<StudentItem[]> {
  return request<StudentItem[]>(
    `/admin/students${queryString({
      q: query.q?.trim(),
      group_id: query.group_id ?? undefined,
      must_change: flagParam(query.must_change),
    })}`,
  );
}

/** PW-01：新建学生不传密码，初始密码由系统统一发放。 */
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

/** PW-04：单个重置无请求体，响应返回随机密码明细（PW-09）。 */
export function resetStudentPassword(id: number): Promise<TempCredential> {
  return request<TempCredential>(`/admin/students/${id}/reset_password`, { method: 'POST' });
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

/**
 * PW-06：批量重置。`mode='unified'` 全员统一初始密码（整批一次哈希、不过期），
 * `mode='random'` 逐生独立随机 8 位密码。两种模式都返回逐生凭证明细，由前端拼 CSV（PW-09）。
 */
export function adminBatchResetPassword(
  studentIds: number[],
  mode: BatchResetMode,
): Promise<BatchResetResult> {
  return request<BatchResetResult>('/admin/students/batch_reset_password', {
    method: 'POST',
    body: { student_ids: studentIds, mode },
  });
}

/** 批量启用 / 停用学生账号。 */
export function adminBatchActive(studentIds: number[], isActive: boolean): Promise<SuccessResult> {
  return request<SuccessResult>('/admin/students/batch_active', {
    method: 'POST',
    body: { student_ids: studentIds, is_active: isActive },
  });
}

/* ---------- admin: 审计日志（AU-05 / AU-06） ---------- */

/** 只读、按 created_at 倒序；分页靠 `limit` / `offset`，`total` 判断是否还有下一页。 */
export function listAuditLogs(params: {
  action?: string;
  targetType?: string;
  limit: number;
  offset: number;
}): Promise<AuditLogPage> {
  return request<AuditLogPage>(
    `/admin/audit_logs${queryString({
      action: params.action?.trim(),
      target_type: params.targetType?.trim(),
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

/* ---------- 分组（GR-01：管理员是唯一写者） ---------- */

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

/* ---------- teacher: 学生名单（层 3，教师是唯一写者；组别本身对教师只读） ---------- */

/**
 * LI-01：我的学生名单，`q` 匹配学号 / 姓名。
 * GR-02 起教师端不再有 `GET /teacher/groups` 与 `POST /teacher/students/group_members`：
 * 可见的组一律经 `listTeacherClasses()` 拿。
 */
export function listTeacherStudents(q?: string): Promise<BoundStudentItem[]> {
  return request<BoundStudentItem[]>(`/teacher/students${queryString({ q: q?.trim() })}`);
}

/** BD-03：我可教的组（经 `teacher_groups` 过滤）及其成员，只读。 */
export function listTeacherClasses(): Promise<ClassItem[]> {
  return request<ClassItem[]>('/teacher/classes');
}

/** BD-03：从可教组里把学生拉进自己的名单；有任一学生不在可教组时整批 403。幂等。 */
export function teacherBindFromClass(studentIds: number[]): Promise<BatchResult> {
  return request<BatchResult>('/teacher/students/bind_from_class', {
    method: 'POST',
    body: { student_ids: studentIds },
  });
}

/** BD-04：按学生 id 兜底添加（转学生 / 旁听等暂不在组的情况）。 */
export function teacherBindStudents(studentIds: number[]): Promise<BatchResult> {
  return request<BatchResult>('/teacher/students/bind', {
    method: 'POST',
    body: { student_ids: studentIds },
  });
}

/** BD-05：把自己的名单里的学生移出；历史提交与成绩保留。幂等。 */
export function teacherUnbindStudents(studentIds: number[]): Promise<BatchResult> {
  return request<BatchResult>('/teacher/students/unbind', {
    method: 'POST',
    body: { student_ids: studentIds },
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
