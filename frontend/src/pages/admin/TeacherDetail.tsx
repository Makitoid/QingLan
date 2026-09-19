import { useTheme } from '../../appTheme';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Caption1,
  Card,
  CardHeader,
  Checkbox,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Option,
  SearchBox,
  Text,
  tokens,

} from '@fluentui/react-components';
import { Key24Regular, Save24Regular } from '@fluentui/react-icons';
import { getTeacherStudents, listStudents, listTeachers, putTeacherStudents, resetTeacherPassword } from '../../api';
import type { StudentItem } from '../../api/types';
import { LoadingView, ErrorView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';

export function AdminTeacherDetail() {
  const { id } = useParams();
  const t = useTheme();
  const navigate = useNavigate();
  const teacherId = Number(id);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown | null>(null);
  const [teacherName, setTeacherName] = useState('');
  const [students, setStudents] = useState<StudentItem[]>([]);
  const [boundIds, setBoundIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState('');
  const [pickedGroup, setPickedGroup] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);
  const [newPassword, setNewPassword] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([listTeachers(), listStudents(), getTeacherStudents(teacherId)])
      .then(([teachers, allStudents, bound]) => {
        if (cancelled) return;
        const teacher = teachers.find((x) => x.id === teacherId);
        setTeacherName(teacher ? `${teacher.display_name}（${teacher.username}）` : `#${teacherId}`);
        setStudents(allStudents);
        setBoundIds(new Set(bound.student_ids));
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

  const toggle = (studentId: number, checked: boolean) => {
    setBoundIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(studentId);
      else next.delete(studentId);
      return next;
    });
  };

  // 「按组添加」的选项由本页已加载的学生 groups 前端聚合，不需要额外接口。
  // 与下方复选框保持一致：已停用的学生不参与绑定，所以也不并入。
  const groupOptions = useMemo(() => {
    const byId = new Map<number, { id: number; name: string; studentIds: number[] }>();
    students.forEach((s) => {
      if (!s.is_active) return;
      s.groups.forEach((g) => {
        const found = byId.get(g.id);
        if (found) found.studentIds.push(s.id);
        else byId.set(g.id, { id: g.id, name: g.name, studentIds: [s.id] });
      });
    });
    return Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
  }, [students]);

  const handleAddByGroup = (groupId: string) => {
    const group = groupOptions.find((g) => String(g.id) === groupId);
    // 选完即回落到占位文案：这是一个「动作」，不是持久的筛选条件。
    setPickedGroup('');
    if (!group) return;
    const next = new Set(boundIds);
    const added = group.studentIds.filter((id) => !next.has(id));
    group.studentIds.forEach((id) => next.add(id));
    setBoundIds(next);
    setMessage({
      intent: 'success',
      text: `已并入分组「${group.name}」的 ${group.studentIds.length} 名学生，新增 ${added.length} 人，当前已选 ${next.size} 人；点「保存绑定」后生效。`,
    });
  };

  const handleSave = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await putTeacherStudents(teacherId, Array.from(boundIds));
      setMessage({ intent: 'success', text: '绑定关系已保存（全量覆盖）' });
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleResetPassword = async () => {
    if (!newPassword) {
      setMessage({ intent: 'error', text: '请输入新密码' });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await resetTeacherPassword(teacherId, newPassword);
      setNewPassword('');
      setMessage({ intent: 'success', text: '密码已重置' });
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={() => navigate(0)} />;

  const filtered = students.filter(
    (s) => !search.trim() || s.username.includes(search.trim()) || s.display_name.includes(search.trim()),
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate('/admin/teachers')}>← 返回教师管理</Button>
        </Caption1>
        <PageHeader title={<>教师详情 · {teacherName}</>} />
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
              <Key24Regular style={{ color: t.colorBrandForeground1 }} />
              <Text weight="semibold">重置密码</Text>
            </span>
          }
        />
        <div style={{ display: 'flex', gap: tokens.spacingHorizontalS, alignItems: 'flex-end' }}>
          <Field label="新密码" style={{ width: '280px' }}>
            <Input type="password" value={newPassword} onChange={(_, d) => setNewPassword(d.value)} />
          </Field>
          <Button appearance="primary" onClick={handleResetPassword} disabled={busy}>确认重置</Button>
        </div>
      </Card>

      <Card size="medium">
        <CardHeader
          header={<Text weight="semibold">绑定学生（已选 {boundIds.size} 人）</Text>}
          action={<Button appearance="primary" icon={<Save24Regular />} onClick={handleSave} disabled={busy}>保存绑定</Button>}
        />
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          场次受众 = 当前绑定的学生（动态计算）。保存为全量覆盖：未勾选的学生将被解绑。
        </Caption1>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            flexWrap: 'wrap',
            gap: tokens.spacingHorizontalS,
            marginTop: tokens.spacingVerticalS,
          }}
        >
          <SearchBox
            placeholder="按学号或姓名搜索"
            value={search}
            onChange={(_, d) => setSearch(d.value)}
            style={{ maxWidth: '320px' }}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalSNudge }}>
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>按组添加</Caption1>
            <Dropdown
              placeholder={groupOptions.length === 0 ? '学生还没有分组' : '选择一个分组，并入其成员'}
              value={groupOptions.find((g) => String(g.id) === pickedGroup)?.name}
              selectedOptions={pickedGroup ? [pickedGroup] : []}
              onOptionSelect={(_, d) => handleAddByGroup(String(d.optionValue ?? ''))}
              disabled={busy || groupOptions.length === 0}
              style={{ width: '240px' }}
            >
              {groupOptions.map((g) => (
                <Option key={g.id} value={String(g.id)}>
                  {`${g.name}（${g.studentIds.length} 人）`}
                </Option>
              ))}
            </Dropdown>
          </div>
        </div>
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          「按组添加」把该组学生并入当前选择（自动去重，已停用的学生不并入），仍需点「保存绑定」才生效。
        </Caption1>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: tokens.spacingVerticalS,
            marginTop: tokens.spacingVerticalM,
            maxHeight: '420px',
            overflowY: 'auto',
          }}
        >
          {filtered.map((s) => (
            <Checkbox
              key={s.id}
              checked={boundIds.has(s.id)}
              onChange={(_, d) => toggle(s.id, Boolean(d.checked))}
              disabled={!s.is_active}
              label={`${s.display_name}（${s.username}）${s.is_active ? '' : ' · 已停用'}`}
            />
          ))}
          {filtered.length === 0 && (
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>没有匹配的学生。请先到「学生管理」创建或导入学生。</Caption1>
          )}
        </div>
      </Card>
    </div>
  );
}
