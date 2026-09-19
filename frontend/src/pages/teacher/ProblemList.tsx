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
import { Add24Regular } from '@fluentui/react-icons';
import { createTeacherProblem, listTeacherProblems } from '../../api';
import type { ProblemSummary } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { PageHeader } from '../../components/PageHeader';

const COMPARE_LABELS: Record<string, string> = { exact: '精确', trim: '忽略空白', float: '浮点容差' };

const columns: TableColumnDefinition<ProblemSummary>[] = [
  createTableColumn({ columnId: 'id', renderHeaderCell: () => 'ID' }),
  createTableColumn({ columnId: 'title', renderHeaderCell: () => '标题' }),
  createTableColumn({ columnId: 'limits', renderHeaderCell: () => '限制' }),
  createTableColumn({ columnId: 'compare_mode', renderHeaderCell: () => '比对模式' }),
  createTableColumn({ columnId: 'created_at', renderHeaderCell: () => '创建时间' }),
];

export function TeacherProblemList() {
  const t = useTheme();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(listTeacherProblems, []);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

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

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="题库"
        actions={<Button appearance="primary" icon={<Add24Regular />} onClick={() => setOpen(true)}>新建题目</Button>}
      />

      {data && data.length === 0 ? (
        <EmptyView title="题库为空" description="点击右上角「新建题目」创建第一道题。" />
      ) : (
        <DataGrid items={data ?? []} columns={columns} focusMode="cell" resizableColumns>
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
                    {columnId === 'limits' && (
                      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                        {item.time_limit_ms} ms / {item.memory_limit_mb} MB
                      </Caption1>
                    )}
                    {columnId === 'compare_mode' && <Badge appearance="outline" size="small">{COMPARE_LABELS[item.compare_mode]}</Badge>}
                    {columnId === 'created_at' && fmtTime(item.created_at)}
                  </DataGridCell>
                )}
              </DataGridRow>
            )}
          </DataGridBody>
        </DataGrid>
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
    </div>
  );
}
