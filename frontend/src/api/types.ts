export type Role = 'admin' | 'teacher' | 'student';

export interface User {
  id: number;
  username: string;
  role: Role;
  display_name: string;
  /**
   * PW-02：true 时该账号必须先改密才能继续使用。
   * 前端在路由级拦截（`Guard.RequirePasswordChanged`），后端业务 API 同时返回 403 MUST_CHANGE_PASSWORD。
   * `/auth/me` 也带该字段，所以刷新页面能恢复拦截态。
   */
  must_change_password: boolean;
}

export interface LoginResponse {
  token: string;
  user: User;
}

export interface ApiErrorBody {
  code: string;
  message: string;
}

/* ---------- settings ---------- */

export type BrandColorSource = 'manual' | 'image';
export type BgMode = 'light' | 'dark';

export interface SiteSettings {
  brand_color: string;
  /** 暗色模式专属品牌色；null 表示暗色沿用 brand_color。 */
  brand_color_dark: string | null;
  brand_color_source: BrandColorSource;
  bg_image_url: string | null;
  bg_image_url_dark: string | null;
  bg_dual: boolean;
  bg_opacity: number;
}

/* ---------- groups（学生分组 / 班级，全站共享，管理员维护） ---------- */

/** 分组的精简引用，随学生一起返回。 */
export interface GroupRef {
  id: number;
  name: string;
}

/** 分组定义 + 成员数，对应后端 GroupOut。 */
export interface GroupItem extends GroupRef {
  member_count: number;
}

/** 教师端「我的学生」行，对应后端 BoundStudentOut（无归属教师字段）。 */
export interface BoundStudentItem {
  id: number;
  username: string;
  display_name: string;
  is_active: boolean;
  /** LI-02：未改密徽标。 */
  must_change_password: boolean;
  groups: GroupRef[];
}

/**
 * BD-03：可教组（`teacher_groups` 过滤后的行政班）里的一名成员。
 * `bound` = 已在自己的学生名单中，前端据此把「拉入」按钮置灰。
 */
export interface ClassStudentItem {
  id: number;
  username: string;
  display_name: string;
  is_active: boolean;
  bound: boolean;
}

/** BD-03：`GET /api/teacher/classes` 的一个组（含成员）。 */
export interface ClassItem {
  id: number;
  name: string;
  member_count: number;
  students: ClassStudentItem[];
}

/** 组成员批量写入的返回体，对应后端 GroupMembershipOut。 */
export interface BatchResult {
  success_count: number;
}

/** 只报成败的批量接口返回体，对应后端 SuccessOut。 */
export interface SuccessResult {
  success: boolean;
}

/** 组成员批量写入方向。 */
export type GroupMembershipAction = 'add' | 'remove';

/* ---------- 密码凭证（PW-04 / PW-06 / PW-09） ---------- */

/**
 * 重置密码返回的一行凭证（学生与教师同构，教师复用 `student_id` 字段放教师 id）。
 * `expires_at` 为 UTC 串；null = 不过期（统一/初始密码，PW-05）。
 */
export interface TempCredential {
  student_id: number;
  username: string;
  display_name: string;
  temp_password: string;
  expires_at: string | null;
}

/** PW-06：批量重置的两种模式——全员统一初始密码 / 逐生独立随机。 */
export type BatchResetMode = 'unified' | 'random';

export interface BatchResetResult {
  mode: BatchResetMode;
  count: number;
  credentials: TempCredential[];
}

/* ---------- 审计日志（AU-05 / AU-06） ---------- */

export interface AuditLogItem {
  id: number;
  actor_id: number | null;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: number | null;
  /** 后端存 JSON 文本，出接口时已解成对象；无明细为 null。 */
  detail: Record<string, unknown> | null;
  /** UTC 串。 */
  created_at: string;
}

export interface AuditLogPage {
  items: AuditLogItem[];
  total: number;
}

/* ---------- admin ---------- */

export interface TeacherItem {
  id: number;
  username: string;
  display_name: string;
  is_active: boolean;
  /** LI-02：未改密徽标（PW 方案同等适用于教师账号）。 */
  must_change_password: boolean;
  student_count: number;
}

