import { useTheme } from '../../appTheme';
import { Link, useParams } from 'react-router-dom';
import { Badge, Caption1, createTableColumn, DataGrid, DataGridBody, DataGridCell, DataGridHeader, DataGridHeaderCell, DataGridRow, Text, tokens, type TableColumnDefinition } from '@fluentui/react-components';
import { getStudentAssignment } from '../../api';
import type { StudentAssignmentDetail as Detail, StudentAssignmentProblem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';

const columns: TableColumnDefinition<StudentAssignmentProblem>[] = [
  createTableColumn({ columnId: 'seq', renderHeaderCell: () => '#' }),
  createTableColumn({ columnId: 'title', renderHeaderCell: () => '题目' }),
  createTableColumn({ columnId: 'full_score', renderHeaderCell: () => '满分' }),
  createTableColumn({ columnId: 'my_score', renderHeaderCell: () => '我的成绩' }),
];

export function StudentAssignmentDetail() {
  const { id } = useParams();
  const t = useTheme();
  const assignmentId = Number(id);
  const { data, error, loading, reload } = useAsync<Detail>(() => getStudentAssignment(assignmentId), [assignmentId]);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM }}>
        <Text as="h2" size={600} weight="semibold">{data.title}</Text>
        <Badge appearance="outline" size="small">{data.mode === 'homework' ? '作业' : '测试'}</Badge>
        <Badge
          size="small"
          style={
            data.state === 'ongoing'
              ? { color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }
              : { color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }
          }
        >
          {data.state === 'ongoing' ? '进行中' : '已结束'}
        </Badge>
      </div>
      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
        时间窗：{fmtTime(data.start_time)} ~ {fmtTime(data.end_time)} · 计分策略：{data.score_policy === 'best' ? '取历次最高分' : '取最后一次提交'}
      </Caption1>

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
