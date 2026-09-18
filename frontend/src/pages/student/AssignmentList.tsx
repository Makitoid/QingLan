import { useTheme } from '../../appTheme';
import { Link } from 'react-router-dom';
import { Badge, Caption1, createTableColumn, DataGrid, DataGridCell, DataGridRow, DataGridHeaderCell, DataGridBody, DataGridHeader, Text, tokens, type TableColumnDefinition } from '@fluentui/react-components';
import { listStudentAssignments } from '../../api';
import type { StudentAssignmentItem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';

const columns: TableColumnDefinition<StudentAssignmentItem>[] = [
  createTableColumn({ columnId: 'title', renderHeaderCell: () => '场次' }),
  createTableColumn({ columnId: 'mode', renderHeaderCell: () => '模式' }),
  createTableColumn({ columnId: 'window', renderHeaderCell: () => '时间窗' }),
  createTableColumn({ columnId: 'state', renderHeaderCell: () => '状态' }),
  createTableColumn({ columnId: 'score', renderHeaderCell: () => '我的得分' }),
];

export function StudentAssignmentList() {
  const t = useTheme();
  const { data, error, loading, reload } = useAsync(listStudentAssignments, []);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <Text as="h2" size={600} weight="semibold">我的场次</Text>
      {data && data.length === 0 ? (
        <EmptyView title="暂无场次" description="老师发布作业或测试后会出现在这里。" />
      ) : (
        <DataGrid items={data ?? []} columns={columns} focusMode="cell" resizableColumns>
          <DataGridHeader>
            <DataGridRow>
              {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
            </DataGridRow>
          </DataGridHeader>
          <DataGridBody<StudentAssignmentItem>>
            {({ item, rowId }) => (
              <DataGridRow<StudentAssignmentItem> key={rowId}>
                {({ columnId }) => (
                  <DataGridCell>
                    {columnId === 'title' && (
                      <Link to={`/student/assignments/${item.id}`} style={{ color: t.colorBrandForeground1, fontWeight: tokens.fontWeightSemibold }}>
                        {item.title}
                      </Link>
                    )}
                    {columnId === 'mode' && (
                      <Badge appearance="outline" size="small">
                        {item.mode === 'homework' ? '作业' : '测试'}
                      </Badge>
                    )}
                    {columnId === 'window' && (
                      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                        {fmtTime(item.start_time)} ~ {fmtTime(item.end_time)}
                      </Caption1>
                    )}
                    {columnId === 'state' && (
                      <Badge
                        size="small"
                        style={
                          item.state === 'ongoing'
                            ? { color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }
                            : { color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }
                        }
                      >
                        {item.state === 'ongoing' ? '进行中' : '已结束'}
                      </Badge>
                    )}
                    {columnId === 'score' &&
                      (() => {
                        const rows = item.my_scores ?? [];
                        const total = rows.reduce((s, r) => s + r.full_score, 0);
                        const scored = rows.filter((r) => r.effective_score !== null);
                        const got = scored.reduce((s, r) => s + (r.effective_score ?? 0), 0);
                        return (
                          <Text>
                            {scored.length === 0 ? '—' : fmtScore(got)}
                            <Caption1 style={{ color: t.colorNeutralForeground3 }}> / {total}</Caption1>
                          </Text>
                        );
                      })()}
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
