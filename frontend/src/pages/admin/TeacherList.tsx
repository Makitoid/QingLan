import { useTheme } from '../../appTheme';
import { useState } from 'react';
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
  Field,
  Input,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Add24Regular, Key24Regular } from '@fluentui/react-icons';
import { createTeacher, listTeachers, resetTeacherPassword, updateTeacherActive } from '../../api';
import type { TeacherItem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';

const columns: TableColumnDefinition<TeacherItem>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '工号' }),
  createTableColumn({ columnId: 'display_name', renderHeaderCell: () => '姓名' }),
  createTableColumn({ columnId: 'student_count', renderHeaderCell: () => '绑定学生数' }),
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '操作' }),
];

export function AdminTeacherList() {
  const t = useTheme();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(listTeachers, []);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', display_name: '' });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [resetTarget, setResetTarget] = useState<TeacherItem | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const handleCreate = async () => {
    setFormError(null);
    if (!form.username.trim() || !form.password || !form.display_name.trim()) {
      setFormError('工号、密码、姓名均为必填');
      return;
    }
    setBusy(true);
    try {
      await createTeacher({ username: form.username.trim(), password: form.password, display_name: form.display_name.trim() });
      setCreateOpen(false);
      setForm({ username: '', password: '', display_name: '' });
      reload();
    } catch (err) {
      setFormError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleToggleActive = async (item: TeacherItem) => {
    const action = item.is_active ? '停用' : '启用';
    if (!window.confirm(`确定${action}教师「${item.display_name}（${item.username}）」？停用后该账号无法登录。`)) return;
    try {
      await updateTeacherActive(item.id, !item.is_active);
      reload();
    } catch (err) {
      window.alert(errMessage(err));
    }
  };

  const handleResetPassword = async () => {
    if (!resetTarget || !newPassword) return;
    setBusy(true);
    try {
      await resetTeacherPassword(resetTarget.id, newPassword);
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="教师管理"
        actions={<Button appearance="primary" icon={<Add24Regular />} onClick={() => setCreateOpen(true)}>新建教师</Button>}
      />

      {data && data.length === 0 ? (
        <EmptyView title="还没有教师账号" description="点击右上角「新建教师」创建账号。" />
      ) : (
        <DataGrid items={data ?? []} columns={columns} focusMode="cell" resizableColumns>
          <DataGridHeader>
            <DataGridRow>
              {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
            </DataGridRow>
          </DataGridHeader>
          <DataGridBody<TeacherItem>>
            {({ item, rowId }) => (
              <DataGridRow<TeacherItem> key={rowId}>
                {({ columnId }) => (
                  <DataGridCell>
                    {columnId === 'username' && item.username}
                    {columnId === 'display_name' && (
                      <Link to={`/admin/teachers/${item.id}`} style={{ color: t.colorBrandForeground1, fontWeight: tokens.fontWeightSemibold }}>
                        {item.display_name}
                      </Link>
                    )}
                    {columnId === 'student_count' && item.student_count}
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
                        <Button size="small" appearance="subtle" onClick={() => navigate(`/admin/teachers/${item.id}`)}>
                          详情
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
            <DialogTitle>新建教师</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Field label="工号（登录名）" required>
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
