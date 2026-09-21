import { useTheme } from '../../appTheme';
import { useEffect, useMemo, useState, type ReactElement } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  Card,
  CardHeader,
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
  MessageBar,
  MessageBarBody,
  SearchBox,
  Spinner,
  Text,
  tokens,
  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Add24Regular, ArrowExit24Regular, Key24Regular, Save24Regular } from '@fluentui/react-icons';
import {
  getTeacherGroups,
  getTeacherStudents,
  listGroups,
  listStudents,
  listTeachers,
  putTeacherGroups,
  resetTeacherPassword,
} from '../../api';
import type { GroupItem, StudentItem, TeacherGroups, TempCredential } from '../../api/types';
import { EmptyView, ErrorView, LoadingView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { CredentialDialog } from '../../components/CredentialDialog';
import { useDangerStyles } from '../../components/dangerStyles';

const rosterColumns: TableColumnDefinition<StudentItem>[] = [
  createTableColumn({ columnId: 'username', renderHeaderCell: () => '学号' }),
  createTableColumn({ columnId: 'display_name', renderHeaderCell: () => '姓名' }),
  createTableColumn({ columnId: 'groups', renderHeaderCell: () => '组别' }),
  createTableColumn({ columnId: 'password', renderHeaderCell: () => '改密状态' }),
  createTableColumn({ columnId: 'is_active', renderHeaderCell: () => '状态' }),
];

interface PanelProps {
  title: string;
  hint: string;
  groups: GroupItem[];
  emptyText: string;
  actionLabel: string;
  /** Fluent `Button` 的 icon 槽要的是元素，不是任意 ReactNode（ReactNode 含 false，会 TS2322）。 */
  actionIcon: ReactElement;
  onAction: (group: GroupItem) => void;
  busy: boolean;
}

/** 「可教组别」分配面板的一列：组名 + 成员数 + 加入/移出动作。 */
function GroupPanel({ title, hint, groups, emptyText, actionLabel, actionIcon, onAction, busy }: PanelProps) {
  const t = useTheme();
  return (
    <div
      style={{
        flex: 1,
        minWidth: '240px',
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spacingVerticalSNudge,
        border: `1px solid ${t.colorNeutralStroke2}`,
        borderRadius: tokens.borderRadiusMedium,
        padding: tokens.spacingVerticalS,
      }}
    >
      <div>
        <Text weight="semibold">{title}</Text>
        <Caption1 style={{ display: 'block', color: t.colorNeutralForeground3 }}>{hint}</Caption1>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXXS, maxHeight: '280px', overflowY: 'auto' }}>
        {groups.length === 0 ? (
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>{emptyText}</Caption1>
        ) : (
          groups.map((g) => (
            <div key={g.id} style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
              <Text size={300} style={{ flex: 1 }}>{g.name}</Text>
              <Caption1 style={{ color: t.colorNeutralForeground4 }}>{g.member_count} 人</Caption1>
              <Button size="small" appearance="subtle" icon={actionIcon} disabled={busy} onClick={() => onAction(g)}>
                {actionLabel}
              </Button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/**
 * 教师详情（BD-02 / BD-06）：
 * ① 可教组别（层 2）——admin 唯一的任教安排入口，左右双栏分配，保存前列 diff 再确认；
 * ② 学生名单（层 3）——**只读**：admin 直绑写接口已删除，名单由教师本人在可教组内拉/移；
 * ③ 重置密码——随机密码只在响应里给一次（PW-04 / PW-09）。
 */
export function AdminTeacherDetail() {
  const { id } = useParams();
  const t = useTheme();
  const danger = useDangerStyles();
  const navigate = useNavigate();
  const teacherId = Number(id);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown | null>(null);
  const [teacherName, setTeacherName] = useState('');

  const [allGroups, setAllGroups] = useState<GroupItem[]>([]);
  /** 服务端已保存的可教组别。 */
  const [savedGroupIds, setSavedGroupIds] = useState<Set<number>>(new Set());
  /** 页面上的工作副本，点「保存分配」前不落库。 */
  const [pickedGroupIds, setPickedGroupIds] = useState<Set<number>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);

  const [students, setStudents] = useState<StudentItem[]>([]);
  const [rosterIds, setRosterIds] = useState<Set<number>>(new Set());
  const [rosterSearch, setRosterSearch] = useState('');

  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'warning' | 'error'; text: string } | null>(null);
  const [credentials, setCredentials] = useState<TempCredential[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([listTeachers(), listGroups(), getTeacherGroups(teacherId), getTeacherStudents(teacherId), listStudents()])
      .then(([teachers, groups, assigned, roster, allStudents]) => {
        if (cancelled) return;
        const teacher = teachers.find((x) => x.id === teacherId);
        setTeacherName(teacher ? `${teacher.display_name}（${teacher.username}）` : `#${teacherId}`);
        setAllGroups(groups);
        setSavedGroupIds(new Set(assigned.group_ids));
        setPickedGroupIds(new Set(assigned.group_ids));
        setRosterIds(new Set(roster.student_ids));
        setStudents(allStudents);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [teacherId]);

  const groupById = useMemo(() => new Map(allGroups.map((g) => [g.id, g] as const)), [allGroups]);
  const availableGroups = allGroups.filter((g) => !pickedGroupIds.has(g.id));
  const pickedGroups = Array.from(pickedGroupIds)
    .map((gid) => groupById.get(gid))
    .filter((g): g is GroupItem => Boolean(g))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));

  const addedIds = Array.from(pickedGroupIds).filter((gid) => !savedGroupIds.has(gid));
  const removedIds = Array.from(savedGroupIds).filter((gid) => !pickedGroupIds.has(gid));
  const namesOf = (ids: number[]) => ids.map((gid) => `「${groupById.get(gid)?.name ?? gid}」`).join('、') || '无';

  const setPicked = (gid: number, on: boolean) => {
    setPickedGroupIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(gid);
      else next.delete(gid);
      return next;
    });
  };

  const handleSaveGroups = async () => {
    setBusy(true);
    setMessage(null);
    setConfirmOpen(false);
    try {
      const result: TeacherGroups = await putTeacherGroups(teacherId, Array.from(pickedGroupIds));
      const next = new Set(result.group_ids);
      setSavedGroupIds(next);
      setPickedGroupIds(new Set(next));
      setMessage({
        intent: 'success',
        text: `可教组别已保存（新增 ${addedIds.length} 个、移除 ${removedIds.length} 个）。教师侧的既有名单保留，只是不能再从被移除的组拉新人。`,
      });
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  /** BD-06：名单只读，这里只导出查看用的 CSV，不做任何写入。 */
  const rosterStudents = useMemo(() => students.filter((s) => rosterIds.has(s.id)), [students, rosterIds]);
  const keyword = rosterSearch.trim();
  const visibleRoster = keyword
    ? rosterStudents.filter((s) => s.username.includes(keyword) || s.display_name.includes(keyword))
    : rosterStudents;

  const handleResetPassword = async () => {
    if (!window.confirm('确定重置该教师的密码？将生成一个随机密码，原密码立即失效。')) return;
    setBusy(true);
    setMessage(null);
    try {
      const cred = await resetTeacherPassword(teacherId);
      setCredentials([cred]);
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={() => navigate(0)} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate('/admin/teachers')}>← 返回教师管理</Button>
        </Caption1>
        <PageHeader
          title={<>教师详情 · {teacherName}</>}
          actions={
            <Button appearance="secondary" icon={<Key24Regular />} disabled={busy} onClick={() => void handleResetPassword()}>
              重置密码
            </Button>
          }
        />
      </div>

      {message && (
        <MessageBar intent={message.intent} style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{message.text}</MessageBarBody>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader
          header={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
              <Text weight="semibold">可教组别（任教安排）</Text>
              <Badge appearance="tint" size="large">
                已选 {pickedGroupIds.size} / 共 {allGroups.length}
              </Badge>
            </span>
          }
          action={
            <Button
              appearance="primary"
              icon={busy ? <Spinner size="tiny" /> : <Save24Regular />}
              disabled={busy || (addedIds.length === 0 && removedIds.length === 0)}
              onClick={() => setConfirmOpen(true)}
            >
              保存分配
            </Button>
          }
        />
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          组别（行政班）的成员由管理员在「学生管理」维护；这里决定该教师**能从哪些组里**拉学生进自己的名单。
          保存为全量替换，教师侧已有名单不受影响。
        </Caption1>
        {addedIds.length + removedIds.length > 0 && (
          <Caption1 style={{ display: 'block', color: t.colorPaletteDarkOrangeForeground1 }}>
            待保存：新增 {addedIds.length} 个、移除 {removedIds.length} 个。
          </Caption1>
        )}
        <div style={{ display: 'flex', gap: tokens.spacingHorizontalM, marginTop: tokens.spacingVerticalM, flexWrap: 'wrap' }}>
          <GroupPanel
            title="全部组别"
            hint="点「加入」把该组设为可教"
            groups={availableGroups}
            emptyText={allGroups.length === 0 ? '还没有任何组别，请先到「学生管理 → 分组管理」创建。' : '全部组别都已是可教组别。'}
            actionLabel="加入"
            actionIcon={<Add24Regular />}
            onAction={(g) => setPicked(g.id, true)}
            busy={busy}
          />
          <GroupPanel
            title="已选可教组别"
            hint="点「移出」取消该组的任教资格"
            groups={pickedGroups}
            emptyText="尚未分配任何可教组别，该教师暂时拉不到任何班级的学生。"
            actionLabel="移出"
            actionIcon={<ArrowExit24Regular />}
            onAction={(g) => setPicked(g.id, false)}
            busy={busy}
          />
        </div>
      </Card>

      <Card size="medium">
        <CardHeader
          header={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
              <Text weight="semibold">学生名单（只读）</Text>
              <Badge appearance="outline" size="large">{rosterStudents.length} 人</Badge>
            </span>
          }
        />
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          名单（层 3）由教师本人在「我的学生 → 从班级拉学生」里维护，管理员只能查看——原「勾选学生绑定教师」的写入口已随 BD-06 删除。
        </Caption1>
        <div style={{ marginTop: tokens.spacingVerticalS }}>
          <SearchBox placeholder="按学号或姓名筛选名单" value={rosterSearch} onChange={(_, d) => setRosterSearch(d.value)} style={{ maxWidth: '320px' }} />
        </div>
        <div style={{ marginTop: tokens.spacingVerticalM }}>
          {rosterStudents.length === 0 ? (
            <EmptyView title="该教师还没有学生名单" description="请在教师可教的组别分配后，由教师本人从班级里拉取学生。" />
          ) : visibleRoster.length === 0 ? (
            <EmptyView title="名单里没有匹配的学生" description="换个关键词试试，或清空筛选查看全部。" />
          ) : (
            <DataGrid items={visibleRoster} columns={rosterColumns} focusMode="cell" resizableColumns getRowId={(item) => item.id}>
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
                        {columnId === 'password' && (
                          item.must_change_password
                            ? <Badge className="ql-badge-status" size="large" style={{ color: t.colorPaletteDarkOrangeForeground1, backgroundColor: t.colorPaletteDarkOrangeBackground2 }}>未改密</Badge>
                            : <Badge className="ql-badge-status" appearance="outline" size="large">已改密</Badge>
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

      {/* 保存前的 diff 确认（BD-02：全量替换，必须让管理员看清新增/移除了哪些组） */}
      <Dialog open={confirmOpen} onOpenChange={(_, d) => { if (!busy) setConfirmOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>确认可教组别变更</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  这是全量替换操作：保存后该教师的可教组别立即生效，并写入审计日志。
                  教师已有的学生名单保留不断档，只是被移除组里的学生不能再拉新人。
                </Caption1>
                <div>
                  <Text weight="semibold" style={{ color: t.colorPaletteGreenForeground1 }}>新增 {addedIds.length} 个组别</Text>
                  <Caption1 style={{ display: 'block' }}>{namesOf(addedIds)}</Caption1>
                </div>
                <div>
                  <Text weight="semibold" style={{ color: t.colorPaletteRedForeground1 }}>移除 {removedIds.length} 个组别</Text>
                  <Caption1 style={{ display: 'block' }}>{namesOf(removedIds)}</Caption1>
                </div>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setConfirmOpen(false)} disabled={busy}>取消</Button>
              <Button
                appearance={removedIds.length > 0 ? 'outline' : 'primary'}
                className={removedIds.length > 0 ? danger.outline : undefined}
                onClick={() => void handleSaveGroups()}
                disabled={busy}
              >
                {busy ? '保存中…' : '确认保存'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <CredentialDialog
        open={credentials !== null}
        onOpenChange={(next) => { if (!next) setCredentials(null); }}
        title="临时密码"
        credentials={credentials ?? []}
        csvPrefix="教师重置凭证"
      />
    </div>
  );
}
