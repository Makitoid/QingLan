import { useTheme } from '../../appTheme';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  createTableColumn, DataGrid,
  DataGridBody,
  DataGridCell,
  DataGridHeader,
  DataGridHeaderCell,
  DataGridRow,
  Text,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { getAssignmentStudents } from '../../api';
import type { AssignmentStudentRow } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';

const columns: TableColumnDefinition<AssignmentStudentRow>[] = [
  createTableColumn({ columnId: 'name', renderHeaderCell: () => '学生' }),
  createTableColumn({ columnId: 'submitted_count', renderHeaderCell: () => '提交次数' }),
  createTableColumn({ columnId: 'best', renderHeaderCell: () => '最佳有效分' }),
  createTableColumn({ columnId: 'last_submitted_at', renderHeaderCell: () => '最后提交时间' }),
  createTableColumn({ columnId: 'drill', renderHeaderCell: () => '下钻' }),
];

export function TeacherAssignmentStudents() {
  const { id } = useParams();
  const t = useTheme();
  const navigate = useNavigate();
  const assignmentId = Number(id);
  const { data, error, loading, reload } = useAsync<AssignmentStudentRow[]>(
    () => getAssignmentStudents(assignmentId),
    [assignmentId],
  );

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate(`/teacher/assignments/${assignmentId}`)}>
            ← 返回场次总览
          </Button>
        </Caption1>
        <Text as="h2" size={600} weight="semibold">逐学生成绩</Text>
      </div>

      {data && data.length === 0 ? (
        <EmptyView title="暂无学生" description="该场次受众为空，请检查教师↔学生绑定关系。" />
      ) : (
        <DataGrid items={data ?? []} columns={columns} focusMode="cell" resizableColumns>
          <DataGridHeader>
            <DataGridRow>
              {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
            </DataGridRow>
          </DataGridHeader>
          <DataGridBody<AssignmentStudentRow>>
            {({ item, rowId }) => (
              <DataGridRow<AssignmentStudentRow> key={rowId}>
                {({ columnId }) => (
                  <DataGridCell>
                    {columnId === 'name' && (
                      <Text weight={item.submitted_count === 0 ? 'regular' : 'semibold'}>
                        {item.name}
                        {item.submitted_count === 0 && (
                          <Badge size="small" style={{ marginLeft: tokens.spacingHorizontalS, color: t.colorPaletteRedForeground1, backgroundColor: t.colorPaletteRedBackground2 }}>
                            未交
                          </Badge>
                        )}
                      </Text>
                    )}
                    {columnId === 'submitted_count' && item.submitted_count}
                    {columnId === 'best' && fmtScore(item.best_effective_score)}
                    {columnId === 'last_submitted_at' && fmtTime(item.last_submitted_at)}
                    {columnId === 'drill' &&
                      (item.last_submission_id ? (
                        <Link to={`/teacher/submissions/${item.last_submission_id}`} style={{ color: t.colorBrandForeground1 }}>
                          查看提交
                        </Link>
                      ) : (
                        <Caption1 style={{ color: t.colorNeutralForeground4 }}>—</Caption1>
                      ))}
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
