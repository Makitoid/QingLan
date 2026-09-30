import { useTheme } from '../../appTheme';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Caption1,
  Card,
  CardHeader,
  Checkbox,
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
  Radio,
  RadioGroup,
  Text,
  tokens,

} from '@fluentui/react-components';
import { Add24Regular, CheckboxChecked24Regular, Send24Regular } from '@fluentui/react-icons';
import { createAssignment, listTeacherProblems, listTeacherSubgroups } from '../../api';
import type { AssignmentMode, AudienceMode, ProblemSummary, ScorePolicy } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, errMessage } from '../../components/StateViews';
import { toUtcString } from '../../components/time';
import { NumberInput } from '../../components/NumberInput';
import { PageHeader } from '../../components/PageHeader';

interface SelectedProblem {
  problem_id: number;
  full_score: number;
}

/** 分组筛选的特殊选项值；正常分组名不会以 `__` 开头，两者不会冲突。 */
const GROUP_ALL = '__all__';
const GROUP_NONE = '__none__';

/** 「按题目 ID 添加」的输入分隔符：半/全角逗号、分号、空白都认。 */
const ID_SEPARATOR = /[,，;；\s]+/;

/** 题库分组是自由文本（可空），比较与展示前统一去掉首尾空白。 */
function groupOf(problem: ProblemSummary): string {
  return (problem.group_name ?? '').trim();
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

  // 0.4.0 F2：分组筛选 + 按题目 ID 添加（纯前端，提交体不变）
  const [groupFilter, setGroupFilter] = useState(GROUP_ALL);
  const [addByIdOpen, setAddByIdOpen] = useState(false);
  const [probIdText, setProbIdText] = useState('');
  const [addByIdError, setAddByIdError] = useState<string | null>(null);

  const subgroups = useMemo(() => subgroupData ?? [], [subgroupData]);
  const selectedIds = useMemo(() => new Set(selected.map((s) => s.problem_id)), [selected]);
  const problemList = useMemo(() => problems ?? [], [problems]);

  /** 下拉选项：全部分组 + 本页数据里出现过的分组（排序）+ 未分组。 */
  const groupOptions = useMemo(() => {
    const names = Array
      .from(new Set(problemList.map(groupOf).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
    return [
      { value: GROUP_ALL, label: '全部分组' },
      ...names.map((name) => ({ value: name, label: name })),
      { value: GROUP_NONE, label: '未分组' },
    ];
  }, [problemList]);

  const filtered = useMemo(
    () => problemList.filter((problem) => {
      const group = groupOf(problem);
      if (groupFilter === GROUP_NONE) return group === '';
      if (groupFilter !== GROUP_ALL) return group === groupFilter;
      return true;
    }),
    [problemList, groupFilter],
  );

  const idTokens = probIdText.split(ID_SEPARATOR).map((x) => x.trim()).filter(Boolean);
  const idBadTokens = idTokens.filter((x) => !/^\d+$/.test(x));
  const parsedIds = useMemo(
    () => Array.from(new Set(idTokens.filter((x) => /^\d+$/.test(x)).map(Number))).filter((n) => n > 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [probIdText],
  );

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

  /** 「全选该组」：当前筛选结果里未选者全部加入，默认满分沿用 toggleProblem。 */
  const selectAllFiltered = () => {
    filtered.forEach((p) => {
      if (!selectedIds.has(p.id)) toggleProblem(p.id, true);
    });
  };

  /** 按题目 ID 添加：任一无效（不在本人题库）整批拒绝并列出无效 ID。 */
  const handleAddByIds = () => {
    if (parsedIds.length === 0) return;
    const known = new Set(problemList.map((p) => p.id));
    const invalid = parsedIds.filter((id) => !known.has(id));
    if (invalid.length > 0) {
      setAddByIdError(`无效的题目 ID：${invalid.join('、')}，本次未添加任何题目。`);
      return;
    }
    parsedIds.forEach((id) => {
      if (!selectedIds.has(id)) toggleProblem(id, true);
    });
    setAddByIdError(null);
    setProbIdText('');
    setAddByIdOpen(false);
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
        <div style={{ display: 'flex', gap: tokens.spacingHorizontalM, alignItems: 'center', flexWrap: 'wrap' }}>
          <Dropdown
            selectedOptions={[groupFilter]}
            value={groupOptions.find((o) => o.value === groupFilter)?.label}
            onOptionSelect={(_, d) => setGroupFilter(d.optionValue || GROUP_ALL)}
            style={{ minWidth: '170px' }}
          >
            {groupOptions.map((o) => (
              <Option key={o.value} value={o.value}>{o.label}</Option>
            ))}
          </Dropdown>
          <Button
            appearance="secondary"
            icon={<CheckboxChecked24Regular />}
            onClick={selectAllFiltered}
            disabled={filtered.length === 0}
          >
            全选该组
          </Button>
          <Button
            appearance="secondary"
            icon={<Add24Regular />}
            onClick={() => { setAddByIdError(null); setAddByIdOpen(true); }}
          >
            按题目 ID 添加
          </Button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
          {filtered.map((p) => {
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
          {filtered.length === 0 && problemList.length > 0 && (
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>该筛选下没有题目。</Caption1>
          )}
          {problemList.length === 0 && (
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>题库为空，请先到「题库」创建题目。</Caption1>
          )}
        </div>
      </Card>

      <Dialog open={addByIdOpen} onOpenChange={(_, d) => setAddByIdOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>按题目 ID 添加</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  题目 ID 来自「题库」列表第一列，可一次给多个，用逗号或空格分隔。
                </Caption1>
                <Field label="题目 ID" required>
                  <Input
                    value={probIdText}
                    onChange={(_, d) => setProbIdText(d.value)}
                    placeholder="例如：12, 34 56"
                    autoFocus
                  />
                </Field>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  {parsedIds.length > 0
                    ? `识别到 ${parsedIds.length} 个题目 ID。`
                    : '还没有识别到有效的数字 ID。'}
                  {idBadTokens.length > 0 && ` 其中「${idBadTokens.join('、')}」不是数字 ID，会被忽略。`}
                </Caption1>
                {addByIdError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{addByIdError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setAddByIdOpen(false)}>取消</Button>
              <Button
                appearance="primary"
                icon={<Add24Regular />}
                disabled={parsedIds.length === 0}
                onClick={handleAddByIds}
              >
                {`确认添加${parsedIds.length > 0 ? `（${parsedIds.length} 个 ID）` : ''}`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button appearance="primary" size="large" icon={<Send24Regular />} onClick={handleSubmit} disabled={busy}>
          {busy ? '发布中…' : '发布'}
        </Button>
      </div>
    </div>
  );
}
