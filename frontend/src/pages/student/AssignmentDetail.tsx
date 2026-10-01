import { useTheme } from '../../appTheme';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Badge, Button, Caption1, createTableColumn, DataGrid, DataGridBody, DataGridCell, DataGridHeader, DataGridHeaderCell, DataGridRow, tokens, type TableColumnDefinition } from '@fluentui/react-components';
import { getStudentAssignment } from '../../api';
import type { StudentAssignmentDetail as Detail, StudentAssignmentProblem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';
import { PageHeader } from '../../components/PageHeader';
import { AssignmentStateBadge } from '../../components/VerdictBadge';

const columns: TableColumnDefinition<StudentAssignmentProblem>[] = [
  createTableColumn({ columnId: 'seq', renderHeaderCell: () => '#' }),
  createTableColumn({ columnId: 'title', renderHeaderCell: () => '题目' }),
  createTableColumn({ columnId: 'full_score', renderHeaderCell: () => '满分' }),
  createTableColumn({ columnId: 'my_score', renderHeaderCell: () => '我的成绩' }),
];

export function StudentAssignmentDetail() {
  const { id } = useParams();
  const t = useTheme();
  const navigate = useNavigate();
  const assignmentId = Number(id);
  const { data, error, loading, reload } = useAsync<Detail>(() => getStudentAssignment(assignmentId), [assignmentId]);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <Caption1>
        <Button appearance="subtle" size="small" onClick={() => navigate('/student/assignments')}>
          ← 返回考试列表
        </Button>
      </Caption1>
      <PageHeader
        title={data.title}
        subtitle={<>时间窗：{fmtTime(data.start_time)} ~ {fmtTime(data.end_time)} · 计分策略：{data.score_policy === 'best' ? '取历次最高分' : '取最后一次提交'}</>}
        actions={
          <>
            <Badge appearance="outline" size="large">{data.mode === 'homework' ? '作业' : '测试'}</Badge>
            <AssignmentStateBadge state={data.state} />
          </>
        }
      />

      <DataGrid items={data.my_scores} columns={columns} focusMode="cell">
        <DataGridHeader>
          <DataGridRow>
            {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
          </DataGridRow>
        </DataGridHeader>
        <DataGridBody<StudentAssignmentProblem>>
          {({ item, rowId }) => (
            <DataGridRow<StudentAssignmentProblem> key={rowId}>
              {({ columnId }) => (
                <DataGridCell>
                  {columnId === 'seq' && item.seq}
                  {columnId === 'title' && (
                    <Link
                      to={`/student/assignments/${data.id}/problems/${item.problem_id}`}
                      style={{ color: t.colorBrandForeground1, fontWeight: tokens.fontWeightSemibold }}
                    >
                      {item.title}
                    </Link>
                  )}
                  {columnId === 'full_score' && item.full_score}
                  {columnId === 'my_score' && fmtScore(item.effective_score)}
                </DataGridCell>
              )}
            </DataGridRow>
          )}
        </DataGridBody>
      </DataGrid>
      {data.mode === 'test' && (
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          测试模式：成绩在教师放出前不可见，显示为「—」。
        </Caption1>
      )}
    </div>
  );
}
