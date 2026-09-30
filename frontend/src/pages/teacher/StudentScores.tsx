import { useTheme } from '../../appTheme';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Caption1,
  createTableColumn, DataGrid,
  DataGridBody,
  DataGridCell,
  DataGridHeader,
  DataGridHeaderCell,
  DataGridRow,
  MessageBar,
  MessageBarBody,
  Text,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Delete24Regular, Save24Regular } from '@fluentui/react-icons';
import { getAssignmentStudentProblems, setManualScore } from '../../api';
import type { StudentProblemScoreRow } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { NumberInput } from '../../components/NumberInput';
import { fmtScore } from '../../components/score';
import { PageHeader } from '../../components/PageHeader';

const columns: TableColumnDefinition<StudentProblemScoreRow>[] = [
  createTableColumn({ columnId: 'problem', renderHeaderCell: () => '题目' }),
  createTableColumn({ columnId: 'full_score', renderHeaderCell: () => '满分' }),
  createTableColumn({ columnId: 'submission_count', renderHeaderCell: () => '提交次数' }),
  createTableColumn({ columnId: 'score', renderHeaderCell: () => '系统分' }),
  createTableColumn({ columnId: 'manual', renderHeaderCell: () => '教师调分' }),
  createTableColumn({ columnId: 'effective', renderHeaderCell: () => '有效分' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '操作' }),
];

export function TeacherStudentScores() {
  const { id, sid } = useParams();
  const t = useTheme();
  const navigate = useNavigate();
  const assignmentId = Number(id);
  const studentId = Number(sid);
  const { data, error, loading, reload } = useAsync<StudentProblemScoreRow[]>(
    () => getAssignmentStudentProblems(assignmentId, studentId),
    [assignmentId, studentId],
  );
  const [drafts, setDrafts] = useState<Record<number, number>>({});
  const [busyProblem, setBusyProblem] = useState<number | null>(null);
  const [message, setMessage] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  const submit = async (row: StudentProblemScoreRow, value: number | null) => {
    if (row.latest_submission_id === null) {
      setMessage({ intent: 'error', text: `第 ${row.seq} 题暂无提交，无法调分` });
      return;
    }
    if (value === null) {
      setMessage({ intent: 'error', text: '请先输入调分数值' });
      return;
    }
    setBusyProblem(row.problem_id);
    setMessage(null);
    try {
      await setManualScore(row.latest_submission_id, value);
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[row.problem_id];
        return next;
      });
      setMessage({ intent: 'success', text: `第 ${row.seq} 题调分已保存` });
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusyProblem(null);
    }
  };

  const revoke = async (row: StudentProblemScoreRow) => {
    if (row.latest_submission_id === null) return;
    setBusyProblem(row.problem_id);
    setMessage(null);
    try {
      await setManualScore(row.latest_submission_id, null);
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[row.problem_id];
        return next;
      });
      setMessage({ intent: 'success', text: `第 ${row.seq} 题已撤销调分，恢复系统判分` });
      reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusyProblem(null);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate(`/teacher/assignments/${assignmentId}/students`)}>
            ← 返回逐学生表
          </Button>
        </Caption1>
        <PageHeader
          title={`学生 #${studentId} 逐题成绩与调分`}
          subtitle="「系统分」与「教师调分」取自该题最新一次提交，调分也只作用于该条；「有效分」按本场次计分策略聚合该题全部提交，best 策略下可能不等于系统分。"
        />
      </div>

      {message && (
        <MessageBar intent={message.intent} style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{message.text}</MessageBarBody>
        </MessageBar>
      )}

      {data && data.length === 0 ? (
        <EmptyView title="该场次没有题目" description="题单为空，无法逐题调分。" />
      ) : (
        <DataGrid items={data ?? []} columns={columns} focusMode="cell" resizableColumns>
          <DataGridHeader>
            <DataGridRow>
              {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
            </DataGridRow>
          </DataGridHeader>
          <DataGridBody<StudentProblemScoreRow>>
            {({ item, rowId }) => (
              <DataGridRow<StudentProblemScoreRow> key={rowId}>
                {({ columnId }) => (
                  <DataGridCell>
                    {columnId === 'problem' && (
                      <Text>
                        第 {item.seq} 题 ·{' '}
                        <Link to={`/teacher/problems/${item.problem_id}`} style={{ color: t.colorBrandForeground1 }}>
                          {item.title}
                        </Link>
                      </Text>
                    )}
                    {columnId === 'full_score' && fmtScore(item.full_score)}
                    {columnId === 'submission_count' && item.submission_count}
                    {columnId === 'score' && fmtScore(item.score)}
                    {columnId === 'manual' && (
                      <NumberInput
                        value={drafts[item.problem_id] ?? item.manual_score ?? undefined}
                        min={0}
                        disabled={busyProblem === item.problem_id || item.latest_submission_id === null}
                        onValue={(v) => setDrafts((prev) => ({ ...prev, [item.problem_id]: v }))}
                        width="120px"
                      />
                    )}
                    {columnId === 'effective' && fmtScore(item.effective_score)}
                    {columnId === 'actions' && (
                      <div style={{ display: 'flex', gap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap' }}>
                        <Button
                          appearance="primary"
                          size="small"
                          icon={<Save24Regular />}
                          disabled={busyProblem === item.problem_id || item.latest_submission_id === null}
                          onClick={() => submit(item, drafts[item.problem_id] ?? null)}
                        >
                          保存
                        </Button>
                        <Button
                          appearance="secondary"
                          size="small"
                          icon={<Delete24Regular />}
                          disabled={busyProblem === item.problem_id || item.manual_score === null}
                          onClick={() => revoke(item)}
                        >
                          撤销
                        </Button>
                        {item.latest_submission_id === null ? (
                          <Caption1 style={{ color: t.colorNeutralForeground4 }}>暂无提交</Caption1>
                        ) : (
                          <Link to={`/teacher/submissions/${item.latest_submission_id}`} style={{ color: t.colorBrandForeground1 }}>
                            查看最新提交
                          </Link>
                        )}
                      </div>
                    )}
                  </DataGridCell>
                )}
              </DataGridRow>
            )}
          </DataGridBody>
        </DataGrid>
      )}
    </div>
  );
}
