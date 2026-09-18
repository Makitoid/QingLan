import { useTheme } from '../appTheme';
import { Badge, tokens } from '@fluentui/react-components';
import type { Verdict } from '../api/types';

interface VerdictColors {
  fg: string;
  bg: string;
  label: string;
}

function verdictColors(t: ReturnType<typeof useTheme>): Record<Verdict, VerdictColors> {
  return {
    AC: { fg: t.colorPaletteGreenForeground1, bg: t.colorPaletteGreenBackground2, label: 'AC · 答案正确' },
    WA: { fg: t.colorPaletteRedForeground1, bg: t.colorPaletteRedBackground2, label: 'WA · 答案错误' },
    TLE: { fg: t.colorPaletteDarkOrangeForeground1, bg: t.colorPaletteDarkOrangeBackground2, label: 'TLE · 超时' },
    MLE: { fg: t.colorPalettePurpleForeground2, bg: t.colorPalettePurpleBackground2, label: 'MLE · 内存超限' },
    RE: { fg: t.colorPaletteBrownForeground2, bg: t.colorPaletteBrownBackground2, label: 'RE · 运行错误' },
    CE: { fg: t.colorNeutralForeground2, bg: t.colorNeutralBackground4, label: 'CE · 编译错误' },
  };
}

export function VerdictBadge({ verdict, short }: { verdict: Verdict | null | undefined; short?: boolean }) {
  const t = useTheme();
  if (!verdict) return null;
  const c = verdictColors(t)[verdict];
  return (
    <Badge
      size="medium"
      style={{ color: c.fg, backgroundColor: c.bg, borderRadius: tokens.borderRadiusMedium, fontWeight: tokens.fontWeightSemibold }}
    >
      {short ? verdict : c.label}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const t = useTheme();
  if (status === 'pending' || status === 'judging') {
    return (
      <Badge size="medium" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4, borderRadius: tokens.borderRadiusMedium }}>
        {status === 'pending' ? '排队中' : '判题中'}
      </Badge>
    );
  }
  if (status === 'failed') {
    return (
      <Badge size="medium" style={{ color: t.colorPaletteRedForeground1, backgroundColor: t.colorPaletteRedBackground2, borderRadius: tokens.borderRadiusMedium }}>
        判题失败
      </Badge>
    );
  }
  return (
    <Badge size="medium" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2, borderRadius: tokens.borderRadiusMedium }}>
      已判题
    </Badge>
  );
}
