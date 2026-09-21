import { useTheme } from '../../appTheme';
import { useMemo, useState } from 'react';
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
  Tooltip,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { ArrowDownload24Regular } from '@fluentui/react-icons';
import { exportAssignmentStudents, getAssignmentStudents } from '../../api';
import type { AssignmentProblemScore, AssignmentStudentRow } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';
import { PageHeader } from '../../components/PageHeader';

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
 */
function problemCell(item: AssignmentStudentRow, columnId: string): string {
  const problemId = Number(columnId.slice(PROBLEM_COL_PREFIX.length));
  const score = item.problem_scores?.find((p) => p.problem_id === problemId)?.effective_score;
  return score === null || score === undefined ? '' : fmtScore(score);
}

/** 题名列头：整题目标题过长时省略号收尾，完整标题交给 Fluent Tooltip（取主题令牌，暗色自适应）。 */
function ProblemHeaderCell({ problem }: { problem: AssignmentProblemScore }) {
  return (
    <Tooltip content={problem.title} relationship="description">
      <span
        style={{
          display: 'block',
          maxWidth: 160,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {problem.title}
      </span>
    </Tooltip>
  );
}

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
      createTableColumn({ columnId: 'drill', renderHeaderCell: () => '下钻' }),
    );
    return cols;
  }, [problemColumns]);

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
          subtitle="分数口径：「最高单题分」是得分最高的那道题，「总分」是题单内各题有效分之和；多题场次逐题成列，列顺序与导出 Excel 一致。"
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
                    {columnId === 'total' && fmtScore(item.total_score)}
                    {typeof columnId === 'string' &&
                      columnId.startsWith(PROBLEM_COL_PREFIX) &&
                      problemCell(item, columnId)}
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
