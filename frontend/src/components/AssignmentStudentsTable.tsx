import { useTheme } from '../appTheme';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
  type TableRowId,
} from '@fluentui/react-components';
import { Alert24Regular, ArrowDownload24Regular, Dismiss24Regular } from '@fluentui/react-icons';
import { exportAssignmentStudents, getAssignmentStudents, remindAssignmentStudents } from '../api';
import type { AssignmentProblemScore, AssignmentStudentRow } from '../api/types';
import { useAsync } from './useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from './StateViews';
import { BulkActionBar } from './BulkActionBar';
import { fmtTime } from './time';
import { fmtScore } from './score';

/** 每题得分列的 id 前缀，列 id 里带 problem_id 以便单元格回查该题的分。 */
const PROBLEM_COL_PREFIX = 'problem:';
const problemColumnId = (problemId: number) => `${PROBLEM_COL_PREFIX}${problemId}`;

/**
 * 每题列的题单：后端保证每行的 problem_scores 同序（即题单 seq），取第一行推导即可；
 * 没有数据（空表 / 首行无题单）时退回固定列。
 *
 * 只有一道题时不出题名列——那一列与「总分」恒等，并排两列反而让教师误读成两个口径。
 */
function problemColumnsFor(rows: AssignmentStudentRow[] | null | undefined): AssignmentProblemScore[] {
  const first = rows?.[0]?.problem_scores ?? [];
  return first.length > 1 ? [...first].sort((a, b) => a.seq - b.seq) : [];
}

/**
 * 某题得分单元格。未提交该题（effective_score 为 null）显示**空**，
 * 与导出的 xlsx 一致（那里写空串，见 services/export.py），不写 0 也不写「—」。
 * 0.4.0 F5 起为纯文本——调分入口统一收进「查看详情」列，直达判分页。
 */
function problemCell(item: AssignmentStudentRow, columnId: string): string {
  const problemId = Number(columnId.slice(PROBLEM_COL_PREFIX.length));
  const score = item.problem_scores?.find((p) => p.problem_id === problemId)?.effective_score;
  return score === null || score === undefined ? '' : fmtScore(score);
}

/** 每题列的列头：只显示考试时的题号（第 N 题），不显示题目标题。 */
function ProblemHeaderCell({ problem }: { problem: AssignmentProblemScore }) {
  return <span>第 {problem.seq} 题</span>;
}

/**
 * 0.4.0 F4：导出 Excel 的状态（表格嵌进总览卡片时，按钮要落在卡片头部，故与表格拆开）。
 */
export function useAssignmentStudentsExport(assignmentId: number) {
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

  const exportButton = (
    <Button
      appearance="secondary"
      icon={exporting ? <Spinner size="tiny" /> : <ArrowDownload24Regular />}
      disabled={exporting}
      onClick={handleExport}
    >
      {exporting ? '导出中…' : '导出 Excel'}
    </Button>
  );

  return { exporting, exportError, handleExport, exportButton };
}

/**
 * 0.4.0 F4：逐学生成绩表（原 /teacher/assignments/:id/students 页面主体），
 * 现内嵌进场次总览的「学生答题情况」块。自己取数、自己出动态每题列。
 */
