import { useTheme } from '../appTheme';
import type { KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Caption1,
  Card,
  Spinner,
  Text,
  tokens,
} from '@fluentui/react-components';
import { getAssignmentStudentProblems } from '../api';
import type { StudentProblemScoreRow } from '../api/types';
import { useAsync } from './useAsync';
import { ErrorView } from './StateViews';
import { VerdictBadge } from './VerdictBadge';

interface ProblemSwitchNavProps {
  assignmentId: number;
  studentId: number;
  /** 当前判分页对应的题目 id，命中项高亮。 */
  currentProblemId: number;
}

/**
 * 0.4.0 F5：判分页左侧题目切换栏。
 * 每项「第 N 题 · 标题」+ 状态徽标（未交 / 最新判定 / 已调分）；
 * 点击跳到该题最新提交的判分页（同页换 sid），未交项不可点。
 */
export function ProblemSwitchNav({ assignmentId, studentId, currentProblemId }: ProblemSwitchNavProps) {
  const t = useTheme();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync<StudentProblemScoreRow[]>(
    () => getAssignmentStudentProblems(assignmentId, studentId),
    [assignmentId, studentId],
  );

  const goSubmission = (submissionId: number | null) => {
    if (submissionId !== null) navigate(`/teacher/submissions/${submissionId}`);
  };

  return (
    <Card size="small" style={{ width: '272px', flexShrink: 0, alignSelf: 'flex-start' }}>
      <Text weight="semibold" size={300} style={{ display: 'block', marginBottom: tokens.spacingVerticalS }}>
        题目
      </Text>
      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: tokens.spacingVerticalL }}>
          <Spinner size="tiny" label="加载题单…" labelPosition="after" />
        </div>
      ) : error ? (
        <ErrorView error={error} onRetry={reload} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalSNudge }}>
          {(data ?? []).map((row) => {
            const current = row.problem_id === currentProblemId;
            const clickable = row.latest_submission_id !== null;
            const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                goSubmission(row.latest_submission_id);
              }
            };
            return (
              <div
                key={row.problem_id}
                role={clickable ? 'button' : undefined}
                tabIndex={clickable ? 0 : undefined}
                onClick={() => goSubmission(row.latest_submission_id)}
                onKeyDown={clickable ? onKey : undefined}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: tokens.spacingHorizontalS,
                  padding: `${tokens.spacingVerticalSNudge} ${tokens.spacingHorizontalSNudge}`,
                  borderRadius: tokens.borderRadiusMedium,
                  backgroundColor: current ? t.colorBrandBackground2 : 'transparent',
                  border: `1px solid ${current ? t.colorBrandStroke1 : 'transparent'}`,
                  cursor: clickable ? 'pointer' : 'default',
                }}
              >
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    color: clickable ? t.colorNeutralForeground1 : t.colorNeutralForeground4,
                  }}
                >
                  第 {row.seq} 题 · {row.title || '—'}
                </span>
                {row.latest_submission_id === null ? (
                  <Badge size="small" style={{ color: t.colorNeutralForeground4, backgroundColor: t.colorNeutralBackground4 }}>
                    未交
                  </Badge>
                ) : (
                  <>
                    <VerdictBadge verdict={row.verdict} short />
                    {row.manual_score !== null && (
                      <Badge
                        size="small"
                        style={{ color: t.colorPaletteDarkOrangeForeground1, backgroundColor: t.colorPaletteDarkOrangeBackground2 }}
                      >
                        已调分
                      </Badge>
                    )}
                  </>
                )}
              </div>
            );
          })}
          {data && data.length === 0 && (
            <Caption1 style={{ color: t.colorNeutralForeground3 }}>题单为空。</Caption1>
          )}
        </div>
      )}
    </Card>
  );
}