export interface StudentItem {
  id: number;
  username: string;
  display_name: string;
  is_active: boolean;
  /** LI-02：未改密徽标。 */
  must_change_password: boolean;
  teachers: { id: number; display_name: string }[];
  groups: GroupRef[];
}

/** LI-01 / LI-02：学生列表的可选筛选参数，全部缺省时行为与旧接口一致。 */
export interface StudentListQuery {
  /** 学号 / 姓名模糊匹配。 */
  q?: string;
  /** 按组别（行政班）过滤。 */
  group_id?: number | null;
  /** true = 只看未改密，false = 只看已改密，undefined = 全部。 */
  must_change?: boolean | null;
}

/** BD-02：组-教师分配（可教组别），PUT 为全量替换。 */
export interface TeacherGroups {
  teacher_id: number;
  group_ids: number[];
}

/** PW-01：`AccountCreate` 已去掉 password —— 初始密码由后端统一发放，无需前端填写。 */
export interface CreateTeacherBody {
  username: string;
  display_name: string;
}

export interface CreateStudentBody {
  username: string;
  display_name: string;
}

/**
 * 导入失败行明细。
 * 后端历史上只回 `content`（整行原文），M5 起补 `username`（学号）；
 * 两个字段都按可选处理，渲染时用 `username ?? content` 兜底。
 */
export interface ImportFailure {
  line: number;
  content?: string;
  username?: string;
  reason: string;
}

export interface ImportResult {
  success_count: number;
  failures: ImportFailure[];
}

/* ---------- teacher: problems ---------- */

export type CompareMode = 'exact' | 'trim' | 'float';

export interface TestCase {
  id: number;
  seq: number;
  input: string;
  expected: string;
  is_sample: boolean;
  weight: number;
}

export interface ProblemSummary {
  id: number;
  title: string;
  time_limit_ms: number;
  memory_limit_mb: number;
  compare_mode: CompareMode;
  created_at: string;
  /** 题库分组（自由文本，可空）。 */
  group_name?: string | null;
}

export interface ProblemDetail {
  id: number;
  title: string;
  description: string;
  input_format: string;
  output_format: string;
  time_limit_ms: number;
  memory_limit_mb: number;
  compare_mode: CompareMode;
  float_eps: number | null;
  created_at: string;
  cases: TestCase[];
  group_name?: string | null;
  /** 未保存的草稿（与正式字段同构）；服务端保存题目后清空。 */
  draft?: ProblemDraft | null;
  /** 草稿保存时间，UTC ISO 字符串。 */
  draft_saved_at?: string | null;
}

export interface ProblemBody {
  title: string;
  description: string;
  input_format: string;
  output_format: string;
  time_limit_ms: number;
  memory_limit_mb: number;
  compare_mode: CompareMode;
  float_eps: number | null;
  group_name?: string | null;
}

/** 题目草稿：与 ProblemBody 同构，后端以 JSON 存于 problems.draft。 */
export interface ProblemDraft {
  title: string;
  description: string;
  input_format: string;
  output_format: string;
  time_limit_ms: number;
  memory_limit_mb: number;
  compare_mode: CompareMode;
  float_eps: number | null;
  group_name?: string | null;
}

export interface CaseBody {
  seq: number;
  input: string;
  expected: string;
  is_sample: boolean;
  weight: number;
}

/* ---------- assignments ---------- */

export type AssignmentMode = 'homework' | 'test';
export type ScorePolicy = 'best' | 'last';
export type SubmissionStatus = 'pending' | 'judging' | 'done' | 'failed';
export type Verdict = 'AC' | 'WA' | 'TLE' | 'MLE' | 'RE' | 'CE';

export interface AssignmentProblemRef {
  problem_id: number;
  seq: number;
  full_score: number;
}

export interface AssignmentSummary {
  id: number;
  title: string;
  mode: AssignmentMode;
  start_time: string;
  end_time: string;
  max_submissions: number | null;
  score_policy: ScorePolicy;
  released: boolean;
  released_at: string | null;
  created_at: string;
}

export interface AssignmentDetail extends AssignmentSummary {
  problems: (AssignmentProblemRef & { title: string })[];
}

export interface AssignmentBody {
  title: string;
  mode: AssignmentMode;
  start_time: string;
  end_time: string;
  max_submissions: number | null;
  score_policy: ScorePolicy;
  problems: AssignmentProblemRef[];
}

