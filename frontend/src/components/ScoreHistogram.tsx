import { useState } from 'react';
import { useTheme } from '../appTheme';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts';
import { Button, Tooltip, tokens } from '@fluentui/react-components';
import { DataBarVertical24Regular, DataLine24Regular } from '@fluentui/react-icons';
import type { HistogramBucket } from '../api/types';

/** 柱形 / 折线两种画法（0.4.1 F7）：柱形看各档人数，折线看分布走势。 */
type Shape = 'column' | 'line';

const SHAPES: { value: Shape; label: string; icon: JSX.Element }[] = [
  { value: 'column', label: '柱形图', icon: <DataBarVertical24Regular /> },
  { value: 'line', label: '折线图', icon: <DataLine24Regular /> },
];

export function ScoreHistogram({ data, height = 280 }: { data: HistogramBucket[]; height?: number }) {
  const t = useTheme();
  const [shape, setShape] = useState<Shape>('column');

  const axisTick = { fill: t.colorNeutralForeground3, fontSize: 12 };
  const chartTooltip = (
    <ChartTooltip
      contentStyle={{
        backgroundColor: t.colorNeutralBackground1,
        border: `1px solid ${t.colorNeutralStroke1}`,
        borderRadius: tokens.borderRadiusMedium,
        color: t.colorNeutralForeground1,
      }}
      labelStyle={{ color: t.colorNeutralForeground1 }}
    />
  );

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

      <ResponsiveContainer width="100%" height={height}>
        {shape === 'column' ? (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={t.colorNeutralStroke2} vertical={false} />
            <XAxis dataKey="range" tick={axisTick} stroke={t.colorNeutralStroke1} />
            <YAxis allowDecimals={false} tick={axisTick} stroke={t.colorNeutralStroke1} />
            {chartTooltip}
            <Bar dataKey="count" name="人数" fill={t.colorBrandBackground} />
          </BarChart>
        ) : (
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={t.colorNeutralStroke2} vertical={false} />
            <XAxis dataKey="range" tick={axisTick} stroke={t.colorNeutralStroke1} />
            <YAxis allowDecimals={false} tick={axisTick} stroke={t.colorNeutralStroke1} />
            {chartTooltip}
            <Line
              type="monotone"
              dataKey="count"
              name="人数"
              stroke={t.colorBrandBackground}
              strokeWidth={2}
              dot={{ r: 3, fill: t.colorBrandBackground }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
