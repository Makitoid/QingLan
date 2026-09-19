import { useTheme } from '../../appTheme';
import { useRef, useState } from 'react';
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
  Field,
  Input,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  SearchBox,
  tokens,

  type TableColumnDefinition,
  type TableRowId,
} from '@fluentui/react-components';
import {
  Add24Regular,
  ArrowExit24Regular,
  ArrowUpload24Regular,
  Dismiss24Regular,
  Group24Regular,
  Key24Regular,
  LockOpen24Regular,
  PeopleTeam24Regular,
  Stop24Regular,
} from '@fluentui/react-icons';
import {
  adminBatchActive,
  adminBatchGroupMembers,
  adminBatchResetPassword,
  createStudent,
  importStudents,
  listGroups,
  listStudents,
  resetStudentPassword,
  updateStudentActive,
} from '../../api';
import type { ImportResult, StudentItem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { BulkActionBar } from '../../components/BulkActionBar';
import { GroupPickerDialog, type GroupPickerAction } from '../../components/GroupPickerDialog';
import { GroupsManageDialog } from '../../components/GroupsManageDialog';

/** 批量重置的密码长度下限，与后端 BatchResetPasswordRequest.min_length 一致。 */
const MIN_PASSWORD_LENGTH = 6;

const columns: TableColumnDefinition<StudentItem>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '学号' }),
  createTableColumn({ columnId: 'display_name', renderHeaderCell: () => '姓名' }),
  createTableColumn({ columnId: 'groups', renderHeaderCell: () => '分组' }),
  createTableColumn({ columnId: 'teachers', renderHeaderCell: () => '归属教师' }),
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '操作' }),
];

