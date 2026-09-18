import { useTheme } from '../../appTheme';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Caption1,
  Card,
  CardHeader,
  Checkbox,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Option,
  Text,
  tokens,

} from '@fluentui/react-components';
import { Send24Regular } from '@fluentui/react-icons';
import { createAssignment, listTeacherProblems } from '../../api';
import type { AssignmentMode, ScorePolicy } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, errMessage } from '../../components/StateViews';
import { toUtcString } from '../../components/time';
import { NumberInput } from '../../components/NumberInput';

interface SelectedProblem {
  problem_id: number;
  full_score: number;
}

export function TeacherAssignmentNew() {
  const t = useTheme();
  const navigate = useNavigate();
  const { data: problems, error, loading, reload } = useAsync(listTeacherProblems, []);

  const [title, setTitle] = useState('');
  const [mode, setMode] = useState<AssignmentMode>('homework');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [limitEnabled, setLimitEnabled] = useState(false);
  const [maxSubmissions, setMaxSubmissions] = useState<number>(3);
  const [scorePolicy, setScorePolicy] = useState<ScorePolicy>('best');
  const [selected, setSelected] = useState<SelectedProblem[]>([]);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const selectedIds = useMemo(() => new Set(selected.map((s) => s.problem_id)), [selected]);

  const toggleProblem = (problemId: number, checked: boolean) => {
    setSelected((prev) =>
      checked ? [...prev, { problem_id: problemId, full_score: 100 }] : prev.filter((s) => s.problem_id !== problemId),
    );
  };

  const setFullScore = (problemId: number, full_score: number) => {
    setSelected((prev) => prev.map((s) => (s.problem_id === problemId ? { ...s, full_score } : s)));
  };

  const handleSubmit = async () => {
    setFormError(null);
    if (!title.trim()) return setFormError('请输入场次标题');
    if (!startTime || !endTime) return setFormError('请选择开始与结束时间');
    if (toUtcString(endTime) <= toUtcString(startTime)) return setFormError('结束时间必须晚于开始时间');
    if (selected.length === 0) return setFormError('请至少选择一道题目');

    setBusy(true);
    try {
      const created = await createAssignment({
        title: title.trim(),
        mode,
        start_time: toUtcString(startTime),
        end_time: toUtcString(endTime),
        max_submissions: limitEnabled ? maxSubmissions : null,
        score_policy: scorePolicy,
        problems: selected.map((s, i) => ({ problem_id: s.problem_id, seq: i + 1, full_score: s.full_score })),
      });
      navigate(`/teacher/assignments/${created.id}`, { replace: true });
    } catch (err) {
      setFormError(errMessage(err));
      setBusy(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate('/teacher/assignments')}>← 返回场次列表</Button>
        </Caption1>
        <Text as="h2" size={600} weight="semibold">发布作业 / 测试</Text>
      </div>

      {formError && (
        <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{formError}</MessageBarBody>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">基本信息</Text>} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Field label="标题" required>
            <Input value={title} onChange={(_, d) => setTitle(d.value)} placeholder="如：第 3 周 C 语言作业" />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: tokens.spacingHorizontalM }}>
            <Field label="模式" hint="作业即时可见判定；测试需结束后手动放出。">
              <Dropdown
                value={mode === 'homework' ? '作业' : '测试'}
                selectedOptions={[mode]}
                onOptionSelect={(_, d) => setMode(d.optionValue as AssignmentMode)}
              >
                <Option value="homework">作业</Option>
                <Option value="test">测试</Option>
              </Dropdown>
            </Field>
            <Field label="开始时间" required>
              <Input type="datetime-local" value={startTime} onChange={(_, d) => setStartTime(d.value)} />
            </Field>
            <Field label="结束时间" required>
              <Input type="datetime-local" value={endTime} onChange={(_, d) => setEndTime(d.value)} />
            </Field>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: tokens.spacingHorizontalM }}>
            <Field label="计分策略">
              <Dropdown
                value={scorePolicy === 'best' ? '取历次最高分' : '取最后一次提交'}
                selectedOptions={[scorePolicy]}
                onOptionSelect={(_, d) => setScorePolicy(d.optionValue as ScorePolicy)}
              >
                <Option value="best">取历次最高分（best）</Option>
                <Option value="last">取最后一次提交（last）</Option>
              </Dropdown>
            </Field>
            <Field label="提交次数限制">
              <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM }}>
                <Checkbox checked={limitEnabled} onChange={(_, d) => setLimitEnabled(Boolean(d.checked))} label="限制次数" />
                <NumberInput
                  value={maxSubmissions}
                  min={1}
                  disabled={!limitEnabled}
                  onValue={setMaxSubmissions}
                  width="120px"
                />
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>不勾选则不限次数</Caption1>
              </div>
            </Field>
          </div>
        </div>
      </Card>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">选题（已选 {selected.length} 题）</Text>} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
          {(problems ?? []).map((p) => {
            const sel = selected.find((s) => s.problem_id === p.id);
            return (
              <div
                key={p.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: tokens.spacingHorizontalM,
                  padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
                  borderRadius: tokens.borderRadiusMedium,
                  backgroundColor: sel ? t.colorBrandBackground2 : 'transparent',
                  border: `1px solid ${sel ? t.colorBrandStroke1 : t.colorNeutralStroke3}`,
                }}
              >
                <Checkbox
                  checked={selectedIds.has(p.id)}
                  onChange={(_, d) => toggleProblem(p.id, Boolean(d.checked))}
                  label={p.title}
                  style={{ flex: 1 }}
                />
                {sel && (
                  <Field label="满分" size="small" style={{ minWidth: '140px' }}>
                    <NumberInput
                      value={sel.full_score}
                      min={1}
                      onValue={(v) => setFullScore(p.id, v)}
                    />
                  </Field>
                )}
              </div>
            );
          })}
          {(problems ?? []).length === 0 && (
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>题库为空，请先到「题库」创建题目。</Caption1>
          )}
        </div>
      </Card>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button appearance="primary" size="large" icon={<Send24Regular />} onClick={handleSubmit} disabled={busy}>
          {busy ? '发布中…' : '发布'}
        </Button>
      </div>
    </div>
  );
}
