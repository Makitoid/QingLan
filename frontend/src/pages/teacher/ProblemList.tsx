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
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Option,
  SearchBox,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Add24Regular, Delete24Regular } from '@fluentui/react-icons';
import { createTeacherProblem, deleteTeacherProblem, listTeacherProblems } from '../../api';
import type { ProblemSummary } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errCode, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { PageHeader } from '../../components/PageHeader';

const COMPARE_LABELS: Record<string, string> = { exact: '精确', trim: '忽略空白', float: '浮点容差' };

/** 分组筛选的特殊选项值；正常分组名不会以 `__` 开头，两者不会冲突。 */
const GROUP_ALL = '__all__';
const GROUP_NONE = '__none__';

/** 题库分组是自由文本（可空），比较与展示前统一去掉首尾空白。 */
function groupOf(problem: ProblemSummary): string {
  return (problem.group_name ?? '').trim();
}

const columns: TableColumnDefinition<ProblemSummary>[] = [
  createTableColumn({ columnId: 'id', renderHeaderCell: () => 'ID' }),
  createTableColumn({ columnId: 'title', renderHeaderCell: () => '标题' }),
  createTableColumn({ columnId: 'group', renderHeaderCell: () => '分组' }),
  createTableColumn({ columnId: 'limits', renderHeaderCell: () => '限制' }),
  createTableColumn({ columnId: 'compare_mode', renderHeaderCell: () => '比对模式' }),
  createTableColumn({ columnId: 'created_at', renderHeaderCell: () => '创建时间' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '操作' }),
];