export function AssignmentStudentsTable({ assignmentId }: { assignmentId: number }) {
  const t = useTheme();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync<AssignmentStudentRow[]>(
    () => getAssignmentStudents(assignmentId),
    [assignmentId],
  );

  // F6：勾选 = 批量提醒的收件人；换场次（组件重挂载）自然清空。
  const [selectedIds, setSelectedIds] = useState<Set<TableRowId>>(new Set());
  const [reminding, setReminding] = useState(false);
  const [notice, setNotice] = useState<{ intent: 'success' | 'warning' | 'error'; text: string } | null>(null);

  // 列顺序与导出的 xlsx 对齐：学号 | 姓名 | 提交次数 | 最高单题分 | 总分 | 每题得分 | 最后提交时间。
  // 「总分」紧跟「最高单题分」，教师对照导出时两列相邻；每题列插在它之后、时间列之前。
  const problemColumns = useMemo(() => problemColumnsFor(data), [data]);
  const columns = useMemo<TableColumnDefinition<AssignmentStudentRow>[]>(() => {
    const cols: TableColumnDefinition<AssignmentStudentRow>[] = [
      createTableColumn({ columnId: 'username', renderHeaderCell: () => '学号' }),
      createTableColumn({ columnId: 'name', renderHeaderCell: () => '姓名' }),
      createTableColumn({ columnId: 'submitted_count', renderHeaderCell: () => '提交次数' }),
      createTableColumn({ columnId: 'best', renderHeaderCell: () => '最高单题分' }),
      createTableColumn({ columnId: 'total', renderHeaderCell: () => '总分' }),
    ];
    for (const problem of problemColumns) {
      cols.push(
        createTableColumn({
          columnId: problemColumnId(problem.problem_id),
          renderHeaderCell: () => <ProblemHeaderCell problem={problem} />,
        }),
      );
    }
    cols.push(
      createTableColumn({ columnId: 'last_submitted_at', renderHeaderCell: () => '最后提交时间' }),
      createTableColumn({ columnId: 'drill', renderHeaderCell: () => '查看详情' }),
      createTableColumn({ columnId: 'remind', renderHeaderCell: () => '提醒' }),
    );
    return cols;
  }, [problemColumns]);

  const remind = async (ids: number[], label: string) => {
    if (ids.length === 0 || reminding) return;
    if (!window.confirm(`确定提醒 ${label} 交作业？学生下次登录时会看到弹窗。`)) return;
    setReminding(true);
    setNotice(null);
    try {
      const result = await remindAssignmentStudents(assignmentId, ids);
      setNotice({
        intent: result.created > 0 ? 'success' : 'warning',
        text: result.created > 0
          ? `已提醒 ${result.created} 名学生${result.skipped ? `，另有 ${result.skipped} 名的提醒仍未读、不重复发送` : ''}。`
          : '这些学生都还有一条未读的提醒，本次没有重复发送。',
      });
      setSelectedIds(new Set());
    } catch (err) {
      setNotice({ intent: 'error', text: `提醒失败：${errMessage(err)}` });
    } finally {
      setReminding(false);
    }
  };

  const selectedStudentIds = (data ?? []).filter((r) => selectedIds.has(r.student_id)).map((r) => r.student_id);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  if (!data || data.length === 0) {
    return <EmptyView title="暂无学生" description="该场次受众为空，请检查教师↔学生绑定关系。" />;
  }

  return (
    <>
      <BulkActionBar
        selectedCount={selectedStudentIds.length}
        actions={[
          {
            key: 'remind',
            label: '提醒交作业',
            icon: <Alert24Regular />,
            appearance: 'primary',
            disabled: reminding,
            onClick: () => void remind(selectedStudentIds, '选中的学生'),
          },
          {
            key: 'cancel',
            label: '取消选择',
            icon: <Dismiss24Regular />,
            disabled: reminding,
            onClick: () => setSelectedIds(new Set()),
          },
        ]}
      />

      {notice && (
        <MessageBar intent={notice.intent} style={{ margin: `${tokens.spacingVerticalS} 0`, borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{notice.text}</MessageBarBody>
          <MessageBarActions>
            <Button size="small" appearance="subtle" icon={<Dismiss24Regular />} onClick={() => setNotice(null)}>
              关闭
            </Button>
          </MessageBarActions>
        </MessageBar>
      )}

      <DataGrid
        items={data}
        columns={columns}
        focusMode="cell"
        resizableColumns
        selectionMode="multiselect"
        getRowId={(item) => item.student_id}
        selectedItems={selectedIds}
        onSelectionChange={(_, d) => setSelectedIds(new Set(d.selectedItems))}
      >
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
                    <Text>
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
                  {columnId === 'total' && fmtScore(item.total_score)}
                  {typeof columnId === 'string' && columnId.startsWith(PROBLEM_COL_PREFIX) &&
                    problemCell(item, columnId)}
                  {columnId === 'last_submitted_at' && fmtTime(item.last_submitted_at)}
                  {columnId === 'drill' && (
                    item.last_submission_id === null || item.last_submission_id === undefined ? (
                      <Caption1 style={{ color: t.colorNeutralForeground4 }}>—</Caption1>
                    ) : (
                      <Button
                        appearance="subtle"
                        size="small"
                        onClick={() => navigate(`/teacher/submissions/${item.last_submission_id}`)}
                      >
                        查看详情
                      </Button>
                    )
                  )}
                  {columnId === 'remind' && (
                    <Button
                      appearance="subtle"
                      size="small"
                      icon={<Alert24Regular />}
                      disabled={reminding}
                      onClick={() => void remind([item.student_id], item.name || item.username || '该生')}
                    >
                      提醒
                    </Button>
                  )}
                </DataGridCell>
              )}
            </DataGridRow>
          )}
        </DataGridBody>
      </DataGrid>
    </>
  );
}
