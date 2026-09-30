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
  Radio,
  RadioGroup,
  Text,
  tokens,

} from '@fluentui/react-components';
import { Send24Regular } from '@fluentui/react-icons';
import { createAssignment, listTeacherProblems, listTeacherSubgroups } from '../../api';
import type { AssignmentMode, AudienceMode, ScorePolicy } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, errMessage } from '../../components/StateViews';
import { toUtcString } from '../../components/time';
import { NumberInput } from '../../components/NumberInput';
import { PageHeader } from '../../components/PageHeader';

interface SelectedProblem {
  problem_id: number;
  full_score: number;
}

export function TeacherAssignmentNew() {
  const t = useTheme();
  const navigate = useNavigate();
  const { data: problems, error, loading, reload } = useAsync(listTeacherProblems, []);
  const { data: subgroupData, error: subgroupError } = useAsync(listTeacherSubgroups, []);

  const [title, setTitle] = useState('');
  const [mode, setMode] = useState<AssignmentMode>('homework');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [limitEnabled, setLimitEnabled] = useState(false);
  const [maxSubmissions, setMaxSubmissions] = useState<number>(3);
  const [scorePolicy, setScorePolicy] = useState<ScorePolicy>('best');
  const [audienceMode, setAudienceMode] = useState<AudienceMode>('all');
  const [pickedSubgroups, setPickedSubgroups] = useState<number[]>([]);
  const [selected, setSelected] = useState<SelectedProblem[]>([]);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const subgroups = useMemo(() => subgroupData ?? [], [subgroupData]);
  const selectedIds = useMemo(() => new Set(selected.map((s) => s.problem_id)), [selected]);

  const toggleSubgroup = (subgroupId: number, checked: boolean) => {
    setPickedSubgroups((prev) => (
      checked ? [...prev, subgroupId] : prev.filter((id) => id !== subgroupId)
    ));
  };

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
    if (audienceMode === 'subgroup' && pickedSubgroups.length === 0) {
      return setFormError('请至少选择一个子分组作为发布受众');
    }

    setBusy(true);
    try {
      const created = await createAssignment({
        title: title.trim(),
        mode,
        start_time: toUtcString(startTime),
        end_time: toUtcString(endTime),
        max_submissions: limitEnabled ? maxSubmissions : null,
        score_policy: scorePolicy,
        audience_mode: audienceMode,
        subgroup_ids: audienceMode === 'subgroup' ? pickedSubgroups : [],
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
        <PageHeader title="发布作业 / 考试" />
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
            <Field label="模式">
              <Dropdown
                value={mode === 'homework' ? '作业' : '考试'}
                selectedOptions={[mode]}
                onOptionSelect={(_, d) => setMode(d.optionValue as AssignmentMode)}
              >
                <Option value="homework" text="作业">
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span>作业</span>
                    <Caption1 style={{ color: t.colorNeutralForeground3 }}>即时可见判定</Caption1>
                  </div>
                </Option>
                <Option value="test" text="考试">
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span>考试</span>
                    <Caption1 style={{ color: t.colorNeutralForeground3 }}>结束后手动放出</Caption1>
                  </div>
                </Option>
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

          <Field label="发布受众">
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
              <RadioGroup
                layout="horizontal"
                value={audienceMode}
                onChange={(_, d) => setAudienceMode(d.value as AudienceMode)}
              >
                <Radio value="all" label="全部名单" />
                <Radio value="subgroup" label="指定子分组" disabled={subgroups.length === 0} />
              </RadioGroup>

              {audienceMode === 'all' ? (
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  你名单里的所有学生都能看到本场次。
                </Caption1>
              ) : subgroupError ? (
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  {`子分组暂时读不到，本次只能选「全部名单」：${errMessage(subgroupError)}`}
                </Caption1>
              ) : subgroups.length === 0 ? (
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  还没有子分组，请先到「学生」页创建，或改选「全部名单」。
                </Caption1>
              ) : (
                <>
                  <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                    仅勾选的子分组能收到本场次；子分组在「学生」页维护，可随时调整成员。
                  </Caption1>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalL }}>
                    {subgroups.map((sg) => (
                      <Checkbox
                        key={sg.id}
                        checked={pickedSubgroups.includes(sg.id)}
                        onChange={(_, d) => toggleSubgroup(sg.id, Boolean(d.checked))}
                        label={`${sg.name}（${sg.member_count} 人）`}
                      />
                    ))}
                  </div>
                </>
              )}
            </div>
          </Field>
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
