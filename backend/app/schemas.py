from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(ORMModel):
    id: int
    username: str
    role: str
    display_name: str
    # PW-02：前端刷新页面后据此恢复强制改密拦截态
    must_change_password: bool = False


class TokenResponse(BaseModel):
    token: str
    user: UserOut


class AccountCreate(BaseModel):
    """PW-01：admin 不再手填初始密码 —— 统一 `12345678` + 首登强制改密。"""

    username: str
    display_name: str


class IsActivePatch(BaseModel):
    is_active: bool


class TempCredentialOut(BaseModel):
    """PW-09 凭证明细的一行；单个重置（学生/教师）即直接返回本对象。"""

    student_id: int
    username: str
    display_name: str
    temp_password: str
    # None = 不过期（统一/初始密码）；随机密码为 UTC 串
    expires_at: str | None = None


class BatchResetResultOut(BaseModel):
    mode: str
    count: int
    credentials: list[TempCredentialOut]


class TeacherOut(ORMModel):
    id: int
    username: str
    display_name: str
    is_active: int
    must_change_password: bool = False
    created_at: str
    student_count: int = 0


class GroupRef(BaseModel):
    id: int
    name: str


class StudentOut(ORMModel):
    id: int
    username: str
    display_name: str
    is_active: int
    # LI-02：未改密徽标
    must_change_password: bool = False
    created_at: str
    teachers: list[UserOut] = []
    groups: list[GroupRef] = []


# B1（0.3.2 F1）：admin 教师详情名单的一名学生。
# source：'manual' = 教师按学号手动添加（层 3 有行）；'group' = 仅由可教组别派生。
# group_names：含该生的可教组别名（手动添加且不在任何组里时为空数组）。
class RosterEntryOut(BaseModel):
    id: int
    username: str
    display_name: str
    source: Literal["manual", "group"]
    group_names: list[str] = []


class TeacherRosterOut(BaseModel):
    students: list[RosterEntryOut] = []


class SubgroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class SubgroupUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class SubgroupStudentsRequest(BaseModel):
    """PUT /teacher/subgroups/{id}/students：全量替换（空列表 = 清空成员）。"""

    student_ids: list[int]


class SubgroupOut(BaseModel):
    id: int
    name: str
    created_at: str
    # 成员数与学生 ID 都按「当前名单口径」给出（已撤销组别的学生不再计入）
    member_count: int = 0
    student_ids: list[int] = []


class TeacherNoticeOut(BaseModel):
    id: int
    kind: str | None = None
    payload: dict | None = None
    created_at: str


class GroupOut(ORMModel):
    id: int
    name: str
    created_at: str
    member_count: int = 0


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class GroupUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class GroupMembersRequest(BaseModel):
    student_ids: list[int]
    group_ids: list[int]
    action: Literal["add", "remove"]


class GroupMembershipOut(BaseModel):
    # 实际写入/删除的「学生×组」成员关系条数（幂等 add 重复提交时为 0）
    success_count: int


class BoundStudentOut(ORMModel):
    id: int
    username: str
    display_name: str
    is_active: int
    must_change_password: bool = False
    groups: list[GroupRef] = []


class BatchResetPasswordRequest(BaseModel):
    """PW-06：mode = unified（全员统一初始密码）| random（逐生独立随机密码）。"""

    student_ids: list[int]
    mode: Literal["unified", "random"] = "random"


class TeacherGroupsRequest(BaseModel):
    """BD-02：全量替换某教师可教的组。"""

    group_ids: list[int]


class TeacherGroupsOut(BaseModel):
    teacher_id: int
    group_ids: list[int]


class ClassStudentOut(BaseModel):
    """BD-03：可教组内的成员；停用学生照常返回并由 is_active 标注。"""

    id: int
    username: str
    display_name: str
    is_active: int
    # 是否已在自己的名单里，前端据此把「拉入」按钮置灰
    bound: bool = False


class ClassOut(BaseModel):
    id: int
    name: str
    member_count: int
    students: list[ClassStudentOut] = []


