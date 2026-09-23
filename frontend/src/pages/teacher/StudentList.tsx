import { useTheme } from '../../appTheme';
import { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Caption1,
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
  Dismiss24Regular,
  PeopleTeam24Regular,
} from '@fluentui/react-icons';
import {
  listTeacherClasses,
  listTeacherStudents,
  teacherBindFromClass,
  teacherBindStudents,
  teacherUnbindStudents,
} from '../../api';
import type { BoundStudentItem, ClassItem } from '../../api/types';
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
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
];

/**
 * 教师端「我的学生」= 我自己维护的名单（层 3）。
 *
 * GR-02 / BD-01 起教师没有任何组别写权限：`GET /teacher/groups` 与
 * `POST /teacher/students/group_members` 已删除，本页也不出现任何组别编辑控件，
 * 组别（行政班）只以只读徽标展示。名单的三条维护路径：
 * - BD-03 主路径「从班级拉学生」：候选来自 `GET /teacher/classes`（admin 分配的层 2 过滤）。
 * - BD-04 兜底「按学生 ID 添加」：转学生 / 旁听等暂不在组里的场景，后端只回条数不回明细。
 * - BD-05 「移出名单」：不在名单里的 id 被静默忽略，历史提交与成绩保留。
 *
 * 权限红线：本页不提供任何账号维护入口（建号、启停、改口令都归管理员）。
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

  const [selectedIds, setSelectedIds] = useState<Set<TableRowId>>(new Set());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ intent: 'success' | 'warning' | 'error'; text: string } | null>(null);

  // 换了一批行就清选择，否则残留的选中态指向已经看不见的行（§8.1 约定）。
  useEffect(() => {
    setSelectedIds(new Set());
  }, [debouncedQ]);

  // 「从班级拉学生」
  const [pullOpen, setPullOpen] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [pullError, setPullError] = useState<string | null>(null);

  // 「按学生 ID 添加」
  const [bindOpen, setBindOpen] = useState(false);
  const [idText, setIdText] = useState('');
  const [bindError, setBindError] = useState<string | null>(null);

  // 「移出名单」确认
  const [unbindOpen, setUnbindOpen] = useState(false);
  const [unbindCount, setUnbindCount] = useState(0);

  const students = useMemo(() => data ?? [], [data]);
  const classes = useMemo(() => classData ?? [], [classData]);
  const noClass = !classLoading && !classError && classes.length === 0;

  /** 名单与可教班级是同一件事的两面：刷新名单时一起刷新，`bound` 才会跟上。 */
  const refresh = () => {
    setSelectedIds(new Set());
    reload();
    reloadClasses();
  };

  const currentSelectedIds = () => students.filter((s) => selectedIds.has(s.id)).map((s) => s.id);
  const selectedCount = students.filter((s) => selectedIds.has(s.id)).length;

  const pickedIds = useMemo(() => Array.from(picked), [picked]);
  const pickedCount = pickedIds.length;

  const idTokens = idText.split(ID_SEPARATOR).map((x) => x.trim()).filter(Boolean);
  const idBadTokens = idTokens.filter((x) => !/^\d+$/.test(x));
  const parsedIds = useMemo(
    () => Array.from(new Set(idTokens.filter((x) => /^\d+$/.test(x)).map(Number))).filter((n) => n > 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [idText],
  );

  const openPull = () => {
    setPicked(new Set());
    setPullError(null);
    setPullOpen(true);
    reloadClasses();
  };

  const togglePicked = (id: number, on: boolean) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  /** 组内「全选」：只在还能勾选（未在我名单里）的成员之间来回切换。 */
  const toggleGroup = (cls: ClassItem, on: boolean) => {
    const ids = cls.students.filter((s) => !s.bound).map((s) => s.id);
    setPicked((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });
  };

  const handlePull = async () => {
    if (pickedCount === 0) return;
    setBusy(true);
    setPullError(null);
    try {
      const result = await teacherBindFromClass(pickedIds);
      setPullOpen(false);
      setPicked(new Set());
      setNotice(
        result.success_count === 0
          ? { intent: 'warning', text: '没有新增学生：勾选的学生都已经在你的名单里。' }
          : { intent: 'success', text: `已拉入 ${result.success_count} 人。` },
      );
      refresh();
    } catch (err) {
      // BD-03：任一学生不在可教班级 → 整批 403 且库里零变化，后端文案照抄给老师看。
      setPullError(
        errCode(err) === 'STUDENT_NOT_IN_CLASS'
          ? `${errMessage(err)}（本次未拉入任何学生。可能是管理员刚刚调整过你的可教组别，关闭本窗口重新打开即可拿到最新名单。）`
          : errMessage(err),
      );
    } finally {
      setBusy(false);
    }
  };

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

  const openUnbind = () => {
    const ids = currentSelectedIds();
    if (ids.length === 0) return;
    setUnbindCount(ids.length);
    setUnbindOpen(true);
  };

  const handleUnbind = async () => {
    const ids = currentSelectedIds();
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
      setNotice({ intent: 'error', text: `移出失败：${errMessage(err)}` });
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
        subtitle="这是我自己维护的学生名单：可以从可教班级里拉人、按学生 ID 补人，也可以把人移出。组别（行政班）及其成员由管理员维护，本页只读，也没有任何账号维护入口。"
        actions={
          <>
            <SearchBox
              placeholder="按学号或姓名搜索"
              value={search}
              onChange={(_, d) => setSearch(d.value)}
              style={{ width: '220px' }}
            />
            <Button
              appearance="secondary"
              icon={<PeopleTeam24Regular />}
              onClick={openPull}
              disabled={busy || classLoading || classes.length === 0}
              title={classes.length === 0 ? '还没有可教的班级，请联系管理员分配' : undefined}
            >
              从班级拉学生
            </Button>
            <Button appearance="secondary" icon={<Add24Regular />} onClick={() => { setBindError(null); setBindOpen(true); }} disabled={busy}>
              按学生 ID 添加
            </Button>
          </>
        }
      />

      <BulkActionBar
        selectedCount={selectedCount}
        actions={[
          { key: 'unbind', label: '移出名单', icon: <ArrowExit24Regular />, danger: true, disabled: busy, onClick: openUnbind },
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

      {!!classError && (
        <MessageBar intent="warning" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>
            可教班级暂时读不到，「从班级拉学生」先置灰：{errMessage(classError)}
          </MessageBarBody>
          <MessageBarActions>
            <Button size="small" appearance="subtle" onClick={reloadClasses}>重试</Button>
          </MessageBarActions>
        </MessageBar>
      )}

      {noClass && (
        <MessageBar intent="info" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>
            还没有可教的班级，请联系管理员在「教师管理 → 可教组别」里分配；分配后就能在这里从班级拉学生。
            急用的话（转学生、旁听）可以先用「按学生 ID 添加」。
          </MessageBarBody>
        </MessageBar>
      )}

      <Caption1 style={{ color: t.colorNeutralForeground3 }}>
        {debouncedQ
          ? `关键词「${debouncedQ}」在当前名单里匹配 ${students.length} 名学生（后端搜索，共多少条以清空搜索为准）。`
          : `共 ${students.length} 名学生在你的名单里。`}
      </Caption1>

      {students.length === 0 ? (
        <EmptyView
          title={debouncedQ ? '没有匹配的学生' : '名单里还没有学生'}
          description={debouncedQ
            ? '换个关键词试试，或清空搜索框查看全部学生。'
            : '用右上角「从班级拉学生」把可教班级的学生拉进名单；班级还没分配给你时，可以先「按学生 ID 添加」。'}
          action={debouncedQ
            ? <Button appearance="secondary" size="small" onClick={() => setSearch('')}>清空搜索</Button>
            : (classes.length > 0
              ? <Button appearance="primary" size="small" icon={<PeopleTeam24Regular />} onClick={openPull}>从班级拉学生</Button>
              : undefined)}
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

      {/* BD-03：从可教班级拉学生。候选集完全来自 /teacher/classes，教师看不到组别之外的名册。 */}
      <Dialog open={pullOpen} onOpenChange={(_, d) => { if (!busy) setPullOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>从班级拉学生</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  这里只列出管理员分配给你的可教班级（行政班）里的学生。勾选后一次性拉入我的名单，已经在名单里的会标出来并置灰；
                  停用的学生也能勾选，但他们目前无法登录。
                </Caption1>

                {pullError && (
                  <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                    <MessageBarBody>{pullError}</MessageBarBody>
                  </MessageBar>
                )}

                {classLoading ? (
                  <Spinner label="正在读取可教班级…" />
                ) : classes.length === 0 ? (
                  <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                    还没有可教的班级，请联系管理员在「教师管理 → 可教组别」里分配。
                  </Text>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM, maxHeight: '56vh', overflowY: 'auto' }}>
                    {classes.map((cls) => {
                      const pullable = cls.students.filter((s) => !s.bound);
                      const groupAllPicked = pullable.length > 0 && pullable.every((s) => picked.has(s.id));
                      return (
                        <div key={cls.id} style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXS }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' }}>
                            <Text weight="semibold">{cls.name}</Text>
                            <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                              {`${cls.member_count} 人，可拉入 ${pullable.length} 人`}
                            </Caption1>
                            <Checkbox
                              checked={groupAllPicked}
                              disabled={busy || pullable.length === 0}
                              onChange={(_, d) => toggleGroup(cls, Boolean(d.checked))}
                              label={groupAllPicked ? '取消全选' : '全选本班'}
                            />
                          </div>
                          {cls.students.length === 0 ? (
                            <Caption1 style={{ color: t.colorNeutralForeground3 }}>这个班级还没有成员。</Caption1>
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXXS, paddingInlineStart: tokens.spacingHorizontalS }}>
                              {cls.students.map((s) => (
                                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' }}>
                                  <Checkbox
                                    checked={picked.has(s.id)}
                                    disabled={busy || s.bound}
                                    onChange={(_, d) => togglePicked(s.id, Boolean(d.checked))}
                                    label={`${s.username}　${s.display_name}`}
                                  />
                                  {!s.is_active && (
                                    <Badge className="ql-badge-status" size="large" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 }}>已停用</Badge>
                                  )}
                                  {s.bound && <Badge appearance="outline" size="large">已在名单</Badge>}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setPullOpen(false)} disabled={busy}>取消</Button>
              <Button
                appearance="primary"
                icon={<PeopleTeam24Regular />}
                disabled={busy || pickedCount === 0}
                onClick={() => void handlePull()}
              >
                {busy ? '拉取中…' : `确认拉入${pickedCount > 0 ? `（${pickedCount} 人）` : ''}`}
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
                  用于转学生、旁听生这类还不在你可教班级里的情况。
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

      {/* BD-05：移出名单只断开「我教这个学生」的关系，历史提交与成绩保留。 */}
      <Dialog open={unbindOpen} onOpenChange={(_, d) => { if (!busy) setUnbindOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>移出我的名单</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                <Caption1>
                  确定把选中的 {unbindCount} 名学生移出我的名单？移出后你看不到他们的新提交，也不能再给他们放题。
                </Caption1>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  学生账号本身、以及他们已有的提交与成绩都保留，仍在你的成绩页可见范围内；再把他们拉回来即可恢复。
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
