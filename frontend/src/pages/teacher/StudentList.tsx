import { useTheme } from '../../appTheme';
import { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Caption1,
  Card,
  CardHeader,
  Checkbox,
  createTableColumn,
  DataGrid,
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
  Spinner,
  Text,
  tokens,

  type TableColumnDefinition,
  type TableRowId,
} from '@fluentui/react-components';
import {
  Add24Regular,
  ArrowExit24Regular,
  Delete24Regular,
  Dismiss24Regular,
  Edit24Regular,
  PeopleTeam24Regular,
} from '@fluentui/react-icons';
import {
  createTeacherSubgroup,
  deleteTeacherSubgroup,
  listTeacherClasses,
  listTeacherStudents,
  listTeacherSubgroups,
  renameTeacherSubgroup,
  replaceTeacherSubgroupStudents,
  teacherBindStudents,
  teacherUnbindStudents,
} from '../../api';
import type { BoundStudentItem, SubgroupItem } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, EmptyView, errCode, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { BulkActionBar } from '../../components/BulkActionBar';
import { useDangerStyles } from '../../components/dangerStyles';

/** 搜索去抖：输入即打 `/teacher/students?q=`，但每 300ms 最多一次。 */
const SEARCH_DEBOUNCE_MS = 300;

/** 「按学生 ID 添加」的输入分隔符：半/全角逗号、分号、空白都认。 */
const ID_SEPARATOR = /[,，;；\s]+/;

const columns: TableColumnDefinition<BoundStudentItem>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '学号' }),
  createTableColumn({ columnId: 'display_name', renderHeaderCell: () => '姓名' }),
  createTableColumn({ columnId: 'groups', renderHeaderCell: () => '组别' }),
  createTableColumn({ columnId: 'source', renderHeaderCell: () => '来源' }),
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
];

/**
 * 教师端「我的学生」：左列是我的子分组（自建、用于收窄发布受众），右列是名单成员。
 *
 * 决策 1b / 1e：「从班级拉学生」已下线——名单 = 可教组成员 ∪ 手动添加，进入本页即是全部
 * 可教学生；组别派生的学生只能由管理员撤销组别来移出，本页只允许移出手动添加的学生。
 * 决策 1c：子分组同时是新建场次的发布受众来源。
 * 可教组别（`GET /teacher/classes`）降级为只读徽标，本页不含任何组别写入口。
 */
