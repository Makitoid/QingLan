import { useTheme } from '../../appTheme';
import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Caption1,
  createTableColumn,
  DataGrid,
  DataGridBody,
  DataGridCell,
  DataGridHeader,
  DataGridHeaderCell,
  DataGridRow,
  Dropdown,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Text,
  tokens,
  type TableColumnDefinition,
} from '@fluentui/react-components';
import { ArrowSync24Regular, ChevronDown24Regular } from '@fluentui/react-icons';
import { listAuditLogs } from '../../api';
import type { AuditLogItem } from '../../api/types';
import { EmptyView, ErrorView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { fmtTimeWithSeconds } from '../../components/time';

/** 每页条数；`limit/offset` 分页，`total` 决定「加载更多」是否还可用（AU-05）。 */
const PAGE_SIZE = 50;

const ACTION_LABELS: Record<string, string> = {
  student_create_pw: '新建学生（发放初始密码）',
  student_reset_pw: '重置学生密码',
  student_batch_reset_pw: '批量重置学生密码',
  teacher_create_pw: '新建教师（发放初始密码）',
  teacher_reset_pw: '重置教师密码',
  user_change_password: '用户修改密码',
  user_is_active_change: '账号停用/启用',
  group_member_change: '组成员变更',
  group_update: '分组改名',
  group_delete: '删除分组',
  group_create: '新建分组',
  teacher_group_assign: '教师可教组别分配',
  teacher_student_bind: '教师拉入学生',
  teacher_student_unbind: '教师移出学生',
  student_import: '批量导入学生',
  score_manual_adjust: '成绩手动调分',
};

const TARGET_LABELS: Record<string, string> = {
  user: '账号',
  student: '学生',
  teacher: '教师',
  group: '分组',
  submission: '提交',
  problem: '题目',
  assignment: '场次',
};

/** 下拉候选：《修改意见》附录 A 的必备动作 + 本次已加载数据里出现过的动作（后端新增也不会漏）。 */
function optionValues(known: Record<string, string>, seen: string[]): string[] {
  return Array.from(new Set([...Object.keys(known), ...seen])).sort();
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '空';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) {
    const parts = value.map((v) => formatValue(v));
    if (parts.length === 0) return '无';
    if (parts.length > 8) return `${parts.slice(0, 8).join('、')}…（共 ${parts.length} 项）`;
    return parts.join('、');
  }
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isInteger(value)) return String(value);
  return String(value);
}

/** 审计 `detail` 里常见键名的中文对照；未知键原样显示，后端加字段不至于显示成空白。 */
const DETAIL_KEY_LABELS: Record<string, string> = {
  mode: '模式',
  count: '人数',
  forced: '强制改密',
  is_active: '启用状态',
  active: '启用状态',
  name: '名称',
  old_name: '原名称',
  new_name: '新名称',
  username: '学号/工号',
  display_name: '姓名',
  student_id: '学生 ID',
  student_ids: '学生 ID',
  teacher_id: '教师 ID',
  teacher_ids: '教师 ID',
  group_id: '分组 ID',
  group_ids: '分组 ID',
  added_group_ids: '新增分组',
  removed_group_ids: '移除分组',
  added: '新增',
  removed: '移除',
  from_group: '原分组',
  to_group: '新分组',
  assignment_id: '场次 ID',
  problem_id: '题目 ID',
  submission_id: '提交 ID',
  manual_score: '手动分',
  old_manual_score: '原手动分',
  new_manual_score: '新手动分',
  role: '角色',
  reason: '原因',
  file: '文件名',
  success_count: '成功数',
  failure_count: '失败数',
};

/** `detail` 的「人话」摘要：键名翻译成中文、值按类型展开，不贴原始 JSON 字符串。 */
function summarizeDetail(detail: Record<string, unknown> | null): string {
  if (!detail) return '—';
  const entries = Object.entries(detail);
  if (entries.length === 0) return '—';
  return entries
    .map(([key, value]) => {
      let shown = formatValue(value);
      if (key === 'mode') shown = value === 'unified' ? '统一初始密码' : value === 'random' ? '逐生随机' : shown;
      return `${DETAIL_KEY_LABELS[key] ?? key}：${shown}`;
    })
    .join('；');
}
const columns: TableColumnDefinition<AuditLogItem>[] = [
  createTableColumn({ columnId: 'created_at', renderHeaderCell: () => '时间' }),
  createTableColumn({ columnId: 'actor', renderHeaderCell: () => '操作者' }),
  createTableColumn({ columnId: 'actor_id', renderHeaderCell: () => '操作者 ID' }),
  createTableColumn({ columnId: 'action', renderHeaderCell: () => '动作' }),
  createTableColumn({ columnId: 'target_type', renderHeaderCell: () => '对象类型' }),
  createTableColumn({ columnId: 'target_id', renderHeaderCell: () => '对象 ID' }),
  createTableColumn({ columnId: 'detail', renderHeaderCell: () => '详情' }),
];

/**
 * AU-06：管理员审计日志页。只读——后端不提供任何修改/删除审计的接口，
 * 这里也不给任何写入口（AU-05「只追加」）。
 */
