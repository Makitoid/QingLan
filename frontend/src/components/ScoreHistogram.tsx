import { useTheme } from '../appTheme';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { tokens } from '@fluentui/react-components';
import type { HistogramBucket } from '../api/types';

export function ScoreHistogram({ data, height = 280 }: { data: HistogramBucket[]; height?: number }) {
  const t = useTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke={t.colorNeutralStroke2} vertical={false} />
        <XAxis dataKey="range" tick={{ fill: t.colorNeutralForeground3, fontSize: 12 }} stroke={t.colorNeutralStroke1} />
        <YAxis allowDecimals={false} tick={{ fill: t.colorNeutralForeground3, fontSize: 12 }} stroke={t.colorNeutralStroke1} />
        <Tooltip
          cursor={{ fill: t.colorNeutralBackground3 }}
          contentStyle={{
            backgroundColor: t.colorNeutralBackground1,
            border: `1px solid ${t.colorNeutralStroke1}`,
            borderRadius: tokens.borderRadiusMedium,
            color: t.colorNeutralForeground1,
          }}
          labelStyle={{ color: t.colorNeutralForeground1 }}
        />
        <Bar dataKey="count" name="人数" fill={t.colorBrandBackground} />
      </BarChart>
    </ResponsiveContainer>
  );
}