export function TeacherStudentList() {
  const t = useTheme();
  const danger = useDangerStyles();

  // LI-01：搜索走后端 q，不把全量名单拉到本地再过滤。
  const [search, setSearch] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, error, loading, reload } = useAsync(() => listTeacherStudents(debouncedQ), [debouncedQ]);
  const {
    data: classData,
    error: classError,
    loading: classLoading,
    reload: reloadClasses,
  } = useAsync(listTeacherClasses, []);
  const {
    data: subgroupData,
    error: subgroupError,
    loading: subgroupLoading,
    reload: reloadSubgroups,
  } = useAsync(listTeacherSubgroups, []);

  const [selectedIds, setSelectedIds] = useState<Set<TableRowId>>(new Set());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ intent: 'success' | 'warning' | 'error'; text: string } | null>(null);

  // 子分组：新建 / 改名共用一个名称弹窗
  const [nameDialog, setNameDialog] = useState<{ mode: 'create' | 'rename'; subgroup: SubgroupItem | null } | null>(null);
  const [nameText, setNameText] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  // 子分组：删除确认（被场次引用时服务端 409）
  const [deleteTarget, setDeleteTarget] = useState<SubgroupItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // 子分组：成员全量替换（候选永远是完整名单，不受搜索影响）
  const [membersTarget, setMembersTarget] = useState<SubgroupItem | null>(null);
  const [memberCandidates, setMemberCandidates] = useState<BoundStudentItem[]>([]);
  const [memberPicked, setMemberPicked] = useState<number[]>([]);
  const [memberFilter, setMemberFilter] = useState('');
  const [membersLoading, setMembersLoading] = useState(false);
  const [membersError, setMembersError] = useState<string | null>(null);

  // 「按学生 ID 添加」
  const [bindOpen, setBindOpen] = useState(false);
  const [idText, setIdText] = useState('');
  const [bindError, setBindError] = useState<string | null>(null);

  // 「移出手动添加的学生」确认
  const [unbindOpen, setUnbindOpen] = useState(false);

  const students = useMemo(() => data ?? [], [data]);
  const classes = useMemo(() => classData ?? [], [classData]);
  const subgroups = useMemo(() => subgroupData ?? [], [subgroupData]);

  /** 我经可教组别拿到的学生 ID：这些学生不能由教师移出名单。 */
  const groupStudentIds = useMemo(
    () => new Set(classes.flatMap((cls) => cls.students.map((s) => s.id))),
    [classes],
  );

  // 换了一批行就清选择，否则残留的选中态指向已经看不见的行（§8.1 约定）。
  useEffect(() => {
    setSelectedIds(new Set());
  }, [debouncedQ]);

  const refresh = () => {
    setSelectedIds(new Set());
    reload();
    reloadClasses();
    reloadSubgroups();
  };

  const selectedRows = students.filter((s) => selectedIds.has(s.id));
  const selectedCount = selectedRows.length;
  const selectedDerivedCount = selectedRows.filter((s) => groupStudentIds.has(s.id)).length;

  const idTokens = idText.split(ID_SEPARATOR).map((x) => x.trim()).filter(Boolean);
  const idBadTokens = idTokens.filter((x) => !/^\d+$/.test(x));
  const parsedIds = useMemo(
    () => Array.from(new Set(idTokens.filter((x) => /^\d+$/.test(x)).map(Number))).filter((n) => n > 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [idText],
  );

  const handleBindByIds = async () => {
    if (parsedIds.length === 0) return;
    setBusy(true);
    setBindError(null);
    try {
      const result = await teacherBindStudents(parsedIds);
      setBindOpen(false);
      setIdText('');
      setNotice(
        result.success_count === parsedIds.length
          ? { intent: 'success', text: `已添加 ${result.success_count} 人。` }
          : {
            intent: 'success',
            text: `已添加 ${result.success_count} 人，另有 ${parsedIds.length - result.success_count} 个 ID 已经在你的名单里（未重复添加）。`,
          },
      );
      refresh();
    } catch (err) {
      // BD-04：整批 422，后端不回任何学生明细（避免这个入口变成全量名册），文案同样不带明细。
      setBindError(
        errCode(err) === 'INVALID_STUDENT_IDS'
          ? `${errMessage(err)}——本次未添加任何学生，且无法告知具体是哪几个 ID；请逐个核对后重试。`
          : errMessage(err),
      );
    } finally {
      setBusy(false);
    }
  };

  const openCreate = () => {
    setFormError(null);
    setNameText('');
    setNameDialog({ mode: 'create', subgroup: null });
  };

  const openRename = (subgroup: SubgroupItem) => {
    setFormError(null);
    setNameText(subgroup.name);
    setNameDialog({ mode: 'rename', subgroup });
  };

  const handleNameSubmit = async () => {
    if (!nameDialog) return;
    const name = nameText.trim();
    if (!name) {
      setFormError('请输入子分组名称');
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      if (nameDialog.mode === 'create') {
        await createTeacherSubgroup(name);
        setNotice({ intent: 'success', text: `已新建子分组「${name}」，接着可以往里加成员。` });
      } else if (nameDialog.subgroup) {
        await renameTeacherSubgroup(nameDialog.subgroup.id, name);
        setNotice({ intent: 'success', text: `子分组已改名为「${name}」。` });
      }
      setNameDialog(null);
      refresh();
    } catch (err) {
      setFormError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteTeacherSubgroup(deleteTarget.id);
      setNotice({ intent: 'success', text: `已删除子分组「${deleteTarget.name}」，名单里的学生不受影响。` });
      setDeleteTarget(null);
      refresh();
    } catch (err) {
      // 409 SUBGROUP_IN_USE：后端消息里带着引用了它的场次标题。
      setDeleteError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openMembers = async (subgroup: SubgroupItem) => {
    setMembersTarget(subgroup);
    setMemberPicked(subgroup.student_ids);
    setMemberFilter('');
    setMembersError(null);
    setMembersLoading(true);
    try {
      // 全量替换的上送集合必须基于完整名单，不能让搜索框把候选人截断。
      const rows = await listTeacherStudents();
      setMemberCandidates(rows);
    } catch (err) {
      setMemberCandidates([]);
      setMembersError(errMessage(err));
    } finally {
      setMembersLoading(false);
    }
  };

  const toggleMember = (studentId: number, checked: boolean) => {
    setMemberPicked((prev) => (checked ? [...prev, studentId] : prev.filter((id) => id !== studentId)));
  };

  const handleMembersSubmit = async () => {
    if (!membersTarget) return;
    setBusy(true);
    setMembersError(null);
    try {
      await replaceTeacherSubgroupStudents(membersTarget.id, memberPicked);
      setNotice({
        intent: 'success',
        text: `子分组「${membersTarget.name}」的成员已更新（${memberPicked.length} 人）。`,
      });
      setMembersTarget(null);
      refresh();
    } catch (err) {
      setMembersError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const visibleCandidates = useMemo(() => {
    const q = memberFilter.trim().toLowerCase();
    return q
      ? memberCandidates.filter((s) => s.username.toLowerCase().includes(q)
        || s.display_name.toLowerCase().includes(q))
      : memberCandidates;
  }, [memberCandidates, memberFilter]);

  const handleUnbind = async () => {
    const ids = selectedRows.map((s) => s.id);
    if (ids.length === 0) {
      setUnbindOpen(false);
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const result = await teacherUnbindStudents(ids);
      setUnbindOpen(false);
      setNotice(
        result.success_count === 0
          ? { intent: 'warning', text: '没有学生被移出：选中项可能已经不在你的名单里。' }
          : {
            intent: 'success',
            text: `已从名单移出 ${result.success_count} 人；该生的历史提交与成绩仍保留在你可见范围内。`,
          },
      );
      refresh();
    } catch (err) {
      setNotice(
        errCode(err) === 'ROSTER_DERIVED_STUDENT'
          ? { intent: 'warning', text: errMessage(err) }
          : { intent: 'error', text: `移出失败：${errMessage(err)}` },
      );
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="我的学生"
        subtitle="名单由管理员分配给你的可教组别自动组成，也可以按学生 ID 补人；组别派生的学生如需移出，请找管理员撤销相应组别。子分组是你在名单之上自建的集合，发布场次时用它选择受众。"
        actions={
          <>
            <SearchBox
              placeholder="按学号或姓名搜索"
              value={search}
              onChange={(_, d) => setSearch(d.value)}
              style={{ width: '220px' }}
            />
            <Button appearance="secondary" icon={<Add24Regular />} onClick={() => { setBindError(null); setBindOpen(true); }} disabled={busy}>
              按学生 ID 添加
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

      <BulkActionBar
        selectedCount={selectedCount}
        actions={[
          {
            key: 'unbind',
            label: '移出手动添加',
            icon: <ArrowExit24Regular />,
            danger: true,
            disabled: busy || selectedDerivedCount > 0,
            onClick: () => setUnbindOpen(true),
          },
          { key: 'cancel', label: '取消选择', icon: <Dismiss24Regular />, disabled: busy, onClick: () => setSelectedIds(new Set()) },
        ]}
      />

      {selectedDerivedCount > 0 && (
        <MessageBar intent="warning" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>
            {`选中的 ${selectedDerivedCount} 名学生来自你的可教组别，需由管理员撤销组别后才能离开名单，因此「移出手动添加」已置灰；请取消勾选这些学生后重试。`}
          </MessageBarBody>
        </MessageBar>
      )}

      {!!classError && (
        <MessageBar intent="warning" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>
            {`可教组别暂时读不到，下表的「来源」列可能不准：${errMessage(classError)}`}
          </MessageBarBody>
          <MessageBarActions>
            <Button size="small" appearance="subtle" onClick={reloadClasses}>重试</Button>
          </MessageBarActions>
        </MessageBar>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: tokens.spacingHorizontalL }}>
        <Card size="medium" style={{ flex: '1 1 320px', minWidth: '280px' }}>
          <CardHeader
            header={<Text weight="semibold">我的子分组</Text>}
            action={(
              <Button size="small" appearance="secondary" icon={<Add24Regular />} onClick={openCreate} disabled={busy}>
                新建子分组
              </Button>
            )}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
            {subgroupLoading ? (
              <Spinner label="正在读取子分组…" />
            ) : subgroups.length === 0 ? (
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                还没有子分组。可以按教学进度把名单分成若干组，发布场次时按组下发。
              </Caption1>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                {subgroups.map((subgroup) => (
                  <div
                    key={subgroup.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: tokens.spacingHorizontalXS,
                      padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
                      border: `1px solid ${t.colorNeutralStroke3}`,
                      borderRadius: tokens.borderRadiusMedium,
                    }}
                  >
                    <Text weight="semibold">{subgroup.name}</Text>
                    <Caption1 style={{ color: t.colorNeutralForeground3 }}>{`${subgroup.member_count} 人`}</Caption1>
                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center' }}>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<PeopleTeam24Regular />}
                        disabled={busy}
                        onClick={() => void openMembers(subgroup)}
                      >
                        成员
                      </Button>
                      <Button size="small" appearance="subtle" icon={<Edit24Regular />} disabled={busy} onClick={() => openRename(subgroup)}>
                        改名
                      </Button>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<Delete24Regular />}
                        disabled={busy}
                        style={{ color: t.colorPaletteRedForeground1 }}
                        onClick={() => { setDeleteError(null); setDeleteTarget(subgroup); }}
                      >
                        删除
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!!subgroupError && (
              <MessageBar intent="warning" style={{ borderRadius: tokens.borderRadiusMedium }}>
                <MessageBarBody>{`子分组读取失败：${errMessage(subgroupError)}`}</MessageBarBody>
                <MessageBarActions>
                  <Button size="small" appearance="subtle" onClick={reloadSubgroups}>重试</Button>
                </MessageBarActions>
              </MessageBar>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXS }}>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                可教组别（只读，由管理员分配；其成员就是名单来源）
              </Caption1>
              {classLoading ? (
                <Spinner size="tiny" />
              ) : classes.length === 0 ? (
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  还没有可教组别，请联系管理员在「教师管理 → 可教组别」里分配。
                </Caption1>
              ) : (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalXS }}>
                  {classes.map((cls) => (
                    <Badge key={cls.id} appearance="tint" size="large">
                      {`${cls.name}（${cls.member_count} 人）`}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Card>

        <Card size="medium" style={{ flex: '2 1 520px', minWidth: '320px' }}>
          <CardHeader header={<Text weight="semibold">{`名单（${students.length} 人）`}</Text>} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>
              {debouncedQ
                ? `关键词「${debouncedQ}」在当前名单里匹配 ${students.length} 名学生（后端搜索，共多少条以清空搜索为准）。`
                : '名单 = 可教组别成员 ∪ 按 ID 手动添加；「组别」列展示学生所属的行政班。'}
            </Caption1>

            {students.length === 0 ? (
              <EmptyView
                title={debouncedQ ? '没有匹配的学生' : '名单里还没有学生'}
                description={debouncedQ
                  ? '换个关键词试试，或清空搜索框查看全部学生。'
                  : '可教组别里的学生会自动出现在这里；组别还没分配给你时，可以先用「按学生 ID 添加」。'}
                action={debouncedQ
                  ? <Button appearance="secondary" size="small" onClick={() => setSearch('')}>清空搜索</Button>
                  : undefined}
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
                <DataGridBody<BoundStudentItem>>
                  {({ item, rowId }) => (
                    <DataGridRow<BoundStudentItem> key={rowId}>
                      {({ columnId }) => (
                        <DataGridCell>
                          {columnId === 'username' && item.username}
                          {columnId === 'display_name' && item.display_name}
                          {columnId === 'groups' && (
                            item.groups.length === 0
                              ? <Caption1 style={{ color: t.colorNeutralForeground3 }}>不在任何组别</Caption1>
                              : (
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalXS }}>
                                  {item.groups.map((g) => (
                                    <Badge key={g.id} appearance="tint" size="large">{g.name}</Badge>
                                  ))}
                                </div>
                              )
                          )}
                          {columnId === 'source' && (
                            groupStudentIds.has(item.id)
                              ? <Badge appearance="outline" size="large">可教组别</Badge>
                              : <Badge appearance="tint" size="large">手动添加</Badge>
                          )}
                          {columnId === 'is_active' && (
                            item.is_active
                              ? <Badge className="ql-badge-status" size="large" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }}>启用</Badge>
                              : <Badge className="ql-badge-status" size="large" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }}>已停用</Badge>
                          )}
                        </DataGridCell>
                      )}
                    </DataGridRow>
                  )}
                </DataGridBody>
              </DataGrid>
            )}
          </div>
        </Card>
      </div>

      {/* 子分组名称：新建 / 改名共用 */}
      <Dialog open={nameDialog !== null} onOpenChange={(_, d) => { if (!d.open && !busy) setNameDialog(null); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{nameDialog?.mode === 'rename' ? '重命名子分组' : '新建子分组'}</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  子分组只由你在名单之上维护，用于发布场次时选择受众；管理员分配的可教组别不受影响。
                </Caption1>
                <Field label="名称" required>
                  <Input
                    value={nameText}
                    onChange={(_, d) => setNameText(d.value)}
                    placeholder="如：提高班 A 组"
                    maxLength={50}
                    autoFocus
                  />
                </Field>
                {formError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{formError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setNameDialog(null)} disabled={busy}>取消</Button>
              <Button
                appearance="primary"
                icon={nameDialog?.mode === 'rename' ? <Edit24Regular /> : <Add24Regular />}
                disabled={busy || !nameText.trim()}
                onClick={() => void handleNameSubmit()}
              >
                {busy ? '保存中…' : '保存'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* 删除保护：被场次引用时服务端 409，消息里列出相关场次 */}
      <Dialog open={deleteTarget !== null} onOpenChange={(_, d) => { if (!d.open && !busy) setDeleteTarget(null); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>删除子分组</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>{`确定删除子分组「${deleteTarget?.name ?? ''}」？`}</Caption1>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  删除只影响这个分组本身，名单里的学生不受影响；被场次引用的分组不能删除，请先调整那些场次的发布受众。
                </Caption1>
                {deleteError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{deleteError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setDeleteTarget(null)} disabled={busy}>取消</Button>
              <Button
                appearance="primary"
                className={danger.solid}
                icon={<Delete24Regular />}
                disabled={busy}
                onClick={() => void handleDelete()}
              >
                {busy ? '删除中…' : '确认删除'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* 成员维护：全量替换，候选来自完整名单（与搜索框无关） */}
      <Dialog open={membersTarget !== null} onOpenChange={(_, d) => { if (!d.open && !busy) setMembersTarget(null); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{`子分组成员${membersTarget ? `：${membersTarget.name}` : ''}`}</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  勾选要放进该子分组的学生，保存时按勾选结果整体覆盖；全部取消勾选即清空成员。只有当前名单里的学生可选。
                </Caption1>

                {membersError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{membersError}</MessageBarBody>
                  </MessageBar>
                )}

                <Field label="筛选">
                  <Input
                    value={memberFilter}
                    onChange={(_, d) => setMemberFilter(d.value)}
                    placeholder="按学号或姓名筛选"
                  />
                </Field>

                {membersLoading ? (
                  <Spinner label="正在读取名单…" />
                ) : memberCandidates.length === 0 ? (
                  <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                    你的名单里还没有学生，先去添加学生或请管理员分配可教组别。
                  </Text>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXS, maxHeight: '48vh', overflowY: 'auto' }}>
                    {visibleCandidates.map((s) => (
                      <Checkbox
                        key={s.id}
                        checked={memberPicked.includes(s.id)}
                        disabled={busy}
                        onChange={(_, d) => toggleMember(s.id, Boolean(d.checked))}
                        label={`${s.username}　${s.display_name}`}
                      />
                    ))}
                    {visibleCandidates.length === 0 && (
                      <Caption1 style={{ color: t.colorNeutralForeground3 }}>没有匹配的学生。</Caption1>
                    )}
                  </div>
                )}

                <Caption1 style={{ color: t.colorNeutralForeground3 }}>{`已勾选 ${memberPicked.length} 人。`}</Caption1>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setMembersTarget(null)} disabled={busy}>取消</Button>
              <Button
                appearance="primary"
                icon={<PeopleTeam24Regular />}
                disabled={busy || membersLoading}
                onClick={() => void handleMembersSubmit()}
              >
                {busy ? '保存中…' : '保存成员'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* BD-04：转学生 / 旁听等暂不在可教组里的兜底入口。后端只回条数，不回明细。 */}
      <Dialog open={bindOpen} onOpenChange={(_, d) => { if (!busy) setBindOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>按学生 ID 添加</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  用于转学生、旁听生这类还不在你可教组别里的情况。
                  这里要的是学生的系统 ID（一个纯数字，<b>不是学号</b>），来自管理员的「学生管理」列表里的学生 ID，需要的话请找管理员要。
                  可以一次给多个，用逗号或空格分隔。
                </Caption1>
                <Field label="学生 ID" required>
                  <Input
                    value={idText}
                    onChange={(_, d) => setIdText(d.value)}
                    placeholder="例如：12, 34 56"
                    autoFocus
                  />
                </Field>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  {parsedIds.length > 0
                    ? `识别到 ${parsedIds.length} 个学生 ID。`
                    : '还没有识别到有效的数字 ID。'}
                  {idBadTokens.length > 0 && ` 其中「${idBadTokens.join('、')}」不是数字 ID，会被忽略。`}
                </Caption1>
                {bindError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{bindError}</MessageBarBody>
                  </MessageBar>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setBindOpen(false)} disabled={busy}>取消</Button>
              <Button
                appearance="primary"
                icon={<Add24Regular />}
                disabled={busy || parsedIds.length === 0}
                onClick={() => void handleBindByIds()}
              >
                {busy ? '添加中…' : `确认添加${parsedIds.length > 0 ? `（${parsedIds.length} 个 ID）` : ''}`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* BD-05 + 0.3.2 F1：只移手动添加的学生，历史提交与成绩保留 */}
      <Dialog open={unbindOpen} onOpenChange={(_, d) => { if (!busy) setUnbindOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>移出手动添加的学生</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>
                  {`确定把选中的 ${selectedCount} 名学生移出我的名单？移出后你看不到他们的新提交，也不能再给他们放题。`}
                </Caption1>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  学生账号本身、以及他们已有的提交与成绩都保留，仍在你的成绩页可见范围内；再按学生 ID 添加回来即可恢复。
                </Caption1>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  来自可教组别的学生不能在这里移出，需由管理员撤销相应组别。
                </Caption1>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setUnbindOpen(false)} disabled={busy}>取消</Button>
              <Button
                appearance="primary"
                className={danger.solid}
                icon={<ArrowExit24Regular />}
                disabled={busy}
                onClick={() => void handleUnbind()}
              >
                {busy ? '移出中…' : '确认移出'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}

export default TeacherStudentList;