export function AdminStudentList() {
  const t = useTheme();
  const { data, error, loading, reload } = useAsync(listStudents, []);
  const { data: groupData, reload: reloadGroups } = useAsync(listGroups, []);
  const fileRef = useRef<HTMLInputElement>(null);

  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', display_name: '' });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [resetTarget, setResetTarget] = useState<StudentItem | null>(null);
  const [newPassword, setNewPassword] = useState('');

  // 多选状态：行 id 的类型是 TableRowId（string | number），写成 Set<number> 会在
  // onSelectionChange 里拿到 Set<TableRowId> 赋值时触发 TS2345。
  const [selectedIds, setSelectedIds] = useState<Set<TableRowId>>(new Set());

  // 分组对话框
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerAction, setPickerAction] = useState<GroupPickerAction>('add');
  const [manageOpen, setManageOpen] = useState(false);

  // 批量重置密码对话框
  const [batchResetOpen, setBatchResetOpen] = useState(false);
  const [batchNewPassword, setBatchNewPassword] = useState('');
  const [batchError, setBatchError] = useState<string | null>(null);

  const [notice, setNotice] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  const students = data ?? [];
  const groups = groupData ?? [];

  /** 重新拉列表时一并清空选择：旧选择可能已经指向被删掉/过滤掉的行。 */
  const refresh = () => {
    setSelectedIds(new Set());
    reload();
  };

  // 以当前数据为准回推选中项，避免选择里残留已不存在的 id。
  const selectedStudents = students.filter((s) => selectedIds.has(s.id));
  const selectedStudentIds = selectedStudents.map((s) => s.id);

  const handleCreate = async () => {
    setFormError(null);
    if (!form.username.trim() || !form.password || !form.display_name.trim()) {
      setFormError('学号、密码、姓名均为必填');
      return;
    }
    setBusy(true);
    try {
      await createStudent({ username: form.username.trim(), password: form.password, display_name: form.display_name.trim() });
      setCreateOpen(false);
      setForm({ username: '', password: '', display_name: '' });
      refresh();
    } catch (err) {
      setFormError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleImportFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setImportResult(null);
    try {
      const result = await importStudents(file);
      setImportResult(result);
      refresh();
      reloadGroups();
    } catch (err) {
      setImportResult({ success_count: 0, failures: [{ line: 0, reason: errMessage(err) }] });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const handleToggleActive = async (item: StudentItem) => {
    const action = item.is_active ? '停用' : '启用';
    if (!window.confirm(`确定${action}学生「${item.display_name}（${item.username}）」？停用后该账号无法登录。`)) return;
    try {
      await updateStudentActive(item.id, !item.is_active);
      refresh();
    } catch (err) {
      window.alert(errMessage(err));
    }
  };

  const handleResetPassword = async () => {
    if (!resetTarget || !newPassword) return;
    setBusy(true);
    try {
      await resetStudentPassword(resetTarget.id, newPassword);
      setResetTarget(null);
      setNewPassword('');
      window.alert('密码已重置');
    } catch (err) {
      window.alert(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openPicker = (action: GroupPickerAction) => {
    setPickerAction(action);
    setPickerOpen(true);
  };

  const handleBatchGroupMembers = async (groupIds: number[]) => {
    // 提交时再取一次选中项，避免对话框期间选择已变化。
    const ids = students.filter((s) => selectedIds.has(s.id)).map((s) => s.id);
    await adminBatchGroupMembers(ids, groupIds, pickerAction);
  };

  const handleBatchGroupSubmitted = (groupIds: number[]) => {
    const verb = pickerAction === 'add' ? '加入' : '移出';
    const count = selectedStudentIds.length;
    setNotice({ intent: 'success', text: `已将 ${count} 名学生${verb} ${groupIds.length} 个分组。` });
    refresh();
    reloadGroups();
  };

  const handleBatchResetPassword = async () => {
    const ids = students.filter((s) => selectedIds.has(s.id)).map((s) => s.id);
    if (ids.length === 0) return;
    if (batchNewPassword.length < MIN_PASSWORD_LENGTH) {
      setBatchError(`新密码至少 ${MIN_PASSWORD_LENGTH} 位`);
      return;
    }
    setBusy(true);
    setBatchError(null);
    try {
      await adminBatchResetPassword(ids, batchNewPassword);
      setBatchResetOpen(false);
      setBatchNewPassword('');
      setNotice({ intent: 'success', text: `已重置 ${ids.length} 名学生的密码。` });
      refresh();
    } catch (err) {
      setBatchError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleBatchActive = async (isActive: boolean) => {
    const ids = students.filter((s) => selectedIds.has(s.id)).map((s) => s.id);
    if (ids.length === 0) return;
    const action = isActive ? '启用' : '停用';
    if (!window.confirm(`确定${action}选中的 ${ids.length} 名学生？停用后这些账号无法登录。`)) return;
    setBusy(true);
    setNotice(null);
    try {
      await adminBatchActive(ids, isActive);
      setNotice({ intent: 'success', text: `已${action} ${ids.length} 名学生。` });
      refresh();
    } catch (err) {
      setNotice({ intent: 'error', text: `批量${action}失败：${errMessage(err)}` });
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  const keyword = search.trim().toLowerCase();
  const filtered = keyword
    ? students.filter((s) => s.username.toLowerCase().includes(keyword) || s.display_name.toLowerCase().includes(keyword))
    : students;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="学生管理"
        subtitle={
          <>
            导入格式：xlsx / txt / csv，三列「学生ID | 姓名 | 组别」。组别可留空；一行多个分组用 、 ， , ； ; / 分隔，
            不存在的分组会自动创建。初始密码默认与学号相同（以后端实现为准）。
          </>
        }
        actions={
          <>
            <SearchBox placeholder="按学号或姓名搜索" value={search} onChange={(_, d) => setSearch(d.value)} style={{ width: '240px' }} />
            <Button appearance="secondary" icon={<PeopleTeam24Regular />} onClick={() => setManageOpen(true)}>
              分组管理
            </Button>
            <Button appearance="secondary" icon={<ArrowUpload24Regular />} onClick={() => fileRef.current?.click()} disabled={busy}>
              导入学生
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.txt,.csv"
              style={{ display: 'none' }}
              onChange={(e) => void handleImportFile(e.target.files?.[0])}
            />
            <Button appearance="primary" icon={<Add24Regular />} onClick={() => setCreateOpen(true)}>新建学生</Button>
          </>
        }
      />

      <BulkActionBar
        selectedCount={selectedStudentIds.length}
        actions={[
          { key: 'group-add', label: '加入分组', icon: <Group24Regular />, appearance: 'primary', disabled: busy, onClick: () => openPicker('add') },
          { key: 'group-remove', label: '移出分组', icon: <ArrowExit24Regular />, disabled: busy, onClick: () => openPicker('remove') },
          { key: 'reset-password', label: '重置密码', icon: <Key24Regular />, disabled: busy, onClick: () => { setBatchError(null); setBatchNewPassword(''); setBatchResetOpen(true); } },
          { key: 'deactivate', label: '批量停用', icon: <Stop24Regular />, danger: true, disabled: busy, onClick: () => void handleBatchActive(false) },
          { key: 'activate', label: '批量启用', icon: <LockOpen24Regular />, disabled: busy, onClick: () => void handleBatchActive(true) },
          { key: 'cancel', label: '取消选择', icon: <Dismiss24Regular />, disabled: busy, onClick: () => setSelectedIds(new Set()) },
        ]}
      />

      {notice && (
        <MessageBar intent={notice.intent} style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{notice.text}</MessageBarBody>
          <MessageBarActions>
            <Button size="small" appearance="subtle" icon={<Dismiss24Regular />} onClick={() => setNotice(null)}>
              关闭
            </Button>
          </MessageBarActions>
        </MessageBar>
      )}

      {importResult && (
        <MessageBar
          intent={importResult.failures.length > 0 ? 'warning' : 'success'}
          style={{ borderRadius: tokens.borderRadiusMedium }}
        >
          <MessageBarBody>
            导入完成：成功 {importResult.success_count} 条
            {importResult.failures.length > 0 && `，失败 ${importResult.failures.length} 条：`}
            {importResult.failures.map((f) => {
              const who = f.username ?? f.content;
              return (
                <div key={`${f.line}-${who ?? ''}`}>
                  第 {f.line} 行{who ? `（${who}）` : ''}：{f.reason}
                </div>
              );
            })}
          </MessageBarBody>
        </MessageBar>
      )}

      {filtered.length === 0 ? (
        <EmptyView title="没有学生" description="使用「新建学生」或「导入学生」添加学生账号。" />
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
          <DataGridBody<StudentItem>>
            {({ item, rowId }) => (
              <DataGridRow<StudentItem> key={rowId}>
                {({ columnId }) => (
                  <DataGridCell>
                    {columnId === 'username' && item.username}
                    {columnId === 'display_name' && item.display_name}
                    {columnId === 'groups' && (
                      item.groups.length === 0
                        ? <Caption1 style={{ color: t.colorNeutralForeground3 }}>—</Caption1>
                        : (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalXS }}>
                            {item.groups.map((g) => (
                              <Badge key={g.id} appearance="tint" size="small">{g.name}</Badge>
                            ))}
                          </div>
                        )
                    )}
                    {columnId === 'teachers' && (
                      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                        {item.teachers.length === 0 ? '未绑定' : item.teachers.map((x) => x.display_name).join('、')}
                      </Caption1>
                    )}
                    {columnId === 'is_active' && (
                      item.is_active
                        ? <Badge size="small" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }}>启用</Badge>
                        : <Badge size="small" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }}>已停用</Badge>
                    )}
                    {columnId === 'actions' && (
                      <div style={{ display: 'flex', gap: tokens.spacingHorizontalXS }}>
                        <Button size="small" appearance="subtle" icon={<Key24Regular />} onClick={() => { setResetTarget(item); setNewPassword(''); }}>
                          重置密码
                        </Button>
                        <Button size="small" appearance="subtle" onClick={() => void handleToggleActive(item)}>
                          {item.is_active ? '停用' : '启用'}
                        </Button>
                      </div>
                    )}
                  </DataGridCell>
                )}
              </DataGridRow>
            )}
          </DataGridBody>
        </DataGrid>
      )}

      <Dialog open={createOpen} onOpenChange={(_, d) => setCreateOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>新建学生</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Field label="学号（登录名）" required>
                  <Input value={form.username} onChange={(_, d) => setForm({ ...form, username: d.value })} autoFocus />
                </Field>
                <Field label="姓名" required>
                  <Input value={form.display_name} onChange={(_, d) => setForm({ ...form, display_name: d.value })} />
                </Field>
                <Field label="初始密码" required>
                  <Input type="password" value={form.password} onChange={(_, d) => setForm({ ...form, password: d.value })} />
                </Field>
                {formError && <Caption1 style={{ color: t.colorPaletteRedForeground1 }}>{formError}</Caption1>}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setCreateOpen(false)} disabled={busy}>取消</Button>
              <Button appearance="primary" onClick={handleCreate} disabled={busy}>{busy ? '创建中…' : '创建'}</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={resetTarget !== null} onOpenChange={(_, d) => { if (!d.open) setResetTarget(null); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>重置密码 · {resetTarget?.display_name}</DialogTitle>
            <DialogContent>
              <Field label="新密码" required>
                <Input type="password" value={newPassword} onChange={(_, d) => setNewPassword(d.value)} autoFocus />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setResetTarget(null)} disabled={busy}>取消</Button>
              <Button appearance="primary" onClick={handleResetPassword} disabled={busy || !newPassword}>确认重置</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={batchResetOpen} onOpenChange={(_, d) => { if (!busy) setBatchResetOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>批量重置密码</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  将把选中的 {selectedStudentIds.length} 名学生的密码统一重置为下面填写的新密码，
                  这些学生原有的密码立即失效，且无法撤销；请确认学生已知晓。
                </Caption1>
                <Field label="新密码" required>
                  <Input
                    type="password"
                    value={batchNewPassword}
                    onChange={(_, d) => setBatchNewPassword(d.value)}
                    autoFocus
                    disabled={busy}
                  />
                </Field>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>至少 {MIN_PASSWORD_LENGTH} 位。</Caption1>
                {batchError && <Caption1 style={{ color: t.colorPaletteRedForeground1 }}>{batchError}</Caption1>}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setBatchResetOpen(false)} disabled={busy}>取消</Button>
              <Button appearance="primary" onClick={handleBatchResetPassword} disabled={busy || !batchNewPassword}>
                {busy ? '处理中…' : `确认重置 ${selectedStudentIds.length} 名学生`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <GroupPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        action={pickerAction}
        groups={groups}
        studentCount={selectedStudentIds.length}
        onSubmit={handleBatchGroupMembers}
        onSubmitted={handleBatchGroupSubmitted}
      />

      <GroupsManageDialog
        open={manageOpen}
        onOpenChange={setManageOpen}
        onChanged={() => {
          // 分组名会出现在学生列表里，重命名 / 删除后两边都要刷新。
          reloadGroups();
          refresh();
        }}
      />
    </div>
  );
}
