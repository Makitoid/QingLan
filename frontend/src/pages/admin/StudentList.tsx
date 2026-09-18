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
  MessageBarBody,
  SearchBox,
  Text,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Add24Regular, ArrowUpload24Regular, Key24Regular } from '@fluentui/react-icons';
import { createStudent, importStudentsCsv, listStudents, resetStudentPassword, updateStudentActive } from '../../api';
import type { ImportResult, StudentItem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';

const columns: TableColumnDefinition<StudentItem>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '学号' }),
  createTableColumn({ columnId: 'display_name', renderHeaderCell: () => '姓名' }),
  createTableColumn({ columnId: 'teachers', renderHeaderCell: () => '归属教师' }),
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '操作' }),
];

export function AdminStudentList() {
  const t = useTheme();
  const { data, error, loading, reload } = useAsync(listStudents, []);
  const fileRef = useRef<HTMLInputElement>(null);

  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', display_name: '' });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [resetTarget, setResetTarget] = useState<StudentItem | null>(null);
  const [newPassword, setNewPassword] = useState('');

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
      reload();
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
      const result = await importStudentsCsv(file);
      setImportResult(result);
      reload();
    } catch (err) {
      setImportResult({ success_count: 0, failures: [{ line: 0, username: null, reason: errMessage(err) }] });
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
      reload();
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

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  const keyword = search.trim();
  const filtered = (data ?? []).filter((s) => !keyword || s.username.includes(keyword) || s.display_name.includes(keyword));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: tokens.spacingHorizontalM, flexWrap: 'wrap' }}>
        <Text as="h2" size={600} weight="semibold">学生管理</Text>
        <div style={{ display: 'flex', gap: tokens.spacingHorizontalS, alignItems: 'center' }}>
          <SearchBox placeholder="按学号或姓名搜索" value={search} onChange={(_, d) => setSearch(d.value)} style={{ width: '240px' }} />
          <Button appearance="secondary" icon={<ArrowUpload24Regular />} onClick={() => fileRef.current?.click()} disabled={busy}>
            CSV 导入
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: 'none' }}
            onChange={(e) => void handleImportFile(e.target.files?.[0])}
          />
          <Button appearance="primary" icon={<Add24Regular />} onClick={() => setCreateOpen(true)}>新建学生</Button>
        </div>
      </div>

      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
        CSV 格式：每行「学号,姓名」，初始密码默认与学号相同（以后端实现为准）。
      </Caption1>

      {importResult && (
        <MessageBar
          intent={importResult.failures.length > 0 ? 'warning' : 'success'}
          style={{ borderRadius: tokens.borderRadiusMedium }}
        >
          <MessageBarBody>
            导入完成：成功 {importResult.success_count} 条
            {importResult.failures.length > 0 && `，失败 ${importResult.failures.length} 条：`}
            {importResult.failures.map((f) => (
              <div key={`${f.line}-${f.username}`}>
                第 {f.line} 行{f.username ? `（${f.username}）` : ''}：{f.reason}
              </div>
            ))}
          </MessageBarBody>
        </MessageBar>
      )}

      {filtered.length === 0 ? (
        <EmptyView title="没有学生" description="使用「新建学生」或「CSV 导入」添加学生账号。" />
      ) : (
        <DataGrid items={filtered} columns={columns} focusMode="cell" resizableColumns>
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
    </div>
  );
}