class AuditLogOut(BaseModel):
    id: int
    actor_id: int | None
    actor_name: str = ""
    action: str
    action_label: str
    target_type: str
    target_label: str
    target_id: int | None
    detail: dict | None = None
    created_at: str


class AuditLogPageOut(BaseModel):
    items: list[AuditLogOut]
    total: int


class BatchActiveRequest(BaseModel):
    student_ids: list[int]
    is_active: bool


class BindStudentsRequest(BaseModel):
    student_ids: list[int]


class ImportFailure(BaseModel):
    line: int
    content: str = ""
    # 前端 types.ts 已有该字段；无法解析学号时为 None
    username: str | None = None
    reason: str


class ImportResult(BaseModel):
    success_count: int
    failures: list[ImportFailure]


class SettingsOut(BaseModel):
    brand_color: str
    brand_color_dark: str | None
    brand_color_source: str
    bg_image_url: str | None
    bg_image_url_dark: str | None
    bg_dual: bool
    bg_opacity: float
    audit_enabled: bool = True


class AdminSettingsOut(SettingsOut):
    audit_retention_days: int | None = None


class SettingsUpdate(BaseModel):
    brand_color: str | None = None
    brand_color_dark: str | None = None
    brand_color_source: Literal["manual", "image"] | None = None
    bg_dual: bool | None = None
    bg_opacity: float | None = Field(default=None, ge=0, le=1)
    audit_enabled: bool | None = None
    audit_retention_days: int | None = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class ProblemCreate(BaseModel):
    title: str
    description: str
    input_format: str
    output_format: str
    time_limit_ms: int = Field(default=1000, ge=50, le=30000)
    memory_limit_mb: int = Field(default=256, ge=16, le=2048)
    compare_mode: str = "trim"
    float_eps: float | None = None
    group_name: str | None = Field(default=None, max_length=50)


class ProblemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    input_format: str | None = None
    output_format: str | None = None
    time_limit_ms: int | None = None
    memory_limit_mb: int | None = None
    compare_mode: str | None = None
    float_eps: float | None = None
    group_name: str | None = None


class ProblemDraft(BaseModel):
    """未保存的编辑内容快照；服务端原样存 JSON，保存题目时清空。"""

    title: str = ""
    description: str = ""
    input_format: str = ""
    output_format: str = ""
    time_limit_ms: int = 1000
    memory_limit_mb: int = 256
    compare_mode: str = "trim"
    float_eps: float | None = None
    group_name: str | None = None


class ProblemDraftSavedOut(BaseModel):
    ok: bool = True
    draft_saved_at: str


class ProblemOut(ORMModel):
    id: int
    title: str
    description: str
    input_format: str
    output_format: str
    time_limit_ms: int
    memory_limit_mb: int
    compare_mode: str
    float_eps: float | None
    group_name: str | None = None
    created_by: int
    created_at: str


class TestCaseCreate(BaseModel):
    seq: int
    input: str
    expected: str
    is_sample: bool = False
    weight: int = Field(default=1, ge=1)


class TestCaseUpdate(BaseModel):
    seq: int | None = None
    input: str | None = None
    expected: str | None = None
    is_sample: bool | None = None
    weight: int | None = None


class TestCaseOut(ORMModel):
    id: int
    problem_id: int
    seq: int
    input: str
    expected: str
    is_sample: int
    weight: int


class ProblemDetailOut(ProblemOut):
    cases: list[TestCaseOut] = []
    draft: ProblemDraft | None = None
    draft_saved_at: str | None = None


class AssignmentProblemIn(BaseModel):
    problem_id: int
    seq: int
    full_score: float = 100


class AssignmentCreate(BaseModel):
    title: str
    mode: str = Field(pattern="^(homework|test)$")
    start_time: str
    end_time: str
    max_submissions: int | None = Field(default=None, ge=1)
    score_policy: str = Field(default="best", pattern="^(best|last)$")
    # 0.3.2 F1 发布受众：'all' = 全部名单（缺省，与老行为一致）；'subgroup' 须给出 subgroup_ids
    audience_mode: Literal["all", "subgroup"] = "all"
    subgroup_ids: list[int] = []
    problems: list[AssignmentProblemIn] = Field(min_length=1)


