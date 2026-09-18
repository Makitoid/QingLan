import { useTheme } from '../../appTheme';
import { useEffect, useState } from 'react';
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
  deleteTeacherProblem,
  getTeacherProblem,
  updateCase,
  updateTeacherProblem,
} from '../../api';
import type { CaseBody, CompareMode, ProblemDetail, TestCase } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, errMessage } from '../../components/StateViews';
import { NumberInput } from '../../components/NumberInput';

const COMPARE_OPTIONS: { value: CompareMode; label: string }[] = [
  { value: 'trim', label: 'trim · 忽略行尾空白与末尾空行（默认）' },
  { value: 'exact', label: 'exact · 字节级精确比对' },
  { value: 'float', label: 'float · 浮点容差比对' },
];

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

export function TeacherProblemEdit() {
  const { id } = useParams();
  const problemId = Number(id);
  const t = useTheme();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync<ProblemDetail>(() => getTeacherProblem(problemId), [problemId]);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [inputFormat, setInputFormat] = useState('');
  const [outputFormat, setOutputFormat] = useState('');
  const [timeLimit, setTimeLimit] = useState(1000);
  const [memoryLimit, setMemoryLimit] = useState(256);
  const [compareMode, setCompareMode] = useState<CompareMode>('trim');
  const [floatEps, setFloatEps] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  const [caseForm, setCaseForm] = useState<CaseFormState | null>(null);
  const [caseBusy, setCaseBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (data) {
      setTitle(data.title);
      setDescription(data.description);
      setInputFormat(data.input_format);
      setOutputFormat(data.output_format);
      setTimeLimit(data.time_limit_ms);
      setMemoryLimit(data.memory_limit_mb);
      setCompareMode(data.compare_mode);
      setFloatEps(data.float_eps);
    }
  }, [data]);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await updateTeacherProblem(problemId, {
        title,
        description,
        input_format: inputFormat,
        output_format: outputFormat,
        time_limit_ms: timeLimit,
        memory_limit_mb: memoryLimit,
        compare_mode: compareMode,
        float_eps: compareMode === 'float' ? floatEps : null,
      });
      setMessage({ intent: 'success', text: '已保存' });
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteProblem = async () => {
    if (!window.confirm('确定删除该题目？已被场次引用的题目无法删除。')) return;
    setDeleting(true);
    setMessage(null);
    try {
      await deleteTeacherProblem(problemId);
      navigate('/teacher/problems', { replace: true });
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <Caption1>
            <Button appearance="subtle" size="small" onClick={() => navigate('/teacher/problems')}>← 返回题库</Button>
          </Caption1>
          <Text as="h2" size={600} weight="semibold">编辑题目 #{data.id}</Text>
        </div>
        <div style={{ display: 'flex', gap: tokens.spacingHorizontalS }}>
          <Button appearance="secondary" icon={<Delete24Regular />} onClick={handleDeleteProblem} disabled={deleting}>删除题目</Button>
          <Button appearance="primary" icon={<Save24Regular />} onClick={handleSave} disabled={saving}>
            {saving ? '保存中…' : '保存'}
          </Button>
        </div>
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
            <Input value={title} onChange={(_, d) => setTitle(d.value)} />
          </Field>
          <Field label="题目描述（Markdown）">
            <Textarea value={description} onChange={(_, d) => setDescription(d.value)} rows={8} resize="vertical" />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: tokens.spacingHorizontalM }}>
            <Field label="输入格式">
              <Textarea value={inputFormat} onChange={(_, d) => setInputFormat(d.value)} rows={3} resize="vertical" />
            </Field>
            <Field label="输出格式">
              <Textarea value={outputFormat} onChange={(_, d) => setOutputFormat(d.value)} rows={3} resize="vertical" />
            </Field>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: tokens.spacingHorizontalM }}>
            <Field label="时间限制（ms）">
              <NumberInput value={timeLimit} min={1} onValue={setTimeLimit} />
            </Field>
            <Field label="内存限制（MB）">
              <NumberInput value={memoryLimit} min={1} onValue={setMemoryLimit} />
            </Field>
            <Field label="比对模式">
              <Dropdown
                value={COMPARE_OPTIONS.find((o) => o.value === compareMode)?.label}
                selectedOptions={[compareMode]}
                onOptionSelect={(_, d) => setCompareMode(d.optionValue as CompareMode)}
              >
                {COMPARE_OPTIONS.map((o) => (
                  <Option key={o.value} value={o.value}>{o.label}</Option>
                ))}
              </Dropdown>
            </Field>
          </div>
          {compareMode === 'float' && (
            <Field label="浮点容差 float_eps" hint="两个数值之差的绝对值不超过该容差即视为相等，常用 1e-6。">
              <NumberInput
                value={floatEps}
                step={0.000001}
                min={0}
                onValue={(v) => setFloatEps(v)}
                width="240px"
              />
            </Field>
          )}
          {compareMode !== 'float' && (
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
          标记为「样例」的用例学生可见；未标记的仅用于判分。用例得分 = 本题满分 × 该用例权重 ÷ 总权重（仅 AC 计分）。
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
                        ? <Badge size="small" style={{ color: t.colorBrandForeground1, backgroundColor: t.colorBrandBackground2 }}>样例</Badge>
                        : <Badge size="small" appearance="outline">隐藏</Badge>
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