export function TeacherProblemList() {
  const t = useTheme();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(listTeacherProblems, []);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // 需求⑥：搜索 + 分组筛选都是前端过滤，列表接口不变
  const [search, setSearch] = useState('');
  const [groupFilter, setGroupFilter] = useState(GROUP_ALL);
  const [deleteTarget, setDeleteTarget] = useState<ProblemSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const problems = useMemo(() => data ?? [], [data]);

  /** 下拉选项：全部分组 + 本页数据里出现过的分组（排序）+ 未分组。 */
  const groupOptions = useMemo(() => {
    const names = Array
      .from(new Set(problems.map(groupOf).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
    return [
      { value: GROUP_ALL, label: '全部分组' },
      ...names.map((name) => ({ value: name, label: name })),
      { value: GROUP_NONE, label: '未分组' },
    ];
  }, [problems]);

  const keyword = search.trim().toLowerCase();
  const filtering = keyword !== '' || groupFilter !== GROUP_ALL;

  const filtered = useMemo(
    () => problems.filter((problem) => {
      if (keyword) {
        const hit = problem.title.toLowerCase().includes(keyword) || groupOf(problem).toLowerCase().includes(keyword);
        if (!hit) return false;
      }
      const group = groupOf(problem);
      if (groupFilter === GROUP_NONE) return group === '';
      if (groupFilter !== GROUP_ALL) return group === groupFilter;
      return true;
    }),
    [problems, keyword, groupFilter],
  );

  const resetFilters = () => {
    setSearch('');
    setGroupFilter(GROUP_ALL);
  };

  const handleCreate = async () => {
    if (!title.trim()) {
      setCreateError('请输入题目标题');
      return;
    }
    setBusy(true);
    setCreateError(null);
    try {
      const created = await createTeacherProblem({
        title: title.trim(),
        description: '',
        input_format: '',
        output_format: '',
        time_limit_ms: 1000,
        memory_limit_mb: 256,
        compare_mode: 'trim',
        float_eps: null,
      });
      navigate(`/teacher/problems/${created.id}`);
    } catch (err) {
      setCreateError(errMessage(err));
      setBusy(false);
    }
  };

  /** 删除题目：后端在被场次引用时返回 409 PROBLEM_IN_USE，给出可操作的中文提示。 */
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteTeacherProblem(deleteTarget.id);
      setDeleteTarget(null);
      setDeleting(false);
      reload();
    } catch (err) {
      setDeleting(false);
      setDeleteError(
        errCode(err) === 'PROBLEM_IN_USE'
          ? '该题目已被场次引用，无法删除。请先在相关场次中移除这道题目。'
          : errMessage(err),
      );
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="题库"
        subtitle="搜索与分组筛选均为前端过滤；分组是自由文本，在题目编辑页填写。"
        actions={
          <>
            <SearchBox
              placeholder="搜索标题或分组"
              value={search}
              onChange={(_, d) => setSearch(d.value)}
              style={{ width: '220px' }}
            />
            <Dropdown
              selectedOptions={[groupFilter]}
              value={groupOptions.find((o) => o.value === groupFilter)?.label}
              onOptionSelect={(_, d) => setGroupFilter(d.optionValue || GROUP_ALL)}
              style={{ width: '170px' }}
            >
              {groupOptions.map((o) => (
                <Option key={o.value} value={o.value}>{o.label}</Option>
              ))}
            </Dropdown>
            <Button appearance="primary" icon={<Add24Regular />} onClick={() => setOpen(true)}>新建题目</Button>
          </>
        }
      />

      {problems.length === 0 ? (
        <EmptyView title="题库为空" description="点击右上角「新建题目」创建第一道题。" />
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>
              {filtering ? `共 ${problems.length} 道题，匹配 ${filtered.length} 道` : `共 ${problems.length} 道题`}
            </Caption1>
            {filtering && (
              <Button appearance="subtle" size="small" onClick={resetFilters}>清除筛选</Button>
            )}
          </div>

          {filtered.length === 0 ? (
            <EmptyView
              title="没有匹配的题目"
              description="换个关键词，或清除筛选条件后重试。"
              action={<Button appearance="secondary" size="small" onClick={resetFilters}>清除筛选</Button>}
            />
          ) : (
            <DataGrid items={filtered} columns={columns} focusMode="cell" resizableColumns>
              <DataGridHeader>
                <DataGridRow>
                  {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
                </DataGridRow>
              </DataGridHeader>
              <DataGridBody<ProblemSummary>>
                {({ item, rowId }) => (
                  <DataGridRow<ProblemSummary> key={rowId}>
                    {({ columnId }) => (
                      <DataGridCell>
                        {columnId === 'id' && item.id}
                        {columnId === 'title' && (
                          <Link to={`/teacher/problems/${item.id}`} style={{ color: t.colorBrandForeground1, fontWeight: tokens.fontWeightSemibold }}>
                            {item.title}
                          </Link>
                        )}
                        {columnId === 'group' && (
                          groupOf(item)
                            ? <Badge appearance="tint" size="small">{groupOf(item)}</Badge>
                            : <Caption1 style={{ color: t.colorNeutralForeground3 }}>—</Caption1>
                        )}
                        {columnId === 'limits' && (
                          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                            {item.time_limit_ms} ms / {item.memory_limit_mb} MB
                          </Caption1>
                        )}
                        {columnId === 'compare_mode' && <Badge appearance="outline" size="small">{COMPARE_LABELS[item.compare_mode]}</Badge>}
                        {columnId === 'created_at' && fmtTime(item.created_at)}
                        {columnId === 'actions' && (
                          <Button
                            appearance="subtle"
                            size="small"
                            icon={<Delete24Regular />}
                            title="删除题目"
                            style={{ color: t.colorPaletteRedForeground1 }}
                            onClick={() => {
                              setDeleteError(null);
                              setDeleteTarget(item);
                            }}
                          />
                        )}
                      </DataGridCell>
                    )}
                  </DataGridRow>
                )}
              </DataGridBody>
            </DataGrid>
          )}
        </>
      )}

      <Dialog open={open} onOpenChange={(_, d) => setOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>新建题目</DialogTitle>
            <DialogContent>
              <Field label="标题" required>
                <Input value={title} onChange={(_, d) => setTitle(d.value)} placeholder="如：A+B 问题" autoFocus />
              </Field>
              {createError && (
                <Caption1 style={{ color: t.colorPaletteRedForeground1 }}>{createError}</Caption1>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setOpen(false)} disabled={busy}>取消</Button>
              <Button appearance="primary" onClick={handleCreate} disabled={busy}>{busy ? '创建中…' : '创建并编辑'}</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={deleteTarget !== null} onOpenChange={(_, d) => { if (!d.open && !deleting) setDeleteTarget(null); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>删除题目</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>
                  确定删除题目「{deleteTarget?.title}」（#{deleteTarget?.id}）？题面与全部测试用例一并删除，且不可恢复。
                </Caption1>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  已被场次引用的题目无法删除。
                </Caption1>
                {deleteError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{deleteError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>取消</Button>
              <Button
                appearance="primary"
                icon={<Delete24Regular />}
                onClick={handleDelete}
                disabled={deleting}
                style={{ color: tokens.colorNeutralForegroundInverted }}
              >
                {deleting ? '删除中…' : '确认删除'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
