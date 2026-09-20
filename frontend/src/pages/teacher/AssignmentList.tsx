import { useTheme } from '../../appTheme';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
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
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Tab,
  TabList,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Add24Regular, MoreHorizontal24Regular } from '@fluentui/react-icons';
import { listTeacherAssignments, releaseAssignment } from '../../api';
import type { AssignmentMode, AssignmentSummary } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { PageHeader } from '../../components/PageHeader';

/**
 * 教师侧模式文案：`test` 对学生叫「测试」，教师侧统一叫「考试」。
 * 学生端页面（pages/student/*）与 AssignmentNew/Overview 各有自己的字面量，
 * 不共用本常量，因此学生端「测试」文案保持原样。
 */
const MODE_LABEL: Record<AssignmentMode, string> = { homework: '作业', test: '考试' };

/** 页内二级筛选（前端过滤，不额外请求接口）。 */
type ModeFilter = 'all' | AssignmentMode;

const MODE_TABS: { value: ModeFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'homework', label: MODE_LABEL.homework },
  { value: 'test', label: MODE_LABEL.test },
];

const columns: TableColumnDefinition<AssignmentSummary>[] = [
  createTableColumn({ columnId: 'title', renderHeaderCell: () => '标题' }),
  createTableColumn({ columnId: 'mode', renderHeaderCell: () => '模式' }),
  createTableColumn({ columnId: 'window', renderHeaderCell: () => '时间窗' }),
  createTableColumn({ columnId: 'policy', renderHeaderCell: () => '计分' }),
  createTableColumn({ columnId: 'released', renderHeaderCell: () => '放分' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '' }),
];

export function TeacherAssignmentList() {
  const t = useTheme();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(listTeacherAssignments, []);
  const [modeFilter, setModeFilter] = useState<ModeFilter>('all');

  // 前端过滤：接口无 mode 参数，一次全量拉取后按 Tab 切换。
  const items = useMemo(
    () => (data ?? []).filter((item) => modeFilter === 'all' || item.mode === modeFilter),
    [data, modeFilter],
  );
  const filterLabel = MODE_TABS.find((tab) => tab.value === modeFilter)?.label ?? '全部';

  const handleRelease = async (item: AssignmentSummary) => {
    if (!window.confirm(`确定放出「${item.title}」的考试结果？放出后学生即可见判定与分数。`)) return;
    try {
      await releaseAssignment(item.id);
      reload();
    } catch (err) {
      window.alert(errMessage(err));
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  const hasAny = Boolean(data && data.length > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="发布"
        actions={
          <Button appearance="primary" icon={<Add24Regular />} onClick={() => navigate('/teacher/assignments/new')}>
            发布作业 / 考试
          </Button>
        }
      />

      <TabList
        size="small"
        selectedValue={modeFilter}
        onTabSelect={(_, d) => setModeFilter(d.value as ModeFilter)}
        // 抵消小号 Tab 自带的 MNudge 水平内边距，让首个 Tab 文字与 PageHeader 大标题左对齐。
        style={{ marginLeft: `calc(-1 * ${tokens.spacingHorizontalMNudge})` }}
      >
        {MODE_TABS.map((tab) => (
          <Tab key={tab.value} value={tab.value}>
            {tab.label}
          </Tab>
        ))}
      </TabList>

      {items.length === 0 ? (
        <EmptyView
          title={hasAny ? `当前没有「${filterLabel}」场次` : '还没有场次'}
          description={hasAny ? '换一个筛选条件看看，或发布新的作业 / 考试。' : '点击右上角发布第一个作业或考试。'}
        />
      ) : (
        <DataGrid items={items} columns={columns} focusMode="cell" resizableColumns>
          <DataGridHeader>
            <DataGridRow>
              {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
            </DataGridRow>
          </DataGridHeader>
          <DataGridBody<AssignmentSummary>>
            {({ item, rowId }) => (
              <DataGridRow<AssignmentSummary> key={rowId}>
                {({ columnId }) => (
                  <DataGridCell>
                    {columnId === 'title' && (
                      <Link to={`/teacher/assignments/${item.id}`} style={{ color: t.colorBrandForeground1, fontWeight: tokens.fontWeightSemibold }}>
                        {item.title}
                      </Link>
                    )}
                    {columnId === 'mode' && <Badge appearance="outline" size="small">{MODE_LABEL[item.mode]}</Badge>}
                    {columnId === 'window' && (
                      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                        {fmtTime(item.start_time)} ~ {fmtTime(item.end_time)}
                      </Caption1>
                    )}
                    {columnId === 'policy' && (
                      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                        {item.score_policy === 'best' ? '取最高' : '取最后'}
                        {item.max_submissions !== null ? ` · 限 ${item.max_submissions} 次` : ' · 不限次数'}
                      </Caption1>
                    )}
                    {columnId === 'released' && (
                      item.mode === 'test' ? (
                        item.released
                          ? <Badge size="small" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }}>已放出</Badge>
                          : <Badge size="small" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }}>未放出</Badge>
                      ) : (
                        <Caption1 style={{ color: t.colorNeutralForeground4 }}>—</Caption1>
                      )
                    )}
                    {columnId === 'actions' && (
                      <Menu>
                        <MenuTrigger>
                          <Button appearance="subtle" size="small" icon={<MoreHorizontal24Regular />} />
                        </MenuTrigger>
                        <MenuPopover>
                          <MenuList>
                            <MenuItem onClick={() => navigate(`/teacher/assignments/${item.id}`)}>总览与统计</MenuItem>
                            <MenuItem onClick={() => navigate(`/teacher/assignments/${item.id}/students`)}>逐学生成绩</MenuItem>
                            {item.mode === 'test' && !item.released && (
                              <MenuItem onClick={() => void handleRelease(item)}>放出考试结果</MenuItem>
                            )}
                          </MenuList>
                        </MenuPopover>
                      </Menu>
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
