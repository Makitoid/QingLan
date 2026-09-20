import { useTheme } from '../../appTheme';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  Card,
  CardHeader,
  createTableColumn, DataGrid,
  DataGridBody,
  DataGridCell,
  DataGridHeader,
  DataGridHeaderCell,
  DataGridRow,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Option,
  Switch,
  Text,
  Textarea,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Add24Regular, Delete24Regular, Edit24Regular, Save24Regular } from '@fluentui/react-icons';
import {
  createCase,
  deleteCase,
  deleteProblemDraft,
  deleteTeacherProblem,
  getTeacherProblem,
  saveProblemDraft,
  updateCase,
  updateTeacherProblem,
} from '../../api';
import type { CaseBody, CompareMode, ProblemDetail, ProblemDraft, TestCase } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, errCode, errMessage } from '../../components/StateViews';
import { NumberInput } from '../../components/NumberInput';
import { PageHeader } from '../../components/PageHeader';
import { useDangerStyles } from '../../components/dangerStyles';
import { fmtTimeWithSeconds } from '../../components/time';

const COMPARE_OPTIONS: { value: CompareMode; label: string }[] = [
  { value: 'trim', label: 'trim · 忽略行尾空白与末尾空行（默认）' },
  { value: 'exact', label: 'exact · 字节级精确比对' },
  { value: 'float', label: 'float · 浮点容差比对' },
];

/** 后端 ProblemCreate.group_name 的上限（坑：字段名用 group_name，group 是 SQL 保留字）。 */
const MAX_GROUP_LENGTH = 50;

const columns: TableColumnDefinition<TestCase>[] = [
  createTableColumn({ columnId: 'seq', renderHeaderCell: () => '#' }),
  createTableColumn({ columnId: 'kind', renderHeaderCell: () => '类型' }),
  createTableColumn({ columnId: 'weight', renderHeaderCell: () => '权重' }),
  createTableColumn({ columnId: 'input', renderHeaderCell: () => '输入' }),
  createTableColumn({ columnId: 'expected', renderHeaderCell: () => '输出' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '操作' }),
];

interface CaseFormState {
  editing: TestCase | null;
  seq: number;
  input: string;
  expected: string;
  is_sample: boolean;
  weight: number;
}

/** 题面表单（草稿只覆盖这些字段，测试用例是即时保存的，不参与脏检测）。 */
interface FormState {
  title: string;
  description: string;
  inputFormat: string;
  outputFormat: string;
  timeLimit: number;
  memoryLimit: number;
  compareMode: CompareMode;
  floatEps: number | null;
  groupName: string;
}

/** 脏检测用的规范化快照：全部是标量，逐字段 === 即等价于深比较。 */
type FormSnapshot = Record<keyof FormState, string | number | null>;

const EMPTY_FORM: FormState = {
  title: '',
  description: '',
  inputFormat: '',
  outputFormat: '',
  timeLimit: 1000,
  memoryLimit: 256,
  compareMode: 'trim',
  floatEps: null,
  groupName: '',
};

