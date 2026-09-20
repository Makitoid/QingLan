import { useTheme } from '../../appTheme';
import { useState } from 'react';
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
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  Spinner,
  Text,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { ArrowDownload24Regular } from '@fluentui/react-icons';
import { exportAssignmentStudents, getAssignmentStudents } from '../../api';
import type { AssignmentStudentRow } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';
import { PageHeader } from '../../components/PageHeader';

const columns: TableColumnDefinition<AssignmentStudentRow>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '学号' }),
  createTableColumn({ columnId: 'name', renderHeaderCell: () => '姓名' }),
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
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleExport = async () => {
    if (exporting) return; // 防重复点击
    setExporting(true);
    setExportError(null);
    try {
      await exportAssignmentStudents(assignmentId);
    } catch (err) {
      setExportError(`导出失败：${errMessage(err)}`);
    } finally {
      setExporting(false);
    }
  };

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
        <PageHeader
          title="逐学生成绩"
          actions={
            <Button
              appearance="secondary"
              icon={exporting ? <Spinner size="tiny" /> : <ArrowDownload24Regular />}
              disabled={exporting}
              onClick={handleExport}
            >
              {exporting ? '导出中…' : '导出 Excel'}
            </Button>
          }
        />
      </div>

      {exportError && (
        <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{exportError}</MessageBarBody>
          <MessageBarActions>
            <Button size="small" disabled={exporting} onClick={handleExport}>
              重试
            </Button>
          </MessageBarActions>
        </MessageBar>
      )}

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
                    {columnId === 'username' &&
                      (item.username ? (
                        item.username
                      ) : (
                        <Caption1 style={{ color: t.colorNeutralForeground4 }}>—</Caption1>
                      ))}
                    {columnId === 'name' && (
                      <Text weight={item.submitted_count === 0 ? 'regular' : 'semibold'}>
                        {item.name}
                        {item.submitted_count === 0 && (
                          <Badge size="large" style={{ marginLeft: tokens.spacingHorizontalS, color: t.colorPaletteRedForeground1, backgroundColor: t.colorPaletteRedBackground2 }}>
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
