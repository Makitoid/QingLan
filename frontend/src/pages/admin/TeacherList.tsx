import { useTheme } from '../../appTheme';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
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
} from '@fluentui/react-components';
import { Add24Regular, Dismiss24Regular, Key24Regular } from '@fluentui/react-icons';
import {
  createTeacher,
  exportTeachers,
  importTeachers,
  listTeachers,
  resetTeacherPassword,
  updateTeacherActive,
} from '../../api';
import type { ImportResult, TeacherItem, TempCredential } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { CredentialDialog } from '../../components/CredentialDialog';
import { ImportExportMenu } from '../../components/ImportExportMenu';

/** LI-01：搜索去抖，避免每敲一个字就打一次 `/admin/teachers?q=`。 */
const SEARCH_DEBOUNCE_MS = 300;

const columns: TableColumnDefinition<TeacherItem>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '工号' }),
  createTableColumn({ columnId: 'display_name', renderHeaderCell: () => '姓名' }),
  createTableColumn({ columnId: 'student_count', renderHeaderCell: () => '名单学生数' }),
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
  createTableColumn({ columnId: 'actions', renderHeaderCell: () => '操作' }),
];

export function AdminTeacherList() {
  const t = useTheme();

  const [search, setSearch] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, error, loading, reload } = useAsync(() => listTeachers(debouncedQ), [debouncedQ]);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ username: '', display_name: '' });
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [notice, setNotice] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  // PW-09：重置返回的临时凭证明细（教师单个重置也是一行）。
  const [credentials, setCredentials] = useState<TempCredential[] | null>(null);
  const [credentialTitle, setCredentialTitle] = useState('');

  const handleCreate = async () => {
    setFormError(null);
    if (!form.username.trim() || !form.display_name.trim()) {
      setFormError('工号与姓名均为必填');
      return;
    }
    setBusy(true);
    try {
      // PW-01：新建教师不传密码——统一初始密码 + 首登强制改密。
      await createTeacher({ username: form.username.trim(), display_name: form.display_name.trim() });
      setCreateOpen(false);
      setForm({ username: '', display_name: '' });
      reload();
    } catch (err) {
      setFormError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleImportFile = async (file: File) => {
    setBusy(true);
    setImportResult(null);
    setNotice(null);
    try {
      setImportResult(await importTeachers(file));
      reload();
    } catch (err) {
      setImportResult({ success_count: 0, failures: [{ line: 0, reason: errMessage(err) }] });
    } finally {
      setBusy(false);
    }
  };

  /** 导出教师名单（0.4.1 F3）：与当前搜索同口径，xlsx / csv 由下拉菜单选择。 */
  const handleExport = async (format: 'xlsx' | 'csv') => {
    setExporting(true);
    setNotice(null);
    try {
      await exportTeachers({ format, q: debouncedQ });
      setNotice({ intent: 'success', text: `已导出教师名单（${format === 'csv' ? 'CSV' : 'Excel'}）。` });
    } catch (err) {
      setNotice({ intent: 'error', text: `导出失败：${errMessage(err)}` });
    } finally {
      setExporting(false);
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

  /** PW-04【v1.1：教师同规则】：不给输入密码的框，后端生成随机密码并返回明细。 */
  const handleResetPassword = async (item: TeacherItem) => {
    if (!window.confirm(`确定重置教师「${item.display_name}（${item.username}）」的密码？将生成一个随机密码，原密码立即失效。`)) return;
    setBusy(true);
    try {
      const cred = await resetTeacherPassword(item.id);
      setCredentialTitle(`临时密码 · ${cred.display_name}（${cred.username}）`);
      setCredentials([cred]);
      reload();
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
        actions={
          <>
            <SearchBox placeholder="按工号或姓名搜索" value={search} onChange={(_, d) => setSearch(d.value)} style={{ width: '240px' }} />
            <ImportExportMenu
              entity="教师"
              importHint="xlsx 三列：工号｜姓名｜可教组别（可选）"
              busy={busy}
              exporting={exporting}
              onImportFile={(file) => void handleImportFile(file)}
              onExport={(format) => void handleExport(format)}
            />
            <Button appearance="primary" icon={<Add24Regular />} onClick={() => setCreateOpen(true)} disabled={busy}>
              新建教师
            </Button>
          </>
        }
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

      {data && data.length === 0 ? (
        <EmptyView
          title={debouncedQ ? '没有匹配的教师' : '还没有教师账号'}
          description={debouncedQ ? '换个关键词试试，或清空搜索查看全部教师。' : '点击右上角「新建教师」或「导入/导出 → 导入教师」创建账号。'}
        />
      ) : (
        <DataGrid items={data ?? []} columns={columns} focusMode="cell" resizableColumns getRowId={(item) => item.id}>
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
            <DialogTitle>新建教师</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Field label="工号（登录名）" required>
                  <Input value={form.username} onChange={(_, d) => setForm({ ...form, username: d.value })} autoFocus />
                </Field>
                <Field label="姓名" required>
                  <Input value={form.display_name} onChange={(_, d) => setForm({ ...form, display_name: d.value })} />
                </Field>
                <MessageBar intent="info" style={{ borderRadius: tokens.borderRadiusMedium }}>
                  <MessageBarBody>
                    初始密码由系统统一发放（统一初始密码），这里不需要填写；该教师首次登录时会被强制改密。
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

      <CredentialDialog
        open={credentials !== null}
        onOpenChange={(next) => { if (!next) setCredentials(null); }}
        title={credentialTitle}
        credentials={credentials ?? []}
        csvPrefix="教师重置凭证"
      />
    </div>
  );
}
