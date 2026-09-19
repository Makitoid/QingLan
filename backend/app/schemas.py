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


class TokenResponse(BaseModel):
    token: str
    user: UserOut


class AccountCreate(BaseModel):
    username: str
    password: str = Field(min_length=6)
    display_name: str


class IsActivePatch(BaseModel):
    is_active: bool


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=6)


class TeacherOut(ORMModel):
    id: int
    username: str
    display_name: str
    is_active: int
    created_at: str
    student_count: int = 0


class StudentOut(ORMModel):
    id: int
    username: str
    display_name: str
    is_active: int
    created_at: str
    teachers: list[UserOut] = []


class BindStudentsRequest(BaseModel):
    student_ids: list[int]


class ImportFailure(BaseModel):
    line: int
    content: str
    reason: str


class ImportResult(BaseModel):
    success_count: int
    failures: list[ImportFailure]


class SettingsOut(BaseModel):
    brand_color: str
    brand_color_source: str
    bg_image_url: str | None
    bg_image_url_dark: str | None
    bg_dual: bool
    bg_opacity: float


class SettingsUpdate(BaseModel):
    brand_color: str | None = None
    brand_color_source: Literal["manual", "image"] | None = None
    bg_dual: bool | None = None
    bg_opacity: float | None = Field(default=None, ge=0, le=1)


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class ProblemCreate(BaseModel):
    title: str
    description: str
    input_format: str
    output_format: str
    time_limit_ms: int = Field(default=1000, ge=50, le=30000)
    memory_limit_mb: int = Field(default=256, ge=16, le=2048)
    compare_mode: str = "trim"
    float_eps: float | None = None


class ProblemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    input_format: str | None = None
    output_format: str | None = None
    time_limit_ms: int | None = None
    memory_limit_mb: int | None = None
    compare_mode: str | None = None
    float_eps: float | None = None


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
    problems: list[AssignmentProblemIn] = Field(min_length=1)


class AssignmentUpdate(BaseModel):
    title: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    max_submissions: int | None = None
    score_policy: str | None = None
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


class StudentRowOut(BaseModel):
    student_id: int
    name: str
    submitted_count: int
    best_effective_score: float
    last_submitted_at: str | None = None


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
    state: str
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