export function AuditLogPage() {
  const t = useTheme();
  const [action, setAction] = useState('');
  const [targetType, setTargetType] = useState('');
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setMoreError(null);
    listAuditLogs({ action: action || undefined, targetType: targetType || undefined, limit: PAGE_SIZE, offset: 0 })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
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
  }, [action, targetType, tick]);

  const loadMore = async () => {
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await listAuditLogs({
        action: action || undefined,
        targetType: targetType || undefined,
        limit: PAGE_SIZE,
        offset: items.length,
      });
      // 只追加：后端按 created_at 倒序，翻页期间新写入会让边界条目重复一次，按 id 去重。
      setItems((prev) => {
        const seen = new Set(prev.map((x) => x.id));
        return [...prev, ...page.items.filter((x) => !seen.has(x.id))];
      });
      setTotal(page.total);
    } catch (e) {
      setMoreError(errMessage(e));
    } finally {
      setLoadingMore(false);
    }
  };

  const seenActions = items.map((x) => x.action);
  const seenTargets = items.map((x) => x.target_type);
  const hasMore = items.length < total;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
      <PageHeader
        title="审计日志"
        subtitle="密码重置、账号启停、分组与教师可教组别变更、导入与手动调分的关键操作记录；只读、按时间倒序。"
        actions={
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXXS }}>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>动作</Caption1>
              <Dropdown
                placeholder="全部动作"
                value={action ? (ACTION_LABELS[action] ?? action) : ''}
                selectedOptions={action ? [action] : []}
                onOptionSelect={(_, d) => setAction(String(d.optionValue ?? ''))}
                disabled={loading}
                style={{ width: '240px' }}
              >
                <Option value="" text="全部动作">
                  全部动作
                </Option>
                {optionValues(ACTION_LABELS, seenActions).map((key) => (
                  <Option key={key} value={key} text={ACTION_LABELS[key] ?? key}>
                    {ACTION_LABELS[key] ?? key}
                  </Option>
                ))}
              </Dropdown>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXXS }}>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>对象类型</Caption1>
              <Dropdown
                placeholder="全部类型"
                value={targetType ? (TARGET_LABELS[targetType] ?? targetType) : ''}
                selectedOptions={targetType ? [targetType] : []}
                onOptionSelect={(_, d) => setTargetType(String(d.optionValue ?? ''))}
                disabled={loading}
                style={{ width: '160px' }}
              >
                <Option value="" text="全部类型">
                  全部类型
                </Option>
                {optionValues(TARGET_LABELS, seenTargets).map((key) => (
                  <Option key={key} value={key} text={TARGET_LABELS[key] ?? key}>
                    {TARGET_LABELS[key] ?? key}
                  </Option>
                ))}
              </Dropdown>
            </div>
            <Button
              appearance="secondary"
              icon={loading ? <Spinner size="tiny" /> : <ArrowSync24Regular />}
              disabled={loading}
              onClick={() => setTick((x) => x + 1)}
              style={{ alignSelf: 'flex-end' }}
            >
              刷新
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorView error={error} onRetry={() => setTick((x) => x + 1)} />
      ) : loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: tokens.spacingVerticalXXL }}>
          <Spinner label="加载中…" />
        </div>
      ) : items.length === 0 ? (
        <EmptyView
          title="没有符合条件的审计记录"
          description={action || targetType ? '换个筛选条件试试，或选择「全部」查看完整记录。' : '系统里还没有产生任何被审计的操作。'}
        />
      ) : (
        <>
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            共 {total} 条，已加载 {items.length} 条。
          </Caption1>

          {moreError && (
            <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
              <MessageBarBody>{moreError}</MessageBarBody>
            </MessageBar>
          )}

          <DataGrid items={items} columns={columns} focusMode="cell" resizableColumns getRowId={(item) => item.id}>
            <DataGridHeader>
              <DataGridRow>
                {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
              </DataGridRow>
            </DataGridHeader>
            <DataGridBody<AuditLogItem>>
              {({ item, rowId }) => (
                <DataGridRow<AuditLogItem> key={rowId}>
                  {({ columnId }) => (
                    <DataGridCell>
                      {columnId === 'created_at' && (
                        <Caption1 style={{ color: t.colorNeutralForeground3, whiteSpace: 'nowrap' }}>
                          {fmtTimeWithSeconds(item.created_at)}
                        </Caption1>
                      )}
                      {columnId === 'actor' && (
                        <Text size={300}>{item.actor_name || '（已删除账号）'}</Text>
                      )}
                      {columnId === 'actor_id' && (item.actor_id === null ? '—' : item.actor_id)}
                      {columnId === 'action' && (
                        <Badge appearance="tint" size="large" style={{ alignSelf: 'flex-start' }}>
                          {ACTION_LABELS[item.action] ?? item.action}
                        </Badge>
                      )}
                      {columnId === 'target_type' && (
                        TARGET_LABELS[item.target_type] ?? item.target_type
                      )}
                      {columnId === 'target_id' && (item.target_id === null ? '—' : item.target_id)}
                      {columnId === 'detail' && (
                        <Text size={200} style={{ color: t.colorNeutralForeground2, whiteSpace: 'pre-wrap' }}>
                          {summarizeDetail(item.detail)}
                        </Text>
                      )}
                    </DataGridCell>
                  )}
                </DataGridRow>
              )}
            </DataGridBody>
          </DataGrid>

          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
            <Button
              appearance="secondary"
              icon={loadingMore ? <Spinner size="tiny" /> : <ChevronDown24Regular />}
              disabled={loadingMore || !hasMore}
              onClick={() => void loadMore()}
            >
              {loadingMore ? '加载中…' : hasMore ? `加载更多（${Math.min(PAGE_SIZE, total - items.length)} 条）` : '已加载全部'}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
