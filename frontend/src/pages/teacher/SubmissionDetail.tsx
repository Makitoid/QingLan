import { useTheme } from '../../appTheme';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
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
  Field,
  MessageBar,
  MessageBarBody,
  Text,
  tokens,
  type TableColumnDefinition,
} from '@fluentui/react-components';
import { ArrowSync24Regular, Save24Regular, Delete24Regular } from '@fluentui/react-icons';
import { getTeacherSubmission, rejudgeSubmission, setManualScore } from '../../api';
import type { SubmissionResultRow, TeacherSubmissionDetail as Detail } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, errMessage } from '../../components/StateViews';
import { NumberInput } from '../../components/NumberInput';
import { fmtTimeWithSeconds } from '../../components/time';
import { fmtScore } from '../../components/score';
import { CodeEditor } from '../../components/CodeEditor';
import { StatusBadge, VerdictBadge } from '../../components/VerdictBadge';
import { PageHeader } from '../../components/PageHeader';

const columns: TableColumnDefinition<SubmissionResultRow>[] = [
  createTableColumn({ columnId: 'seq', renderHeaderCell: () => '测试点' }),
  createTableColumn({ columnId: 'kind', renderHeaderCell: () => '类型' }),
  createTableColumn({ columnId: 'verdict', renderHeaderCell: () => '判定' }),
  createTableColumn({ columnId: 'time', renderHeaderCell: () => '耗时' }),
  createTableColumn({ columnId: 'memory', renderHeaderCell: () => '内存' }),
  createTableColumn({ columnId: 'score', renderHeaderCell: () => '得分' }),
];

export function TeacherSubmissionPage() {
  const { sid } = useParams();
  const t = useTheme();
  const navigate = useNavigate();
  const submissionId = Number(sid);
  const { data, error, loading, reload } = useAsync<Detail>(() => getTeacherSubmission(submissionId), [submissionId]);

  const [manualScore, setManualScoreState] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  const handleRejudge = async () => {
    if (!window.confirm('确定重判该提交？现有逐点结果将被清空并重新判题。')) return;
    setBusy(true);
    setMessage(null);
    try {
      await rejudgeSubmission(submissionId);
      setMessage({ intent: 'success', text: '已置回待判题，稍后刷新查看结果' });
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleSetScore = async () => {
    if (manualScore === null) {
      setMessage({ intent: 'error', text: '请先输入调分数值' });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await setManualScore(submissionId, manualScore);
      setMessage({ intent: 'success', text: '调分已保存' });
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleClearScore = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await setManualScore(submissionId, null);
      setManualScoreState(null);
      setMessage({ intent: 'success', text: '已撤销调分，恢复系统判分' });
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;
  if (!data) return null;

  const effectiveScore = data.manual_score ?? data.score;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate(`/teacher/assignments/${data.assignment_id}/students`)}>
            ← 返回逐学生表
          </Button>
        </Caption1>
        <PageHeader
          title={<>提交 #{data.id}</>}
          subtitle={
            <>
              {data.problem_title && (
                <>
                  题目：
                  <Link to={`/teacher/problems/${data.problem_id}`} style={{ color: t.colorBrandForeground1 }}>{data.problem_title}</Link>
                  {' · '}
                </>
              )}
              {data.student_name && <>学生：{data.student_name} · </>}
              提交时间：{fmtTimeWithSeconds(data.submitted_at)} · 判题时间：{fmtTimeWithSeconds(data.judged_at)}
            </>
          }
          actions={
            <>
              <StatusBadge status={data.status} />
              <VerdictBadge verdict={data.verdict} />
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
        <CardHeader
          header={<Text weight="semibold">判分与操作</Text>}
          action={
            <Button appearance="secondary" icon={<ArrowSync24Regular />} onClick={handleRejudge} disabled={busy}>
              重判
            </Button>
          }
        />
        <div style={{ display: 'flex', gap: tokens.spacingHorizontalL, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="系统判分">
            <Text size={500}>{fmtScore(data.score)}</Text>
          </Field>
          <Field label="教师调分">
            <Text size={500} style={{ color: data.manual_score !== null ? t.colorPaletteDarkOrangeForeground1 : t.colorNeutralForeground3 }}>
              {data.manual_score === null ? '未调分' : fmtScore(data.manual_score)}
            </Text>
          </Field>
          <Field label="有效分">
            <Text size={500} weight="bold" style={{ color: t.colorBrandForeground1 }}>
              {effectiveScore === null ? '—' : effectiveScore}
            </Text>
          </Field>
          <Field label="手动调分">
            <div style={{ display: 'flex', gap: tokens.spacingHorizontalS }}>
              <NumberInput
                value={manualScore}
                min={0}
                onValue={(v) => setManualScoreState(v)}
                width="140px"
              />
              <Button appearance="primary" icon={<Save24Regular />} onClick={handleSetScore} disabled={busy}>保存</Button>
              {data.manual_score !== null && (
                <Button appearance="secondary" icon={<Delete24Regular />} onClick={handleClearScore} disabled={busy}>
                  撤销调分
                </Button>
              )}
            </div>
          </Field>
        </div>
        {data.judge_log && (
          <MessageBar intent="warning" style={{ marginTop: tokens.spacingVerticalM, borderRadius: tokens.borderRadiusMedium }}>
            <MessageBarBody>
              判题日志（仅教师可见）：
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'Consolas, monospace' }}>{data.judge_log}</pre>
            </MessageBarBody>
          </MessageBar>
        )}
      </Card>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">提交的代码（只读）</Text>} />
        <CodeEditor value={data.code_text} readOnly height="360px" />
      </Card>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">逐测试点结果（{data.results.length}）</Text>} />
        {data.results.length === 0 ? (
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            {data.status === 'pending' || data.status === 'judging' ? '判题进行中，稍后刷新。' : '暂无逐点结果。'}
          </Caption1>
        ) : (
          <DataGrid items={data.results} columns={columns} focusMode="cell">
            <DataGridHeader>
              <DataGridRow>
                {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
              </DataGridRow>
            </DataGridHeader>
            <DataGridBody<SubmissionResultRow>>
              {({ item, rowId }) => (
                <DataGridRow<SubmissionResultRow> key={rowId}>
                  {({ columnId }) => (
                    <DataGridCell>
                      {columnId === 'seq' && item.seq}
                      {columnId === 'kind' && (
                        <Caption1 style={{ color: t.colorNeutralForeground3 }}>{item.is_sample ? '样例' : '隐藏'}</Caption1>
                      )}
                      {columnId === 'verdict' && <VerdictBadge verdict={item.verdict} short />}
                      {columnId === 'time' && `${item.time_ms} ms`}
                      {columnId === 'memory' && `${item.memory_kb} KB`}
                      {columnId === 'score' && fmtScore(item.score)}
                    </DataGridCell>
                  )}
                </DataGridRow>
              )}
            </DataGridBody>
          </DataGrid>
        )}
      </Card>

      <Caption1>
        <Button appearance="subtle" size="small" onClick={() => navigate(-1)}>← 返回</Button>
      </Caption1>
    </div>
  );
}
