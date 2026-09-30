import { useTheme } from '../../appTheme';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  Card,
  CardHeader,
  Combobox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Listbox,
  MessageBar,
  MessageBarBody,
  Option,
  SearchBox,
  Spinner,
  Text,
  Tooltip,
  tokens,
} from '@fluentui/react-components';
import { Add24Regular, Dismiss24Regular, Key24Regular, Save24Regular } from '@fluentui/react-icons';
import {
  adminBindTempStudents,
  adminUnbindTempStudents,
  getTeacherGroups,
  getTeacherStudents,
  listGroups,
  listTeachers,
  putTeacherGroups,
  resetTeacherPassword,
} from '../../api';
import type { GroupItem, RosterEntry, TeacherGroups, TempCredential } from '../../api/types';
import { EmptyView, ErrorView, LoadingView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { CredentialDialog } from '../../components/CredentialDialog';

/** 「添加临时学生」的输入分隔符：半/全角逗号、分号、空白都认（与教师端 StudentList 同款）。 */
const ID_SEPARATOR = /[,，;；\s]+/;

/**
 * 教师详情（BD-02 / BD-06 + 0.3.2 F1 + 0.4.0 F3）：
 * ① 可教组别（层 2）——admin 唯一的任教安排入口：列出已分配组 + 「添加组」弹窗勾选，保存为全量替换；
 * ② 学生名单——口径是「可教组别成员并集 ∪ 临时添加」，矩阵呈现，撤销组别即刻移除该组学生；
 *    临时学生（层 3 手动绑定行）可在本页代加/代删；
 * ③ 重置密码——随机密码只在响应里给一次（PW-04 / PW-09）。
 */
export function AdminTeacherDetail() {
  const { id } = useParams();
  const t = useTheme();
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

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerIds, setPickerIds] = useState<string[]>([]);
  const [pickerText, setPickerText] = useState('');
  const [pickerQuery, setPickerQuery] = useState('');

  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [rosterSearch, setRosterSearch] = useState('');

  // 0.4.0 F3：代加临时学生（按学生 ID 输入）
  const [bindOpen, setBindOpen] = useState(false);
  const [bindText, setBindText] = useState('');
  const [bindError, setBindError] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'warning' | 'error'; text: string } | null>(null);
  const [credentials, setCredentials] = useState<TempCredential[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([listTeachers(), listGroups(), getTeacherGroups(teacherId), getTeacherStudents(teacherId)])
      .then(([teachers, groups, assigned, teacherRoster]) => {
        if (cancelled) return;
        const teacher = teachers.find((x) => x.id === teacherId);
        setTeacherName(teacher ? `${teacher.display_name}（${teacher.username}）` : `#${teacherId}`);
        setAllGroups(groups);
        setSavedGroupIds(new Set(assigned.group_ids));
        setPickedGroupIds(new Set(assigned.group_ids));
        setRoster(teacherRoster.students);
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
  const assignableGroups = useMemo(
    () => allGroups.filter((g) => !pickedGroupIds.has(g.id)),
    [allGroups, pickedGroupIds],
  );
  const pickedGroups = useMemo(
    () =>
      Array.from(pickedGroupIds)
        .map((gid) => groupById.get(gid))
        .filter((g): g is GroupItem => Boolean(g))
        .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN')),
    [pickedGroupIds, groupById],
  );

  const addedIds = Array.from(pickedGroupIds).filter((gid) => !savedGroupIds.has(gid));
  const removedIds = Array.from(savedGroupIds).filter((gid) => !pickedGroupIds.has(gid));

  const setPicked = (gid: number, on: boolean) => {
    setPickedGroupIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(gid);
      else next.delete(gid);
      return next;
    });
  };

  const openPicker = () => {
    setPickerIds([]);
    setPickerText('');
    setPickerQuery('');
    setPickerOpen(true);
  };

  const confirmPicker = () => {
    const ids = pickerIds.map(Number).filter((n) => !Number.isNaN(n));
    setPickedGroupIds((prev) => {
      const next = new Set(prev);
      for (const gid of ids) next.add(gid);
      return next;
    });
    setPickerOpen(false);
  };

  const handleSaveGroups = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result: TeacherGroups = await putTeacherGroups(teacherId, Array.from(pickedGroupIds));
      const next = new Set(result.group_ids);
      setSavedGroupIds(next);
      setPickedGroupIds(new Set(next));
      setMessage({
        intent: 'success',
        text: `可教组别已保存（新增 ${addedIds.length} 个、移除 ${removedIds.length} 个）。被移除组的学生已立即离开该教师的名单，历史提交与成绩仍保留。`,
      });
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const keyword = rosterSearch.trim();
  const visibleRoster = keyword
    ? roster.filter((s) => s.username.includes(keyword) || s.display_name.includes(keyword))
    : roster;

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

  // ---------- 0.4.0 F3：代加 / 代删临时学生 ----------

  const bindTokens = bindText.split(ID_SEPARATOR).map((x) => x.trim()).filter(Boolean);
  const bindBadTokens = bindTokens.filter((x) => !/^\d+$/.test(x));
  const bindIds = useMemo(
    () => Array.from(new Set(bindTokens.filter((x) => /^\d+$/.test(x)).map(Number))).filter((n) => n > 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bindText],
  );

  const refreshRoster = () => getTeacherStudents(teacherId)
    .then((r) => setRoster(r.students))
    .catch((e) => setMessage({ intent: 'error', text: errMessage(e) }));

  const handleBindTemp = async () => {
    if (bindIds.length === 0) return;
    setBusy(true);
    setBindError(null);
    try {
      const result = await adminBindTempStudents(teacherId, bindIds);
      setBindOpen(false);
      setBindText('');
      setMessage(
        result.success_count === bindIds.length
          ? { intent: 'success', text: `已添加 ${result.success_count} 名临时学生。` }
          : {
            intent: 'success',
            text: `已添加 ${result.success_count} 名，另有 ${bindIds.length - result.success_count} 个 ID 已在名单里（未重复添加）。`,
          },
      );
      await refreshRoster();
    } catch (err) {
      setBindError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleUnbindTemp = async (s: RosterEntry) => {
    if (!window.confirm(`确定把「${s.display_name}」移出临时学生？其历史提交与成绩仍保留。`)) return;
    setBusy(true);
    setMessage(null);
    try {
      await adminUnbindTempStudents(teacherId, [s.id]);
      setMessage({ intent: 'success', text: `已移出临时学生「${s.display_name}」。` });
      await refreshRoster();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={() => navigate(0)} />;

  const pickerNameById = new Map(allGroups.map((g) => [String(g.id), g] as const));
  const pickerCandidates = pickerQuery.trim()
    ? assignableGroups.filter((g) => g.name.toLowerCase().includes(pickerQuery.trim().toLowerCase()))
    : assignableGroups;
  const pickerPicked = pickerIds
    .map((gid) => pickerNameById.get(gid))
    .filter((g): g is GroupItem => Boolean(g));

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
                已分配 {pickedGroupIds.size} / 共 {allGroups.length}
              </Badge>
            </span>
          }
          action={
            <Button
              appearance="primary"
              icon={busy ? <Spinner size="tiny" /> : <Save24Regular />}
              disabled={busy || (addedIds.length === 0 && removedIds.length === 0)}
              onClick={() => void handleSaveGroups()}
            >
              保存分配
            </Button>
          }
        />
        {addedIds.length + removedIds.length > 0 && (
          <Caption1 style={{ display: 'block', color: t.colorPaletteDarkOrangeForeground1 }}>
            待保存：新增 {addedIds.length} 个、移除 {removedIds.length} 个。
          </Caption1>
        )}
        {pickedGroups.length === 0 ? (
          <Caption1 style={{ display: 'block', marginTop: tokens.spacingVerticalM, color: t.colorNeutralForeground3 }}>
            {allGroups.length === 0
              ? '还没有任何组别，请先到「学生管理 → 分组管理」创建。'
              : '尚未分配任何可教组别，该教师目前没有可教学生。'}
          </Caption1>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalS, marginTop: tokens.spacingVerticalM }}>
            {pickedGroups.map((g) => (
              <span
                key={g.id}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: tokens.spacingHorizontalXS,
                  padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalXXS} ${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
                  border: `1px solid ${t.colorNeutralStroke2}`,
                  borderRadius: tokens.borderRadiusCircular,
                  backgroundColor: t.colorNeutralBackground2,
                }}
              >
                <Text size={300} weight="semibold">{g.name}</Text>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>{g.member_count} 人</Caption1>
                <Tooltip content="从可教组别移除" relationship="label">
                  <Button
                    size="small"
                    appearance="subtle"
                    icon={<Dismiss24Regular />}
                    aria-label={`移除组 ${g.name}`}
                    disabled={busy}
                    onClick={() => setPicked(g.id, false)}
                  />
                </Tooltip>
              </span>
            ))}
          </div>
        )}
        <div style={{ marginTop: tokens.spacingVerticalM }}>
          <Button
            appearance="secondary"
            icon={<Add24Regular />}
            disabled={busy || assignableGroups.length === 0}
            onClick={openPicker}
          >
            添加组
          </Button>
        </div>
      </Card>

      <Card size="medium">
        <CardHeader
          header={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
              <Text weight="semibold">学生名单</Text>
              <Badge appearance="outline" size="large">{roster.length} 人</Badge>
            </span>
          }
          action={(
            <Button
              appearance="secondary"
              icon={<Add24Regular />}
              disabled={busy}
              onClick={() => { setBindError(null); setBindOpen(true); }}
            >
              添加临时学生
            </Button>
          )}
        />
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          名单 = 可教组别成员 ∪ 临时添加；带角标的是临时添加的学生，可直接移出。
        </Caption1>
        <div style={{ marginTop: tokens.spacingVerticalS }}>
          <SearchBox placeholder="按学号或姓名筛选名单" value={rosterSearch} onChange={(_, d) => setRosterSearch(d.value)} style={{ maxWidth: '320px' }} />
        </div>
        <div style={{ marginTop: tokens.spacingVerticalM }}>
          {roster.length === 0 ? (
            <EmptyView title="该教师还没有可教学生" description="在上方分配可教组别后，组里的学生会自动出现在这里。" />
          ) : visibleRoster.length === 0 ? (
            <EmptyView title="名单里没有匹配的学生" description="换个关键词试试，或清空筛选查看全部。" />
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalXS }}>
              {visibleRoster.map((s) => (
                <Tooltip
                  key={s.id}
                  relationship="description"
                  content={`学号：${s.username}　来源：${s.source === 'manual' ? '临时添加' : (s.group_names.join('、') || '可教组别')}`}
                >
                  <span
                    style={{
                      position: 'relative',
                      display: 'inline-flex',
                      alignItems: 'center',
                      padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
                      border: `1px solid ${t.colorNeutralStroke2}`,
                      borderRadius: tokens.borderRadiusCircular,
                      backgroundColor: t.colorNeutralBackground2,
                    }}
                  >
                    <Text size={200}>{`${s.display_name}(ID:${String(s.id).padStart(2, '0')})`}</Text>
                    {s.source === 'manual' && (
                      <>
                        <span
                          aria-hidden
                          style={{
                            position: 'absolute',
                            top: 0,
                            right: 0,
                            width: '8px',
                            height: '8px',
                            borderRadius: '50%',
                            backgroundColor: t.colorBrandBackground2,
                            transform: 'translate(25%, -25%)',
                          }}
                        />
                        <Tooltip content="移出临时学生" relationship="label">
                          <Button
                            size="small"
                            appearance="subtle"
                            icon={<Dismiss24Regular />}
                            aria-label={`移出临时学生 ${s.display_name}`}
                            disabled={busy}
                            style={{ marginLeft: tokens.spacingHorizontalXS, color: t.colorNeutralForeground3 }}
                            onClick={() => void handleUnbindTemp(s)}
                          />
                        </Tooltip>
                      </>
                    )}
                  </span>
                </Tooltip>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* 添加可教组别：候选只列尚未分配的组，确认后加入页面工作副本，仍由「保存分配」全量提交 */}
      <Dialog open={pickerOpen} onOpenChange={(_, d) => setPickerOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>添加可教组别</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  勾选要新增的组，确认后这些组会进入页面待保存列表，仍需点「保存分配」才生效。
                </Caption1>
                {assignableGroups.length === 0 ? (
                  <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                    没有可添加的组别——其余组别都已是该教师的可教组别。
                  </Text>
                ) : (
                  <>
                    <Combobox
                      multiselect
                      appearance="outline"
                      placeholder="选择一个或多个组别"
                      value={pickerText}
                      selectedOptions={pickerIds}
                      disabled={busy}
                      style={{ width: '100%' }}
                      onChange={(e) => {
                        const v = e.target instanceof HTMLInputElement ? e.target.value : '';
                        setPickerText(v);
                        setPickerQuery(v);
                      }}
                      onOptionSelect={(_, d) => {
                        const ids = d.selectedOptions ?? [];
                        setPickerIds(ids);
                        setPickerQuery('');
                        setPickerText(ids.map((gid) => pickerNameById.get(gid)?.name ?? gid).join('、'));
                      }}
                    >
                      <Listbox>
                        {pickerCandidates.map((g) => (
                          <Option key={g.id} value={String(g.id)}>{`${g.name}（${g.member_count} 人）`}</Option>
                        ))}
                        {pickerCandidates.length === 0 && (
                          <Option value="__none__" disabled>没有匹配的组别</Option>
                        )}
                      </Listbox>
                    </Combobox>
                    {pickerPicked.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalXS }}>
                        <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                          已选 {pickerPicked.length} 个组别：
                        </Text>
                        {pickerPicked.map((g) => (
                          <Badge key={g.id} appearance="tint" size="large">{g.name}</Badge>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setPickerOpen(false)} disabled={busy}>取消</Button>
              <Button
                appearance="primary"
                icon={busy ? <Spinner size="tiny" /> : <Add24Regular />}
                disabled={busy || pickerIds.length === 0}
                onClick={confirmPicker}
              >
                确认添加
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      {/* 0.4.0 F3：代加临时学生——同款按 ID 输入弹窗；无效 id 整批 422，后端不回明细 */}
      <Dialog open={bindOpen} onOpenChange={(_, d) => { if (!busy) setBindOpen(d.open); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>添加临时学生</DialogTitle>
            <DialogContent>
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  用于转学生、旁听生这类还不在该教师可教组别里的情况。
                </Caption1>
                <Field label="学生 ID" required>
                  <Input
                    value={bindText}
                    onChange={(_, d) => setBindText(d.value)}
                    placeholder="例如：12, 34 56"
                    autoFocus
                  />
                </Field>
                <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                  {bindIds.length > 0
                    ? `识别到 ${bindIds.length} 个学生 ID。`
                    : '还没有识别到有效的数字 ID。'}
                  {bindBadTokens.length > 0 && ` 其中「${bindBadTokens.join('、')}」不是数字 ID，会被忽略。`}
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
                disabled={busy || bindIds.length === 0}
                onClick={() => void handleBindTemp()}
              >
                {busy ? '添加中…' : `确认添加${bindIds.length > 0 ? `（${bindIds.length} 个 ID）` : ''}`}
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
