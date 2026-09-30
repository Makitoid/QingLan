import { useTheme } from '../../appTheme';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  Card,
  Divider,
  Text,
  tokens,
} from '@fluentui/react-components';
import { Edit24Regular } from '@fluentui/react-icons';
import { getTeacherProblem } from '../../api';
import type { CompareMode, ProblemDetail } from '../../api/types';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { MarkdownBody } from '../../components/Markdown';
import { useRouteFrom } from '../../components/routeFrom';

const COMPARE_LABELS: Record<CompareMode, string> = { exact: '精确', trim: '忽略空白', float: '浮点容差' };

/** 样例输入/输出块，样式与学生端题面页一致。 */
function PreBlock({ text }: { text: string }) {
  const t = useTheme();
  return (
    <pre
      style={{
        margin: 0,
        padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
        backgroundColor: t.colorSubtleBackground,
        border: `1px solid ${t.colorNeutralStroke2}`,
        borderRadius: tokens.borderRadiusMedium,
        fontFamily: "'Cascadia Code', Consolas, 'Courier New', monospace",
        fontSize: tokens.fontSizeBase200,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
      }}
    >
      {text}
    </pre>
  );
}

/** 题目只读查看页：从统计/判分上下文点题目时进这里，编辑动作在页头。 */
export function TeacherProblemView() {
  const { id } = useParams();
  const problemId = Number(id);
  const t = useTheme();
  const navigate = useNavigate();
  const { from, backTo } = useRouteFrom('/teacher/problems');
  const { data, error, loading, reload } = useAsync<ProblemDetail>(
    () => getTeacherProblem(problemId),
    [problemId],
  );

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;
  if (!data) return null;

  const group = (data.group_name ?? '').trim();
  const samples = data.cases.filter((c) => c.is_sample);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <PageHeader
        title={data.title}
        subtitle={<>题目 #{data.id}</>}
        actions={
          <>
            <Button
              appearance="primary"
              icon={<Edit24Regular />}
              onClick={() => navigate(`/teacher/problems/${data.id}${from ? `?from=${encodeURIComponent(from)}` : ''}`)}
            >
              编辑题目
            </Button>
            <Button appearance="subtle" onClick={() => navigate(backTo)}>
              ← 返回
            </Button>
          </>
        }
      />

      <Card size="medium">
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' }}>
          {group ? (
            <Badge appearance="tint" size="large">{group}</Badge>
          ) : (
            <Badge appearance="outline" size="large">未分组</Badge>
          )}
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            时间限制 {data.time_limit_ms} ms · 内存限制 {data.memory_limit_mb} MB · 比对模式{' '}
            {COMPARE_LABELS[data.compare_mode]}
            {data.compare_mode === 'float' && data.float_eps !== null ? `（容差 ${data.float_eps}）` : ''}
          </Caption1>
        </div>

        <Divider />
        <Text weight="semibold">题目描述</Text>
        <MarkdownBody>{data.description}</MarkdownBody>
        <Divider />
        <Text weight="semibold">输入格式</Text>
        <MarkdownBody>{data.input_format}</MarkdownBody>
        <Text weight="semibold">输出格式</Text>
        <MarkdownBody>{data.output_format}</MarkdownBody>

        {samples.length > 0 && <Divider />}
        {samples.map((c) => (
          <div
            key={c.id}
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: tokens.spacingHorizontalM,
              marginTop: tokens.spacingVerticalS,
            }}
          >
            <div>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>样例 {c.seq} 输入</Caption1>
              <PreBlock text={c.input} />
            </div>
            <div>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>样例 {c.seq} 输出</Caption1>
              <PreBlock text={c.expected} />
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}
