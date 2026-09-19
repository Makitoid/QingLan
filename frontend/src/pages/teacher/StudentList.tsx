import { useTheme } from '../../appTheme';
import { useState } from 'react';
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
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  SearchBox,
  tokens,

  type TableColumnDefinition,
  type TableRowId,
} from '@fluentui/react-components';
import { ArrowExit24Regular, Dismiss24Regular, Group24Regular } from '@fluentui/react-icons';
import { listTeacherGroups, listTeacherStudents, teacherBatchGroupMembers } from '../../api';
import type { BoundStudentItem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { BulkActionBar } from '../../components/BulkActionBar';
import { GroupPickerDialog, type GroupPickerAction } from '../../components/GroupPickerDialog';

const columns: TableColumnDefinition<BoundStudentItem>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '学号' }),
  createTableColumn({ columnId: 'display_name', renderHeaderCell: () => '姓名' }),
  createTableColumn({ columnId: 'groups', renderHeaderCell: () => '分组' }),
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
];

/**
 * 教师端「我的学生」：只能查看绑定到自己的学生，并批量调整这些学生的分组。
 *
 * 权限红线：本页只碰分组，不提供任何账号维护入口（建号、改口令等都归管理员）。
 */
export function TeacherStudentList() {
  const t = useTheme();
  const { data, error, loading, reload } = useAsync(listTeacherStudents, []);
  const { data: groupData, reload: reloadGroups } = useAsync(listTeacherGroups, []);

  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<TableRowId>>(new Set());
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerAction, setPickerAction] = useState<GroupPickerAction>('add');
  const [notice, setNotice] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  const students = data ?? [];
  const groups = groupData ?? [];
  const selectedStudentIds = students.filter((s) => selectedIds.has(s.id)).map((s) => s.id);

  /** 重新拉列表时清空选择：旧选择可能已指向不再绑定我的学生。 */
  const refresh = () => {
    setSelectedIds(new Set());
    reload();
  };

  const openPicker = (action: GroupPickerAction) => {
    setPickerAction(action);
    setPickerOpen(true);
  };

  const handleSubmit = async (groupIds: number[]) => {
    const ids = students.filter((s) => selectedIds.has(s.id)).map((s) => s.id);
    await teacherBatchGroupMembers(ids, groupIds, pickerAction);
  };

  const handleSubmitted = (groupIds: number[]) => {
    const verb = pickerAction === 'add' ? '加入' : '移出';
    setNotice({ intent: 'success', text: `已将 ${selectedStudentIds.length} 名学生${verb} ${groupIds.length} 个分组。` });
    refresh();
    reloadGroups();
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  const keyword = search.trim().toLowerCase();
  const filtered = keyword
    ? students.filter((s) => s.username.toLowerCase().includes(keyword) || s.display_name.toLowerCase().includes(keyword))
    : students;

  if (students.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
        <PageHeader title="我的学生" subtitle="这里列出已绑定给你的学生账号，分组由管理员创建，你可以批量调整成员。" />
        <EmptyView title="还没有绑定给你的学生" description="请联系管理员在「教师管理 → 教师详情」里把学生绑定给你。" />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="我的学生"
        subtitle={`共 ${students.length} 名学生绑定给你。可批量加入 / 移出分组；学生账号本身由管理员维护。`}
        actions={
          <SearchBox placeholder="按学号或姓名搜索" value={search} onChange={(_, d) => setSearch(d.value)} style={{ width: '240px' }} />
        }
      />

      <BulkActionBar
        selectedCount={selectedStudentIds.length}
        actions={[
          { key: 'group-add', label: '加入分组', icon: <Group24Regular />, appearance: 'primary', onClick: () => openPicker('add') },
          { key: 'group-remove', label: '移出分组', icon: <ArrowExit24Regular />, onClick: () => openPicker('remove') },
          { key: 'cancel', label: '取消选择', icon: <Dismiss24Regular />, onClick: () => setSelectedIds(new Set()) },
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

      {filtered.length === 0 ? (
        <EmptyView title="没有匹配的学生" description="换个关键词试试，或清空搜索查看全部学生。" />
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
          <DataGridBody<BoundStudentItem>>
            {({ item, rowId }) => (
              <DataGridRow<BoundStudentItem> key={rowId}>
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
                    {columnId === 'is_active' && (
                      item.is_active
                        ? <Badge size="small" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }}>启用</Badge>
                        : <Badge size="small" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }}>已停用</Badge>
                    )}
                  </DataGridCell>
                )}
              </DataGridRow>
            )}
          </DataGridBody>
        </DataGrid>
      )}

      <GroupPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        action={pickerAction}
        groups={groups}
        studentCount={selectedStudentIds.length}
        onSubmit={handleSubmit}
        onSubmitted={handleSubmitted}
      />
    </div>
  );
}

export default TeacherStudentList;
