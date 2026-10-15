import { useTheme } from '../../appTheme';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  Combobox,
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
  type TableRowId,
} from '@fluentui/react-components';
import { Add24Regular, Delete24Regular, Dismiss24Regular, Group24Regular } from '@fluentui/react-icons';
import {
  batchDeleteTeacherProblems,
  batchGroupTeacherProblems,
  createTeacherProblem,
  deleteTeacherProblem,
  listTeacherProblems,
} from '../../api';
import type { ProblemSummary } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errCode, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { PageHeader } from '../../components/PageHeader';
import { BulkActionBar } from '../../components/BulkActionBar';
import { useDangerStyles } from '../../components/dangerStyles';

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
  const danger = useDangerStyles();
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

  // 0.4.0 F1：多选 + 批量分组 / 批量删除
  const [selectedIds, setSelectedIds] = useState<Set<TableRowId>>(new Set());
  const [groupOpen, setGroupOpen] = useState(false);
  const [groupText, setGroupText] = useState('');
  const [groupBusy, setGroupBusy] = useState(false);
  const [groupError, setGroupError] = useState<string | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [bulkDeleteError, setBulkDeleteError] = useState<string | null>(null);

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

  /** 批量动作只作用于当前表格里仍可见的选中项（筛选变化后不误伤）。 */
  const selectedProblemIds = useMemo(
    () => filtered.filter((problem) => selectedIds.has(problem.id)).map((problem) => problem.id),
    [filtered, selectedIds],
  );

  /** 分组 Dialog 的候选：groupOptions 里剔除「全部分组 / 未分组」两个哨兵，只留真实组名。 */
  const groupCandidates = useMemo(
    () => groupOptions
      .map((o) => o.value)
      .filter((value) => value !== GROUP_ALL && value !== GROUP_NONE),
    [groupOptions],
  );

  const closeGroupDialog = () => {
    setGroupOpen(false);
    setGroupText('');
    setGroupError(null);
  };

  const handleBatchGroup = async () => {
    const name = groupText.trim();
    if (!name) {
      setGroupError('请输入分组名');
      return;
    }
    setGroupBusy(true);
    setGroupError(null);
    try {
      await batchGroupTeacherProblems(selectedProblemIds, name);
      closeGroupDialog();
      setSelectedIds(new Set());
      setGroupBusy(false);
      reload();
    } catch (err) {
      setGroupBusy(false);
      setGroupError(errMessage(err));
    }
  };

  const closeBulkDeleteDialog = () => {
    setBulkDeleteOpen(false);
    setBulkDeleteError(null);
  };

  /** 批量删除：被场次引用时整批 409，直接展示后端 message（列出了冲突题名）。 */
  const handleBatchDelete = async () => {
    setBulkDeleting(true);
    setBulkDeleteError(null);
    try {
      await batchDeleteTeacherProblems(selectedProblemIds);
      closeBulkDeleteDialog();
      setSelectedIds(new Set());
      setBulkDeleting(false);
      reload();
    } catch (err) {
      setBulkDeleting(false);
      setBulkDeleteError(
        errCode(err) === 'PROBLEM_IN_USE' ? errMessage(err) : `批量删除失败：${errMessage(err)}`,
      );
    }
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
        actions={
          <>
            <SearchBox
              placeholder="搜索标题或分组"
              value={search}
              onChange={(_, d) => setSearch(d.value)}
              style={{ width: '160px' }}
            />
            <Dropdown
              selectedOptions={[groupFilter]}
              value={groupOptions.find((o) => o.value === groupFilter)?.label}
              onOptionSelect={(_, d) => setGroupFilter(d.optionValue || GROUP_ALL)}
              style={{ width: '110px', minWidth: '110px' }}
            >
              {groupOptions.map((o) => (
                <Option key={o.value} value={o.value}>{o.label}</Option>
              ))}
            </Dropdown>
            <Button appearance="primary" icon={<Add24Regular />} onClick={() => setOpen(true)}>新建题目</Button>
          </>
        }
      />

      <BulkActionBar
        selectedCount={selectedIds.size}
        label={`已选 ${selectedIds.size} 道题`}
        actions={[
          {
            key: 'group',
            label: '加入分组',
            icon: <Group24Regular />,
            disabled: groupBusy || bulkDeleting,
            onClick: () => {
              setGroupError(null);
              setGroupOpen(true);
            },
          },
          {
            key: 'delete',
            label: '删除',
            icon: <Delete24Regular />,
            danger: true,
            disabled: groupBusy || bulkDeleting,
            onClick: () => {
              setBulkDeleteError(null);
              setBulkDeleteOpen(true);
            },
          },
          {
            key: 'cancel',
            label: '取消选择',
            icon: <Dismiss24Regular />,
            disabled: groupBusy || bulkDeleting,
            onClick: () => setSelectedIds(new Set()),
          },
        ]}
      />

      {problems.length === 0 ? (
        <EmptyView title="题库为空" />
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
              action={<Button appearance="secondary" size="small" onClick={resetFilters}>清除筛选</Button>}
            />
          ) : (
            <DataGrid
              items={filtered}
              columns={columns}
              focusMode="cell"
              resizableColumns
              selectionMode="multiselect"
              getRowId={(item) => item.id}
              selectedItems={selectedIds}
              onSelectionChange={(_, d) => setSelectedIds(new Set(d.selectedItems))}
            >
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
                            ? <Badge appearance="tint" size="large">{groupOf(item)}</Badge>
                            : <Caption1 style={{ color: t.colorNeutralForeground3 }}>—</Caption1>
                        )}
                        {columnId === 'limits' && (
                          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                            {item.time_limit_ms} ms / {item.memory_limit_mb} MB
                          </Caption1>
                        )}
                        {columnId === 'compare_mode' && <Badge appearance="outline" size="large">{COMPARE_LABELS[item.compare_mode]}</Badge>}
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
                className={danger.solid}
                icon={<Delete24Regular />}
                onClick={handleDelete}
                disabled={deleting}
              >
                {deleting ? '删除中…' : '确认删除'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={groupOpen} onOpenChange={(_, d) => { if (!d.open && !groupBusy) closeGroupDialog(); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>加入分组</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Field label="分组名" required>
                  <Combobox
                    placeholder="选择已有分组，或输入新分组名"
                    value={groupText}
                    onChange={(e) => {
                      const v = e.target instanceof HTMLInputElement ? e.target.value : '';
                      setGroupText(v);
                    }}
                    disabled={groupBusy}
                    autoFocus
                    style={{ width: '100%' }}
                  >
                    {groupCandidates.map((name) => (
                      <Option key={name} value={name}>{name}</Option>
                    ))}
                  </Combobox>
                </Field>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  {`将把选中的 ${selectedProblemIds.length} 道题归入该分组。`}
                </Caption1>
                {groupError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{groupError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={closeGroupDialog} disabled={groupBusy}>取消</Button>
              <Button appearance="primary" onClick={handleBatchGroup} disabled={groupBusy}>
                {groupBusy ? '保存中…' : '确认加入'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={bulkDeleteOpen} onOpenChange={(_, d) => { if (!d.open && !bulkDeleting) closeBulkDeleteDialog(); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>批量删除题目</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>
                  {`确定删除选中的 ${selectedProblemIds.length} 道题？题面与全部测试用例一并删除，且不可恢复。`}
                </Caption1>
                {bulkDeleteError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{bulkDeleteError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={closeBulkDeleteDialog} disabled={bulkDeleting}>取消</Button>
              <Button
                appearance="primary"
                className={danger.solid}
                icon={<Delete24Regular />}
                onClick={handleBatchDelete}
                disabled={bulkDeleting}
              >
                {bulkDeleting ? '删除中…' : '确认删除'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
