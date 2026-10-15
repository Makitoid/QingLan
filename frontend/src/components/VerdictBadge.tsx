import { useTheme } from '../appTheme';
import { Badge, tokens } from '@fluentui/react-components';
import type { AssignmentState, Verdict } from '../api/types';

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
      size="large"
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
      <Badge size="large" style={{ color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4, borderRadius: tokens.borderRadiusMedium }}>
        {status === 'pending' ? '排队中' : '判题中'}
      </Badge>
    );
  }
  if (status === 'failed') {
    return (
      <Badge size="large" style={{ color: t.colorPaletteRedForeground1, backgroundColor: t.colorPaletteRedBackground2, borderRadius: tokens.borderRadiusMedium }}>
        判题失败
      </Badge>
    );
  }
  return (
    <Badge size="large" style={{ color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2, borderRadius: tokens.borderRadiusMedium }}>
      已判题
    </Badge>
  );
}

/** 场次状态的中文与色调；'retry' 是 0.4.1 F9 的「打回重做」，红底、单独一档。 */
const ASSIGNMENT_STATE: Record<AssignmentState, { label: string; tone: 'green' | 'red' | 'neutral' }> = {
  ongoing: { label: '进行中', tone: 'green' },
  ending: { label: '即将结束', tone: 'red' },
  ended: { label: '已结束', tone: 'neutral' },
  retry: { label: '打回重做', tone: 'red' },
};

/**
 * 学生端的场次状态徽标。列表与详情都用它——状态取值从 3 个变 4 个之后，
 * 两处各写一条三元链迟早会漏掉一支。
 */
export function AssignmentStateBadge({ state }: { state: AssignmentState }) {
  const t = useTheme();
  const meta = ASSIGNMENT_STATE[state] ?? ASSIGNMENT_STATE.ongoing;
  const palette = meta.tone === 'green'
    ? { color: t.colorPaletteGreenForeground1, backgroundColor: t.colorPaletteGreenBackground2 }
    : meta.tone === 'red'
      ? { color: t.colorPaletteRedForeground1, backgroundColor: t.colorPaletteRedBackground2 }
      : { color: t.colorNeutralForeground3, backgroundColor: t.colorNeutralBackground4 };
  return (
    <Badge className="ql-badge-status" size="large" style={{ ...palette, borderRadius: tokens.borderRadiusMedium }}>
      {meta.label}
    </Badge>
  );
}
