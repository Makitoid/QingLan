export type Role = 'admin' | 'teacher' | 'student';

export interface User {
  id: number;
  username: string;
  role: Role;
  display_name: string;
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
  groups: GroupRef[];
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

/* ---------- admin ---------- */

export interface TeacherItem {
  id: number;
  username: string;
  display_name: string;
  is_active: boolean;
  student_count: number;
}

export interface StudentItem {
  id: number;
  username: string;
  display_name: string;
  is_active: boolean;
  teachers: { id: number; display_name: string }[];
  groups: GroupRef[];
}

export interface CreateTeacherBody {
  username: string;
  password: string;
  display_name: string;
}

export interface CreateStudentBody {
  username: string;
  password: string;
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

export interface AssignmentStudentRow {
  student_id: number;
  /** 学号（后端 M5 起补充，旧数据可能为空）。 */
  username?: string;
  name: string;
  submitted_count: number;
  best_effective_score: number | null;
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
