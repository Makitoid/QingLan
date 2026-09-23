import { useTheme } from '../../appTheme';
import { useEffect, useRef, useState } from 'react';
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
  MessageBarActions,
  MessageBarBody,
  Option,
  SearchBox,
  Text,
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
  TextColumnOne24Regular,
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
import type { BatchResetMode, ImportResult, StudentItem, TempCredential } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { BulkActionBar } from '../../components/BulkActionBar';
import { GroupPickerDialog, type GroupPickerAction } from '../../components/GroupPickerDialog';
import { GroupsManageDialog } from '../../components/GroupsManageDialog';
import { CredentialDialog } from '../../components/CredentialDialog';
import { downloadCredentialCsv, initialPasswordRows } from '../../components/credentialCsv';

/**
 * PW-06 阈值：与后端 `config.BATCH_RESET_ASK_THRESHOLD` 同值。
 * 选中人数超过它才弹「统一 / 随机」二选一，否则直接走随机（逐生独立密码）。
 */
const BATCH_RESET_ASK_THRESHOLD = 20;

/** 搜索输入去抖，避免每敲一个字就打一次 `/admin/students?q=`。 */
const SEARCH_DEBOUNCE_MS = 300;

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

  // LI-01 / LI-02：搜索、组别走后端参数（学校规模下搜索优先于分页）。
  const [search, setSearch] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [groupFilter, setGroupFilter] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  // 换筛选条件等于换了一批行：不清选择会残留已不可见行的选中态（§8.1 约定）。
  useEffect(() => {
    setSelectedIds(new Set());
  }, [debouncedQ, groupFilter]);

  const groupId = groupFilter ? Number(groupFilter) : null;

  const { data, error, loading, reload } = useAsync(
    () => listStudents({ q: debouncedQ, group_id: groupId }),
    [debouncedQ, groupFilter],
  );
  const { data: groupData, reload: reloadGroups } = useAsync(listGroups, []);
  const fileRef = useRef<HTMLInputElement>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ username: '', display_name: '' });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  // 多选状态：行 id 的类型是 TableRowId（string | number），写成 Set<number> 会在
  // onSelectionChange 里拿到 Set<TableRowId> 赋值时触发 TS2345。
  const [selectedIds, setSelectedIds] = useState<Set<TableRowId>>(new Set());

  // 分组对话框
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerAction, setPickerAction] = useState<GroupPickerAction>('add');
  const [manageOpen, setManageOpen] = useState(false);

  // PW-06：>阈值时的「统一 / 随机」询问对话框
  const [askBatchOpen, setAskBatchOpen] = useState(false);
  const [askBatchCount, setAskBatchCount] = useState(0);

  // PW-09：重置返回的凭证（单个与批量共用一个对话框）
  const [credentials, setCredentials] = useState<TempCredential[] | null>(null);
  const [credentialTitle, setCredentialTitle] = useState('');

  const [notice, setNotice] = useState<{ intent: 'success' | 'warning' | 'error'; text: string } | null>(null);

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

  /** 提交时再按 id 回取一次，避免对话框期间列表已刷新导致选择漂移。 */
  const currentSelectedIds = () => students.filter((s) => selectedIds.has(s.id)).map((s) => s.id);

  const handleCreate = async () => {
    setFormError(null);
    if (!form.username.trim() || !form.display_name.trim()) {
      setFormError('学号与姓名均为必填');
      return;
    }
    setBusy(true);
    try {
      // PW-01：不传密码——后端统一发放初始密码，学生首登被强制改密。
      await createStudent({ username: form.username.trim(), display_name: form.display_name.trim() });
      setCreateOpen(false);
      setForm({ username: '', display_name: '' });
      setNotice({ intent: 'success', text: '已创建学生，初始密码由系统统一发放，该生首次登录须先修改密码。' });
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

  /** PW-04：单个重置——不给输入密码的框，直接让后端生成随机密码并把明细返回展示。 */
  const handleResetPassword = async (item: StudentItem) => {
    if (!window.confirm(`确定重置学生「${item.display_name}（${item.username}）」的密码？将生成一个随机密码，学生原密码立即失效。`)) return;
    setBusy(true);
    setNotice(null);
    try {
      const cred = await resetStudentPassword(item.id);
      setCredentialTitle(`临时密码 · ${cred.display_name}（${cred.username}）`);
      setCredentials([cred]);
      refresh();
    } catch (err) {
      setNotice({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const runBatchReset = async (ids: number[], mode: BatchResetMode) => {
    setBusy(true);
    setNotice(null);
    try {
      const result = await adminBatchResetPassword(ids, mode);
      setAskBatchOpen(false);
      setCredentialTitle(`批量重置完成 · ${result.count} 人`);
      setCredentials(result.credentials);
      setNotice({
        intent: 'success',
        text: mode === 'unified'
          ? `已将 ${result.count} 名学生的密码统一重置为统一初始密码（不过期），首次登录须改密。`
          : `已为 ${result.count} 名学生各自生成随机密码（7 天内有效），请复制或下载 CSV 后转告本人。`,
      });
      refresh();
    } catch (err) {
      setNotice({ intent: 'error', text: `批量重置失败：${errMessage(err)}` });
    } finally {
      setBusy(false);
    }
  };

  /** PW-06：>20 人先问「统一 / 随机」；≤20 人直接走随机。 */
  const handleBatchResetClick = () => {
    const ids = currentSelectedIds();
    if (ids.length === 0) return;
    if (ids.length > BATCH_RESET_ASK_THRESHOLD) {
      setAskBatchCount(ids.length);
      setAskBatchOpen(true);
      return;
    }
    void runBatchReset(ids, 'random');
  };

  /** PW-09 ②：初始密码表纯前端按已加载的数据拼装，不发任何请求（坑 22：也别走直链）。 */
  const handleExportInitialPasswords = () => {
    const rows = selectedStudents;
    if (rows.length === 0) return;
    downloadCredentialCsv(initialPasswordRows(rows), '初始密码表', '初始密码');
    const alreadyChanged = rows.filter((s) => !s.must_change_password).length;
    setNotice({
      intent: alreadyChanged > 0 ? 'warning' : 'success',
      text: alreadyChanged > 0
        ? `已导出 ${rows.length} 名学生的初始密码表，其中 ${alreadyChanged} 名已改过密，表里的统一初始密码对其无效。`
        : `已导出 ${rows.length} 名学生的初始密码表（密码列为统一初始密码）。`,
    });
  };

  const openPicker = (action: GroupPickerAction) => {
    setPickerAction(action);
    setPickerOpen(true);
  };

  const handleBatchGroupMembers = async (groupIds: number[]) => {
    // 提交时再取一次选中项，避免对话框期间选择已变化。
    const ids = currentSelectedIds();
    await adminBatchGroupMembers(ids, groupIds, pickerAction);
  };

  const handleBatchGroupSubmitted = (groupIds: number[]) => {
    const verb = pickerAction === 'add' ? '加入' : '移出';
    const count = selectedStudentIds.length;
    setNotice({ intent: 'success', text: `已将 ${count} 名学生${verb} ${groupIds.length} 个分组。` });
    refresh();
    reloadGroups();
  };

  const handleBatchActive = async (isActive: boolean) => {
    const ids = currentSelectedIds();
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="学生管理"
        subtitle={
          <>
            导入格式：xlsx / txt / csv，四列「学号 | 姓名 | 组别 | 教师（可选）」。组别可留空；一行多个组别或教师用 、 ， , ； ; / 分隔，
            不存在的组别会自动创建；教师列须与组别同时给出且按工号精确匹配，用于登记「可教组别」。
            新建与导入的学生都用统一初始密码，首次登录被强制改密。
          </>
        }
        actions={
          <>
            <SearchBox
              placeholder="按学号或姓名搜索"
              value={search}
              onChange={(_, d) => setSearch(d.value)}
              style={{ width: '200px' }}
            />
            <Dropdown
              placeholder="全部组别"
              value={groupFilter ? groups.find((g) => String(g.id) === groupFilter)?.name ?? '' : ''}
              selectedOptions={groupFilter ? [groupFilter] : []}
              onOptionSelect={(_, d) => setGroupFilter(String(d.optionValue ?? ''))}
              disabled={busy}
              style={{ width: '140px' }}
            >
              <Option value="" text="全部组别">全部组别</Option>
              {groups.map((g) => (
                <Option key={g.id} value={String(g.id)} text={g.name}>
                  {`${g.name}（${g.member_count} 人）`}
                </Option>
              ))}
            </Dropdown>
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
            <Button appearance="primary" icon={<Add24Regular />} onClick={() => setCreateOpen(true)} disabled={busy}>
              新建学生
            </Button>
          </>
        }
      />

      <BulkActionBar
        selectedCount={selectedStudentIds.length}
        actions={[
          { key: 'export-initial', label: '导出初始密码表', icon: <TextColumnOne24Regular />, appearance: 'primary', disabled: busy, onClick: handleExportInitialPasswords },
          { key: 'group-add', label: '加入分组', icon: <Group24Regular />, disabled: busy, onClick: () => openPicker('add') },
          { key: 'group-remove', label: '移出分组', icon: <ArrowExit24Regular />, disabled: busy, onClick: () => openPicker('remove') },
          { key: 'reset-password', label: '批量重置密码', icon: <Key24Regular />, disabled: busy, onClick: handleBatchResetClick },
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

      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
        {`当前筛选共 ${students.length} 名学生${debouncedQ ? `（关键词「${debouncedQ}」）` : ''}。`}
        重置密码会即时生成一次性随机密码，只在弹窗里显示一次，可复制或下载 CSV 分发。
      </Caption1>

      {students.length === 0 ? (
        <EmptyView
          title="没有符合条件的学生"
          description="清空搜索/筛选看看，或使用「新建学生」「导入学生」添加学生账号。"
        />
      ) : (
        <DataGrid
          items={students}
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
                              <Badge key={g.id} appearance="tint" size="large">{g.name}</Badge>
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
                        ? <Badge className="ql-badge-status" size="large" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }}>启用</Badge>
                        : <Badge className="ql-badge-status" size="large" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }}>已停用</Badge>
                    )}
                    {columnId === 'actions' && (
                      <div style={{ display: 'flex', gap: tokens.spacingHorizontalXS }}>
                        <Button size="small" appearance="subtle" icon={<Key24Regular />} disabled={busy} onClick={() => void handleResetPassword(item)}>
                          重置密码
                        </Button>
                        <Button size="small" appearance="subtle" disabled={busy} onClick={() => void handleToggleActive(item)}>
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
                <MessageBar intent="info" style={{ borderRadius: tokens.borderRadiusMedium }}>
                  <MessageBarBody>
                    初始密码由系统统一发放（统一初始密码），这里不需要填写；该生首次登录时会被强制改密。
                  </MessageBarBody>
                </MessageBar>
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

      {/* PW-06：批量重置的「统一 / 随机」二选一询问 */}
      <Dialog open={askBatchOpen} onOpenChange={(_, d) => { if (!busy) setAskBatchOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>批量重置 {askBatchCount} 名学生</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  本次人数超过 {BATCH_RESET_ASK_THRESHOLD} 人，请先选择重置方式。两种方式都会让原密码立即失效，
                  并要求这些学生下次登录时改密。
                </Caption1>
                <div>
                  <Text weight="semibold">A. 统一重置</Text>
                  <Caption1 style={{ display: 'block', color: t.colorNeutralForeground3 }}>
                    全员使用统一初始密码：整批只算一次哈希，最快，且密码不过期。适合集中上机前统一发放。
                  </Caption1>
                </div>
                <div>
                  <Text weight="semibold">B. 各自随机</Text>
                  <Caption1 style={{ display: 'block', color: t.colorNeutralForeground3 }}>
                    每人一个独立随机密码：更安全，逐行明细可复制或下载 CSV 分发；随机密码自生成起 7 天内有效。
                  </Caption1>
                </div>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setAskBatchOpen(false)} disabled={busy}>取消</Button>
              <Button appearance="outline" onClick={() => void runBatchReset(currentSelectedIds(), 'random')} disabled={busy}>
                {busy ? '处理中…' : `B. 各自随机（${askBatchCount} 人）`}
              </Button>
              <Button appearance="primary" onClick={() => void runBatchReset(currentSelectedIds(), 'unified')} disabled={busy}>
                {busy ? '处理中…' : 'A. 统一重置'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <CredentialDialog
        open={credentials !== null}
        onOpenChange={(next) => { if (!next) setCredentials(null); }}
        title={credentialTitle}
        credentials={credentials ?? []}
        csvPrefix="重置凭证"
      />

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
