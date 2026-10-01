import { useTheme } from '../appTheme';
import { Badge, Caption1, Divider, Text, tokens } from '@fluentui/react-components';
import type { TestCase } from '../api/types';

/** 输入/输出代码块，样式与学生端题面页一致。 */
export function PreBlock({ text }: { text: string }) {
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

/**
 * 测试点用例区块（0.4.1 F5）：教师端「查看原题」处展示题目设定的**全部**测试点，
 * 不再只有样例——判分对不对、权重怎么分，教师在看题时就能核对。
 *
 * 学生端不用它：隐藏测试点的输入输出不能下发给考生。
 */
export function ProblemCases({ cases }: { cases: TestCase[] }) {
  const t = useTheme();
  const sorted = [...cases].sort((a, b) => a.seq - b.seq);
  const sampleCount = sorted.filter((c) => c.is_sample).length;
  const totalWeight = sorted.reduce((sum, c) => sum + c.weight, 0);

  return (
    <>
      <Divider />
      <div style={{ display: 'flex', alignItems: 'baseline', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' }}>
        <Text weight="semibold">测试点用例（{sorted.length}）</Text>
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          {sorted.length === 0
            ? '尚未设定测试点，提交后不会有判题结果。'
            : `样例 ${sampleCount} · 隐藏 ${sorted.length - sampleCount} · 权重合计 ${totalWeight}`}
        </Caption1>
      </div>

      {sorted.map((c) => (
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
            <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalXS, marginBottom: tokens.spacingVerticalXXS }}>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>#{c.seq} 输入</Caption1>
              <Badge appearance={c.is_sample ? 'tint' : 'outline'} size="small">
                {c.is_sample ? '样例' : '隐藏'}
              </Badge>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>权重 {c.weight}</Caption1>
            </div>
            <PreBlock text={c.input} />
          </div>
          <div>
            <Caption1 style={{ display: 'block', color: t.colorNeutralForeground3, marginBottom: tokens.spacingVerticalXXS }}>
              #{c.seq} 期望输出
            </Caption1>
            <PreBlock text={c.expected} />
          </div>
        </div>
      ))}
    </>
  );
}
