import { useTheme } from '../../appTheme';
import { Link } from 'react-router-dom';
import { Badge, Caption1, createTableColumn, DataGrid, DataGridCell, DataGridRow, DataGridHeaderCell, DataGridBody, DataGridHeader, MessageBar, MessageBarBody, MessageBarTitle, Text, tokens, type TableColumnDefinition } from '@fluentui/react-components';
import { listStudentAssignments } from '../../api';
import type { StudentAssignmentItem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';
import { PageHeader } from '../../components/PageHeader';

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

  const ending = (data ?? []).filter((a) => a.state === 'ending');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader title="我的场次" />
      {ending.length > 0 && (
        <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>
            <MessageBarTitle>以下场次即将结束，请尽快提交</MessageBarTitle>
            {ending.map((a) => (
              <div key={a.id}>
                <Link to={`/student/assignments/${a.id}`} style={{ color: t.colorBrandForeground1, fontWeight: tokens.fontWeightSemibold }}>
                  {a.title}
                </Link>
                <Caption1 style={{ color: t.colorNeutralForeground3, marginLeft: tokens.spacingHorizontalS }}>剩余时间至 {fmtTime(a.end_time)}</Caption1>
              </div>
            ))}
          </MessageBarBody>
        </MessageBar>
      )}
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
                      <Badge appearance="outline" size="large">
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
                        className="ql-badge-status"
                        size="large"
                        style={
                          item.state === 'ended'
                            ? { color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }
                            : item.state === 'ending'
                              ? { color: t.colorPaletteRedForeground1, backgroundColor: t.colorPaletteRedBackground2 }
                              : { color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }
                        }
                      >
                        {item.state === 'ended' ? '已结束' : item.state === 'ending' ? '即将结束' : '进行中'}
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
