import { useState } from 'react';
import { useTheme } from '../appTheme';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts';
import { Button, Tooltip, tokens } from '@fluentui/react-components';
import { DataBarHorizontal24Regular, DataBarVertical24Regular } from '@fluentui/react-icons';
import type { HistogramBucket } from '../api/types';

/** 柱形（竖）/ 条形（横）两种形状，分数段文案长时用条形更好读（0.4.1 F7）。 */
type Shape = 'column' | 'bar';

/** 条形模式下每档占的行高；档数多时按它把容器撑高，避免标签挤成一团。 */
const BAR_ROW_HEIGHT = 36;

const SHAPES: { value: Shape; label: string; icon: JSX.Element }[] = [
  { value: 'column', label: '柱形图', icon: <DataBarVertical24Regular /> },
  { value: 'bar', label: '条形图', icon: <DataBarHorizontal24Regular /> },
];

export function ScoreHistogram({ data, height = 280 }: { data: HistogramBucket[]; height?: number }) {
  const t = useTheme();
  const [shape, setShape] = useState<Shape>('column');
  const chartHeight = shape === 'bar' ? Math.max(height, data.length * BAR_ROW_HEIGHT + 24) : height;

  const axisTick = { fill: t.colorNeutralForeground3, fontSize: 12 };
  const tooltipContentStyle = {
    backgroundColor: t.colorNeutralBackground1,
    border: `1px solid ${t.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    color: t.colorNeutralForeground1,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
      <div
        role="group"
        aria-label="图表形状"
        style={{
          display: 'flex',
          alignSelf: 'flex-end',
          gap: tokens.spacingHorizontalXXS,
          padding: tokens.spacingHorizontalXXS,
          backgroundColor: t.colorNeutralBackground3,
          borderRadius: tokens.borderRadiusMedium,
        }}
      >
        {SHAPES.map((option) => (
          <Tooltip key={option.value} content={option.label} relationship="label">
            <Button
              size="small"
              appearance={shape === option.value ? 'primary' : 'subtle'}
              icon={option.icon}
              aria-label={option.label}
              aria-pressed={shape === option.value}
              onClick={() => setShape(option.value)}
            />
          </Tooltip>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={chartHeight}>
        {shape === 'column' ? (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={t.colorNeutralStroke2} vertical={false} />
            <XAxis dataKey="range" tick={axisTick} stroke={t.colorNeutralStroke1} />
            <YAxis allowDecimals={false} tick={axisTick} stroke={t.colorNeutralStroke1} />
            <ChartTooltip
              cursor={{ fill: t.colorNeutralBackground3 }}
              contentStyle={tooltipContentStyle}
              labelStyle={{ color: t.colorNeutralForeground1 }}
            />
            <Bar dataKey="count" name="人数" fill={t.colorBrandBackground} radius={[4, 4, 0, 0]} />
          </BarChart>
        ) : (
          <BarChart data={data} layout="vertical" margin={{ left: 16, right: 24 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={t.colorNeutralStroke2} horizontal={false} />
            <XAxis type="number" allowDecimals={false} tick={axisTick} stroke={t.colorNeutralStroke1} />
            <YAxis type="category" dataKey="range" width={80} tick={axisTick} stroke={t.colorNeutralStroke1} />
            <ChartTooltip
              cursor={{ fill: t.colorNeutralBackground3 }}
              contentStyle={tooltipContentStyle}
              labelStyle={{ color: t.colorNeutralForeground1 }}
            />
            <Bar dataKey="count" name="人数" fill={t.colorBrandBackground} radius={[0, 4, 4, 0]} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
