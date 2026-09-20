import { useTheme } from '../../appTheme';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
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
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  Text,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { ArrowTrending24Regular, People24Regular, Send24Regular } from '@fluentui/react-icons';
import { getAssignmentOverview, getTeacherAssignment, releaseAssignment } from '../../api';
import type { AssignmentDetail, AssignmentOverview, OverviewPerProblem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';
import { ScoreHistogram } from '../../components/ScoreHistogram';
import { PageHeader } from '../../components/PageHeader';

const columns: TableColumnDefinition<OverviewPerProblem>[] = [
  createTableColumn({ columnId: 'title', renderHeaderCell: () => '题目' }),
  createTableColumn({ columnId: 'submit_count', renderHeaderCell: () => '提交数' }),
  createTableColumn({ columnId: 'pass_rate', renderHeaderCell: () => '通过率（AC）' }),
  createTableColumn({ columnId: 'avg', renderHeaderCell: () => '平均有效分' }),
];

function StatCard({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  const t = useTheme();
  return (
    <Card size="medium" style={{ flex: 1 }}>
      <CardHeader
        image={<span style={{ color: t.colorBrandForeground1, display: 'flex' }}>{icon}</span>}
        header={<Caption1 style={{ color: t.colorNeutralForeground3 }}>{label}</Caption1>}
        description={<Text size={700} weight="bold">{value}</Text>}
      />
    </Card>
  );
}

export function TeacherAssignmentOverview() {
  const { id } = useParams();
  const t = useTheme();
  const navigate = useNavigate();
  const assignmentId = Number(id);
  const detail = useAsync<AssignmentDetail>(() => getTeacherAssignment(assignmentId), [assignmentId]);
  const overview = useAsync<AssignmentOverview>(() => getAssignmentOverview(assignmentId), [assignmentId]);

  const handleRelease = async () => {
    if (!window.confirm('确定放出考试结果？放出后学生即可见判定与分数。')) return;
    try {
      await releaseAssignment(assignmentId);
      detail.reload();
      overview.reload();
    } catch (err) {
      window.alert(errMessage(err));
    }
  };

  if (detail.loading || overview.loading) return <LoadingView />;
  if (detail.error) return <ErrorView error={detail.error} onRetry={detail.reload} />;
  if (overview.error) return <ErrorView error={overview.error} onRetry={overview.reload} />;
  if (!detail.data || !overview.data) return null;

  const a = detail.data;
  const o = overview.data;
  const canRelease = a.mode === 'test' && !a.released;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate('/teacher/assignments')}>← 返回场次列表</Button>
        </Caption1>
        <PageHeader
          title={a.title}
          subtitle={
            <>
              时间窗：{fmtTime(a.start_time)} ~ {fmtTime(a.end_time)} · 计分：{a.score_policy === 'best' ? '取最高' : '取最后'}
              {a.max_submissions !== null ? ` · 限 ${a.max_submissions} 次提交` : ' · 不限提交次数'}
            </>
          }
          actions={
            <>
              <Badge appearance="outline" size="large">{a.mode === 'homework' ? '作业' : '考试'}</Badge>
              {a.mode === 'test' && (
                a.released
                  ? <Badge className="ql-badge-status" size="large" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }}>已放出</Badge>
                  : <Badge className="ql-badge-status" size="large" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }}>未放出</Badge>
              )}
            </>
          }
        />
      </div>

      {canRelease && (
        <MessageBar intent="info" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>考试模式：当前学生不可见判定详情。结束后（已过 end_time）可放出成绩。</MessageBarBody>
          <MessageBarActions>
            <Button size="small" appearance="primary" icon={<Send24Regular />} onClick={handleRelease}>放出成绩</Button>
          </MessageBarActions>
        </MessageBar>
      )}

      <div style={{ display: 'flex', gap: tokens.spacingHorizontalM }}>
        <StatCard label="应交学生数" value={o.total_students} icon={<People24Regular />} />
        <StatCard label="已提交学生数" value={o.submitted_students} icon={<ArrowTrending24Regular />} />
        <StatCard
          label="提交率"
          value={o.total_students > 0 ? `${Math.round((o.submitted_students / o.total_students) * 100)}%` : '—'}
          icon={<ArrowTrending24Regular />}
        />
      </div>

      <Card size="medium">
        <CardHeader
          header={<Text weight="semibold">每题统计</Text>}
          action={
            <Button size="small" appearance="secondary" onClick={() => navigate(`/teacher/assignments/${assignmentId}/students`)}>
              逐学生成绩 →
            </Button>
          }
        />
        {o.per_problem.length === 0 ? (
          <EmptyView title="暂无题目数据" />
        ) : (
          <DataGrid items={o.per_problem} columns={columns} focusMode="cell">
            <DataGridHeader>
              <DataGridRow>
                {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
              </DataGridRow>
            </DataGridHeader>
            <DataGridBody<OverviewPerProblem>>
              {({ item, rowId }) => (
                <DataGridRow<OverviewPerProblem> key={rowId}>
                  {({ columnId }) => (
                    <DataGridCell>
                      {columnId === 'title' && (
                        <Link to={`/teacher/problems/${item.problem_id}`} style={{ color: t.colorBrandForeground1 }}>
                          {item.title}
                        </Link>
                      )}
                      {columnId === 'submit_count' && item.submit_count}
                      {columnId === 'pass_rate' && `${Math.round(item.pass_rate * 100)}%`}
                      {columnId === 'avg' && fmtScore(item.avg_effective_score)}
                    </DataGridCell>
                  )}
                </DataGridRow>
              )}
            </DataGridBody>
          </DataGrid>
        )}
      </Card>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">分数分布</Text>} />
        {o.histogram.length === 0 ? (
          <EmptyView title="暂无分数数据" description="还没有已判分的提交。" />
        ) : (
          <ScoreHistogram data={o.histogram} />
        )}
      </Card>
    </div>
  );
}