class AssignmentUpdate(BaseModel):
    title: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    max_submissions: int | None = None
    score_policy: str | None = None
    audience_mode: Literal["all", "subgroup"] | None = None
    subgroup_ids: list[int] | None = None
    problems: list[AssignmentProblemIn] | None = None


class AssignmentProblemOut(ORMModel):
    problem_id: int
    seq: int
    full_score: float
    title: str | None = None


class AssignmentOut(ORMModel):
    id: int
    title: str
    mode: str
    start_time: str
    end_time: str
    max_submissions: int | None
    score_policy: str
    released: int
    released_at: str | None
    # 0.3.2 F1：受众模式与子分组白名单（'all' 时恒为空数组，老数据行为不变）
    audience_mode: str = "all"
    subgroup_ids: list[int] = []
    created_by: int
    created_at: str
    problems: list[AssignmentProblemOut] = []


class SubmissionCreate(BaseModel):
    code_text: str


class ResultOut(ORMModel):
    seq: int
    is_sample: int
    verdict: str
    time_ms: int
    memory_kb: int
    score: float


class SubmissionDetailOut(ORMModel):
    id: int
    assignment_id: int
    problem_id: int
    user_id: int
    code_text: str
    status: str
    verdict: str | None
    score: float | None
    manual_score: float | None
    judge_log: str | None
    submitted_at: str
    judged_at: str | None
    results: list[ResultOut] = []


class SubmissionSummaryOut(ORMModel):
    id: int
    submitted_at: str
    status: str
    verdict: str | None = None
    score: float | None = None
    manual_score: float | None = None


class ManualScorePatch(BaseModel):
    manual_score: float | None = None


class PerProblemStat(BaseModel):
    problem_id: int
    title: str
    submit_count: int
    pass_rate: float
    avg_effective_score: float


class HistogramBin(BaseModel):
    range: str
    count: int


class OverviewOut(BaseModel):
    total_students: int
    submitted_students: int
    per_problem: list[PerProblemStat]
    histogram: list[HistogramBin]


class StudentProblemScoreOut(BaseModel):
    """SC-01：某生在某题上的有效分（未提交为 None）。

    F6 起 `StudentRowOut.problem_scores` 仍只填前 5 个字段（默认值兜底），
    逐学生按题调分端点则额外填 submission_count / latest_submission_id /
    score / manual_score —— 三者取自该题**最新一条**提交，effective_score 取自
    aggregate_scores 全量口径，两者口径不同故并列输出。
    """

    problem_id: int
    seq: int
    title: str
    full_score: float
    effective_score: float | None = None
    submission_count: int = 0
    latest_submission_id: int | None = None
    score: float | None = None
    manual_score: float | None = None


class StudentRowOut(BaseModel):
    student_id: int
    username: str = ""
    name: str
    submitted_count: int
    # 语义即「最高单题分」（SC-01/02 更名），新增 total_score 才是本场总分
    best_effective_score: float
    total_score: float = 0.0
    problem_scores: list[StudentProblemScoreOut] = []
    last_submitted_at: str | None = None
    last_submission_id: int | None = None


class MyProblemScore(BaseModel):
    problem_id: int
    seq: int
    title: str
    full_score: float
    effective_score: float | None = None


class StudentAssignmentOut(BaseModel):
    id: int
    title: str
    mode: str
    start_time: str
    end_time: str
    max_submissions: int | None
    score_policy: str
    released: int
    state: Literal["ongoing", "ending", "ended"]
    my_scores: list[MyProblemScore] = []


class SampleCaseOut(BaseModel):
    seq: int
    input: str
    expected: str


class StudentSubmissionOut(BaseModel):
    id: int
    submitted_at: str
    status: str
    status_text: str | None = None
    verdict: str | None = None
    score: float | None = None
    manual_score: float | None = None


class StudentProblemOut(BaseModel):
    id: int
    title: str
    description: str
    input_format: str
    output_format: str
    time_limit_ms: int
    memory_limit_mb: int
    compare_mode: str
    full_score: float
    samples: list[SampleCaseOut] = []
    my_submissions: list[StudentSubmissionOut] = []