/** 数字字段可能是 null / 空串 / 数字，统一成 number | null 后再比较，避免刚进页面就误报脏。 */
function toNum(value: number | string | null | undefined, fallback: number | null = null): number | null {
  if (value === null || value === undefined || value === '') return fallback;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function snapshotOf(form: FormState): FormSnapshot {
  return {
    title: form.title,
    description: form.description,
    inputFormat: form.inputFormat,
    outputFormat: form.outputFormat,
    timeLimit: toNum(form.timeLimit),
    memoryLimit: toNum(form.memoryLimit),
    compareMode: form.compareMode,
    // 非 float 模式下 float_eps 不会落库（保存时固定发 null），比较时同样忽略
    floatEps: form.compareMode === 'float' ? toNum(form.floatEps) : null,
    groupName: form.groupName.trim(),
  };
}

function sameSnapshot(a: FormSnapshot, b: FormSnapshot): boolean {
  return (Object.keys(a) as (keyof FormState)[]).every((key) => a[key] === b[key]);
}

function formFromProblem(problem: ProblemDetail): FormState {
  return {
    title: problem.title ?? '',
    description: problem.description ?? '',
    inputFormat: problem.input_format ?? '',
    outputFormat: problem.output_format ?? '',
    timeLimit: toNum(problem.time_limit_ms, 1000) ?? 1000,
    memoryLimit: toNum(problem.memory_limit_mb, 256) ?? 256,
    compareMode: problem.compare_mode ?? 'trim',
    floatEps: toNum(problem.float_eps),
    groupName: problem.group_name ?? '',
  };
}

/** 草稿字段覆盖到表单上（草稿不含测试用例）。 */
function formFromDraft(draft: ProblemDraft): FormState {
  return {
    title: draft.title ?? '',
    description: draft.description ?? '',
    inputFormat: draft.input_format ?? '',
    outputFormat: draft.output_format ?? '',
    timeLimit: toNum(draft.time_limit_ms, 1000) ?? 1000,
    memoryLimit: toNum(draft.memory_limit_mb, 256) ?? 256,
    compareMode: draft.compare_mode ?? 'trim',
    floatEps: toNum(draft.float_eps),
    groupName: draft.group_name ?? '',
  };
}

/** 题面 → 请求体；ProblemDraft 与 ProblemBody 同构，两者共用（草稿接口忽略用例）。 */
function payloadOf(form: FormState): ProblemDraft {
  return {
    title: form.title,
    description: form.description,
    input_format: form.inputFormat,
    output_format: form.outputFormat,
    time_limit_ms: toNum(form.timeLimit, 1000) ?? 1000,
    memory_limit_mb: toNum(form.memoryLimit, 256) ?? 256,
    compare_mode: form.compareMode,
    float_eps: form.compareMode === 'float' ? toNum(form.floatEps) : null,
    group_name: form.groupName.trim() || null,
  };
}

/** 后端 409 PROBLEM_IN_USE 的可操作文案（错误码见 backend/app/api/teacher.py::delete_problem）。 */
function deleteErrorMessage(err: unknown): string {
  return errCode(err) === 'PROBLEM_IN_USE'
    ? '该题目已被场次引用，无法删除。请先在相关场次中移除这道题目。'
    : errMessage(err);
}

export function TeacherProblemEdit() {
  const { id } = useParams();
  const problemId = Number(id);
  const t = useTheme();
  const danger = useDangerStyles();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync<ProblemDetail>(() => getTeacherProblem(problemId), [problemId]);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  /** 上次「加载成功 / 保存成功」时的表单快照，脏检测与它深比较。 */
  const [snapshot, setSnapshot] = useState<FormSnapshot>(() => snapshotOf(EMPTY_FORM));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'error' | 'info'; text: string } | null>(null);

  const [caseForm, setCaseForm] = useState<CaseFormState | null>(null);
  const [caseBusy, setCaseBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  /** 服务端返回的待处理草稿：进入页面时只提示一次。 */
  const [pendingDraft, setPendingDraft] = useState<{ draft: ProblemDraft; savedAt: string | null } | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  /** 「返回题库」时若有未保存修改弹出的询问框。 */
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [leaveBusy, setLeaveBusy] = useState(false);
  const [leaveError, setLeaveError] = useState<string | null>(null);

  // 只用服务端数据灌一次表单：之后用例增删触发的 reload 不能覆盖用户正在编辑的内容
  const hydratedId = useRef<number | null>(null);

  useEffect(() => {
    if (!data || hydratedId.current === data.id) return;
    hydratedId.current = data.id;
    const loaded = formFromProblem(data);
    setForm(loaded);
    setSnapshot(snapshotOf(loaded));
    setMessage(null);
    if (data.draft) setPendingDraft({ draft: data.draft, savedAt: data.draft_saved_at ?? null });
  }, [data]);

  const dirty = useMemo(() => !sameSnapshot(snapshotOf(form), snapshot), [form, snapshot]);

  const patch = (changes: Partial<FormState>) => setForm((prev) => ({ ...prev, ...changes }));

  const handleSave = async () => {
    if (!form.title.trim()) {
      setMessage({ intent: 'error', text: '题目标题不能为空。' });
      return;
    }
    if (form.compareMode === 'float' && toNum(form.floatEps) === null) {
      setMessage({ intent: 'error', text: 'float 比对模式必须填写浮点容差 float_eps。' });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await updateTeacherProblem(problemId, payloadOf(form));
      // 服务端保存成功即清空草稿：本地把快照推进到当前值（dirty 归零），并丢掉待处理草稿，避免再弹恢复框
      setSnapshot(snapshotOf(form));
      setPendingDraft(null);
      setMessage({ intent: 'success', text: '已保存，草稿已清除。' });
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  /* ---------- 草稿：离开时询问 ---------- */

  const goBack = () => navigate('/teacher/problems');

  const handleBack = () => {
    if (!dirty) {
      goBack();
      return;
    }
    setLeaveError(null);
    setLeaveOpen(true);
  };

  const handleSaveDraftAndLeave = async () => {
    setLeaveBusy(true);
    setLeaveError(null);
    try {
      await saveProblemDraft(problemId, payloadOf(form));
      setLeaveOpen(false);
      goBack();
    } catch (err) {
      // 草稿没存上就不离开，用户仍可改选「直接退出」或「取消」
      setLeaveError(errMessage(err));
    } finally {
      setLeaveBusy(false);
    }
  };

  /* ---------- 草稿：进入时恢复 ---------- */

  const handleUseDraft = () => {
    if (!pendingDraft) return;
    setForm(formFromDraft(pendingDraft.draft));
    setPendingDraft(null);
    setDraftError(null);
    setMessage({ intent: 'info', text: '已载入草稿内容，仍未保存；确认无误后点「保存」写入正式题面。' });
  };

  const handleDiscardDraft = async () => {
    if (!pendingDraft) return;
    setDraftBusy(true);
    setDraftError(null);
    try {
      await deleteProblemDraft(problemId);
      setPendingDraft(null);
      setMessage({ intent: 'info', text: '已放弃草稿，当前显示上次保存的内容。' });
    } catch (err) {
      setDraftError(errMessage(err));
    } finally {
      setDraftBusy(false);
    }
  };

  const handleDeleteProblem = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteTeacherProblem(problemId);
      navigate('/teacher/problems', { replace: true });
    } catch (err) {
      setDeleteError(deleteErrorMessage(err));
      setDeleting(false);
    }
  };

  const openAddCase = () => {
    const nextSeq = data ? Math.max(0, ...data.cases.map((c) => c.seq)) + 1 : 1;
    setCaseForm({ editing: null, seq: nextSeq, input: '', expected: '', is_sample: false, weight: 1 });
  };

  const openEditCase = (c: TestCase) => {
    setCaseForm({ editing: c, seq: c.seq, input: c.input, expected: c.expected, is_sample: c.is_sample, weight: c.weight });
  };

  const handleSaveCase = async () => {
    if (!caseForm || !data) return;
    if (caseForm.seq <= 0) {
      setMessage({ intent: 'error', text: '序号必须为正整数' });
      return;
    }
    setCaseBusy(true);
    const body: CaseBody = {
      seq: caseForm.seq,
      input: caseForm.input,
      expected: caseForm.expected,
      is_sample: caseForm.is_sample,
      weight: caseForm.weight,
    };
    try {
      if (caseForm.editing) {
        await updateCase(caseForm.editing.id, body);
      } else {
        await createCase(problemId, body);
      }
      setCaseForm(null);
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setCaseBusy(false);
    }
  };

  const handleDeleteCase = async (c: TestCase) => {
    if (!window.confirm(`删除测试点 #${c.seq}？`)) return;
    try {
      await deleteCase(c.id);
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={handleBack}>← 返回题库</Button>
        </Caption1>
        <PageHeader
          title={
            <>
              编辑题目 #{data.id}
              {dirty && <Badge appearance="tint" size="large" style={{ marginLeft: tokens.spacingHorizontalS }}>未保存</Badge>}
            </>
          }
          actions={
            <>
              <Button appearance="secondary" icon={<Delete24Regular />} onClick={() => { setDeleteError(null); setDeleteOpen(true); }} disabled={deleting}>
                删除题目
              </Button>
              <Button appearance="primary" icon={<Save24Regular />} onClick={handleSave} disabled={saving}>
                {saving ? '保存中…' : '保存'}
              </Button>
            </>
          }
        />
      </div>

      {message && (
        <MessageBar intent={message.intent} style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{message.text}</MessageBarBody>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">基本信息</Text>} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Field label="标题" required>
            <Input value={form.title} onChange={(_, d) => patch({ title: d.value })} />
          </Field>
          <Field label="分组（自由文本，可空）" hint={`用于题库搜索与筛选，最长 ${MAX_GROUP_LENGTH} 字；留空即「未分组」。`}>
            <Input
              value={form.groupName}
              onChange={(_, d) => patch({ groupName: d.value })}
              maxLength={MAX_GROUP_LENGTH}
              placeholder="如：高一（1）班"
            />
          </Field>
          <Field label="题目描述（Markdown）">
            <Textarea value={form.description} onChange={(_, d) => patch({ description: d.value })} rows={8} resize="vertical" />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: tokens.spacingHorizontalM }}>
            <Field label="输入格式">
              <Textarea value={form.inputFormat} onChange={(_, d) => patch({ inputFormat: d.value })} rows={3} resize="vertical" />
            </Field>
            <Field label="输出格式">
              <Textarea value={form.outputFormat} onChange={(_, d) => patch({ outputFormat: d.value })} rows={3} resize="vertical" />
            </Field>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: tokens.spacingHorizontalM }}>
            <Field label="时间限制（ms）">
              <NumberInput value={form.timeLimit} min={1} onValue={(v) => patch({ timeLimit: v })} />
            </Field>
            <Field label="内存限制（MB）">
              <NumberInput value={form.memoryLimit} min={1} onValue={(v) => patch({ memoryLimit: v })} />
            </Field>
            <Field label="比对模式">
              <Dropdown
                value={COMPARE_OPTIONS.find((o) => o.value === form.compareMode)?.label}
                selectedOptions={[form.compareMode]}
                onOptionSelect={(_, d) => patch({ compareMode: d.optionValue as CompareMode })}
              >
                {COMPARE_OPTIONS.map((o) => (
                  <Option key={o.value} value={o.value}>{o.label}</Option>
                ))}
              </Dropdown>
            </Field>
          </div>
          {form.compareMode === 'float' && (
            <Field label="浮点容差 float_eps" hint="两个数值之差的绝对值不超过该容差即视为相等，常用 1e-6。">
              <NumberInput
                value={form.floatEps}
                step={0.000001}
                min={0}
                onValue={(v) => patch({ floatEps: v })}
                width="240px"
              />
            </Field>
          )}
          {form.compareMode !== 'float' && (
            <MessageBar intent="info" style={{ borderRadius: tokens.borderRadiusMedium }}>
              <MessageBarBody>
                提示：若本题输出包含浮点数，请注意 C 语言 <code>%f</code> 默认输出 6 位小数，学生输出与期望输出的小数位数、
                行尾空格等格式差异在 trim / exact 模式下都会判为 WA。此类题目建议改用 float 比对模式并设置容差。
              </MessageBarBody>
            </MessageBar>
          )}
        </div>
      </Card>

      <Card size="medium">
        <CardHeader
          header={<Text weight="semibold">测试用例（{data.cases.length}）</Text>}
          action={<Button appearance="primary" icon={<Add24Regular />} size="small" onClick={openAddCase}>新增用例</Button>}
        />
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          用例即时保存，不参与草稿；标记为「样例」的用例学生可见；未标记的仅用于判分。用例得分 = 本题满分 × 该用例权重 ÷ 总权重（仅 AC 计分）。
        </Caption1>
        <DataGrid items={data.cases} columns={columns} focusMode="cell" style={{ marginTop: tokens.spacingVerticalS }}>
          <DataGridHeader>
            <DataGridRow>
              {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
            </DataGridRow>
          </DataGridHeader>
          <DataGridBody<TestCase>>
            {({ item, rowId }) => (
              <DataGridRow<TestCase> key={rowId}>
                {({ columnId }) => (
                  <DataGridCell>
                    {columnId === 'seq' && item.seq}
                    {columnId === 'kind' && (
                      item.is_sample
                        ? <Badge size="large" style={{ color: t.colorBrandForeground1, backgroundColor: t.colorBrandBackground2 }}>样例</Badge>
                        : <Badge size="large" appearance="outline">隐藏</Badge>
                    )}
                    {columnId === 'weight' && item.weight}
                    {columnId === 'input' && (
                      <Caption1 style={{ color: t.colorNeutralForeground3, fontFamily: 'Consolas, monospace' }}>
                        {item.input.length > 40 ? `${item.input.slice(0, 40)}…` : item.input}
                      </Caption1>
                    )}
                    {columnId === 'expected' && (
                      <Caption1 style={{ color: t.colorNeutralForeground3, fontFamily: 'Consolas, monospace' }}>
                        {item.expected.length > 40 ? `${item.expected.slice(0, 40)}…` : item.expected}
                      </Caption1>
                    )}
                    {columnId === 'actions' && (
                      <div style={{ display: 'flex', gap: tokens.spacingHorizontalXS }}>
                        <Button appearance="subtle" size="small" icon={<Edit24Regular />} onClick={() => openEditCase(item)} title="编辑" />
                        <Button appearance="subtle" size="small" icon={<Delete24Regular />} onClick={() => void handleDeleteCase(item)} title="删除" />
                      </div>
                    )}
                  </DataGridCell>
                )}
              </DataGridRow>
            )}
          </DataGridBody>
        </DataGrid>
      </Card>

      {/* 需求⑧：进入页面时若服务器上有草稿，先问用户怎么用 */}
      <Dialog
        open={pendingDraft !== null}
        onOpenChange={(_, d) => {
          // 关闭视为「稍后处理」：保留服务器上的草稿，页面继续显示已保存内容
          if (!d.open && !draftBusy) {
            setPendingDraft(null);
            setDraftError(null);
          }
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitle>检测到未保存的草稿，是否使用草稿内容？</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>草稿保存于 {fmtTimeWithSeconds(pendingDraft?.savedAt)}（本地时区）。</Caption1>
                {draftError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{draftError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={handleDiscardDraft} disabled={draftBusy}>放弃</Button>
              <Button appearance="primary" onClick={handleUseDraft} disabled={draftBusy}>是</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* 需求⑧：返回题库时若表单脏了，问要不要留草稿 */}
      <Dialog open={leaveOpen} onOpenChange={(_, d) => { if (!d.open && !leaveBusy) setLeaveOpen(false); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>有未保存的修改</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>本题的修改还没有保存。可以先存为草稿再离开——下次进入本题编辑页会提示恢复草稿。</Caption1>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  直接退出只保留上次已保存的内容，已有草稿不受影响。
                </Caption1>
                {leaveError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>草稿保存失败：{leaveError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setLeaveOpen(false)} disabled={leaveBusy}>取消</Button>
              <Button
                appearance="secondary"
                className={danger.outline}
                onClick={() => {
                  setLeaveOpen(false);
                  goBack();
                }}
                disabled={leaveBusy}
              >
                直接退出
              </Button>
              <Button appearance="primary" onClick={handleSaveDraftAndLeave} disabled={leaveBusy}>
                {leaveBusy ? '保存中…' : '存为草稿'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={(_, d) => { if (!d.open && !deleting) setDeleteOpen(false); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>删除题目</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>
                  确定删除题目「{data.title}」（#{data.id}）？题面与全部测试用例一并删除，且不可恢复。
                </Caption1>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>已被场次引用的题目无法删除。</Caption1>
                {deleteError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{deleteError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setDeleteOpen(false)} disabled={deleting}>取消</Button>
              <Button appearance="primary" className={danger.solid} icon={<Delete24Regular />} onClick={handleDeleteProblem} disabled={deleting}>
                {deleting ? '删除中…' : '确认删除'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={caseForm !== null} onOpenChange={(_, d) => { if (!d.open) setCaseForm(null); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{caseForm?.editing ? `编辑用例 #${caseForm.editing.seq}` : '新增用例'}</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: tokens.spacingHorizontalM }}>
                  <Field label="序号 seq" required>
                    <NumberInput
                      value={caseForm?.seq}
                      min={1}
                      onValue={(v) => setCaseForm((f) => (f ? { ...f, seq: v } : f))}
                    />
                  </Field>
                  <Field label="分值权重 weight">
                    <NumberInput
                      value={caseForm?.weight}
                      min={1}
                      onValue={(v) => setCaseForm((f) => (f ? { ...f, weight: v } : f))}
                    />
                  </Field>
                </div>
                <Field label="输入 input" required>
                  <Textarea
                    value={caseForm?.input ?? ''}
                    onChange={(_, d) => setCaseForm((f) => (f ? { ...f, input: d.value } : f))}
                    rows={4}
                    resize="vertical"
                    style={{ fontFamily: 'Consolas, monospace' }}
                  />
                </Field>
                <Field label="期望输出 expected" required>
                  <Textarea
                    value={caseForm?.expected ?? ''}
                    onChange={(_, d) => setCaseForm((f) => (f ? { ...f, expected: d.value } : f))}
                    rows={4}
                    resize="vertical"
                    style={{ fontFamily: 'Consolas, monospace' }}
                  />
                </Field>
                <Switch
                  checked={caseForm?.is_sample ?? false}
                  onChange={(_, d) => setCaseForm((f) => (f ? { ...f, is_sample: Boolean(d.checked) } : f))}
                  label="作为样例展示给学生"
                />
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setCaseForm(null)} disabled={caseBusy}>取消</Button>
              <Button appearance="primary" onClick={handleSaveCase} disabled={caseBusy}>
                {caseBusy ? '保存中…' : '保存用例'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