export interface OverviewPerProblem {
  problem_id: number;
  title: string;
  submit_count: number;
  pass_rate: number;
  avg_effective_score: number | null;
}

export interface HistogramBucket {
  range: string;
  count: number;
}

export interface AssignmentOverview {
  total_students: number;
  submitted_students: number;
  per_problem: OverviewPerProblem[];
  histogram: HistogramBucket[];
}

/** SC-01：场次成绩行里「每题的有效分」（未提交为 null）。 */
export interface AssignmentProblemScore {
  problem_id: number;
  seq: number;
  title: string;
  full_score: number;
  effective_score: number | null;
}

export interface AssignmentStudentRow {
  student_id: number;
  /** 学号（后端 M5 起补充，旧数据可能为空）。 */
  username?: string;
  name: string;
  submitted_count: number;
  /**
   * 注意语义是「最高单题分」而非总分（SC-01：后端 stats.py 一直如此）。
   * 多题场次的总分看 `total_score`，列标题文案统一叫「最高单题分」。
   */
  best_effective_score: number | null;
  /** SC-01：Σ 每题有效分。 */
  total_score: number;
  /** SC-01：逐题有效分，顺序即题单 seq。 */
  problem_scores: AssignmentProblemScore[];
  last_submitted_at: string | null;
  last_submission_id?: number | null;
}

/* ---------- submissions ---------- */

export interface SubmissionResultRow {
  seq: number;
  is_sample: boolean;
  verdict: Verdict;
  time_ms: number;
  memory_kb: number;
  score: number;
}

export interface TeacherSubmissionDetail {
  id: number;
  assignment_id: number;
  problem_id: number;
  problem_title?: string;
  user_id: number;
  student_name?: string;
  code_text: string;
  status: SubmissionStatus;
  verdict: Verdict | null;
  score: number | null;
  manual_score: number | null;
  judge_log: string | null;
  submitted_at: string;
  judged_at: string | null;
  results: SubmissionResultRow[];
}

/* ---------- student ---------- */

export type AssignmentState = 'ongoing' | 'ended';

export interface StudentAssignmentItem {
  id: number;
  title: string;
  mode: AssignmentMode;
  start_time: string;
  end_time: string;
  max_submissions: number | null;
  score_policy: ScorePolicy;
  released: boolean;
  state: AssignmentState;
  my_scores: StudentScoreRow[];
}

export interface StudentScoreRow {
  problem_id: number;
  seq: number;
  title: string;
  full_score: number;
  effective_score: number | null;
}

/** @deprecated kept as an alias for the per-problem score row used in the detail table. */
export type StudentAssignmentProblem = StudentScoreRow;

export interface StudentAssignmentDetail {
  id: number;
  title: string;
  mode: AssignmentMode;
  start_time: string;
  end_time: string;
  max_submissions: number | null;
  score_policy: ScorePolicy;
  released: boolean;
  state: AssignmentState;
  my_scores: StudentScoreRow[];
}

export interface SampleCase {
  seq: number;
  input: string;
  expected: string;
}

export interface StudentSubmissionSummary {
  id: number;
  submitted_at: string;
  status: SubmissionStatus;
  status_text?: string;
  verdict?: Verdict | null;
  score?: number | null;
  manual_score?: number | null;
}

export interface StudentProblemDetail {
  id: number;
  title: string;
  description: string;
  input_format: string;
  output_format: string;
  time_limit_ms: number;
  memory_limit_mb: number;
  compare_mode: CompareMode;
  full_score: number;
  samples: SampleCase[];
  my_submissions: StudentSubmissionSummary[];
}

export interface StudentSubmissionResultRow {
  seq: number;
  is_sample: boolean;
  verdict: Verdict;
  time_ms: number;
  score: number;
}

export interface StudentSubmissionDetail {
  id: number;
  assignment_id?: number;
  problem_id?: number;
  submitted_at: string;
  status?: SubmissionStatus;
  status_text?: string;
  code_text?: string;
  verdict?: Verdict | null;
  score?: number | null;
  manual_score?: number | null;
  judged_at?: string | null;
  judge_log?: string | null;
  results?: StudentSubmissionResultRow[];
}

export interface CreateSubmissionResponse {
  id: number;
}
