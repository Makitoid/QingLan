import { useTheme } from '../../appTheme';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Badge,
  Caption1,
  Card,
  CardHeader,
  createTableColumn, DataGrid,
  DataGridBody,
  DataGridCell,
  DataGridHeader,
  DataGridHeaderCell,
  DataGridRow,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { getStudentSubmission } from '../../api';
import type { StudentSubmissionDetail, StudentSubmissionResultRow } from '../../api/types';
import { ErrorView, errMessage } from '../../components/StateViews';
import { PageHeader } from '../../components/PageHeader';
import { fmtTimeWithSeconds } from '../../components/time';
import { fmtScore } from '../../components/score';
import { CodeEditor } from '../../components/CodeEditor';
import { VerdictBadge } from '../../components/VerdictBadge';

const resultColumns: TableColumnDefinition<StudentSubmissionResultRow>[] = [
  createTableColumn({ columnId: 'seq', renderHeaderCell: () => '测试点' }),
  createTableColumn({ columnId: 'kind', renderHeaderCell: () => '类型' }),
  createTableColumn({ columnId: 'verdict', renderHeaderCell: () => '判定' }),
  createTableColumn({ columnId: 'time', renderHeaderCell: () => '耗时' }),
  createTableColumn({ columnId: 'score', renderHeaderCell: () => '得分' }),
];

function isJudging(status?: string) {
  return status === 'pending' || status === 'judging';
}

export function StudentSubmissionPage() {
  const { sid } = useParams();
  const t = useTheme();
  const submissionId = Number(sid);
  const [data, setData] = useState<StudentSubmissionDetail | null>(null);
  const [error, setError] = useState<unknown | null>(null);
  const timerRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await getStudentSubmission(submissionId);
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError(e);
      return null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submissionId]);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      const d = await load();
      if (cancelled) return;
      if (!d || isJudging(d.status)) {
        timerRef.current = window.setTimeout(tick, 2000);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [load]);

  if (error && !data) return <ErrorView error={error} onRetry={() => void load()} />;

  if (!data) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: tokens.spacingVerticalXXL }}>
        <Spinner label="加载中…" />
      </div>
    );
  }

  const judging = isJudging(data.status);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <PageHeader
        title={<>提交 #{data.id}</>}
        subtitle={<>提交时间：{fmtTimeWithSeconds(data.submitted_at)}</>}
        actions={
          judging ? (
            <Spinner size="tiny" label={data.status === 'pending' ? '排队中…' : '判题中…'} />
          ) : (
            <>
              {data.status_text && !data.verdict && (
                <Badge size="medium" style={{ color: t.colorNeutralForeground2, backgroundColor: t.colorNeutralBackground4 }}>
                  {data.status_text}
                </Badge>
              )}
              {data.verdict && <VerdictBadge verdict={data.verdict} />}
              {data.status === 'failed' && (
                <Badge size="medium" style={{ color: t.colorPaletteRedForeground1, backgroundColor: t.colorPaletteRedBackground2 }}>
                  判题失败
                </Badge>
              )}
              {data.score !== null && data.score !== undefined && (
                <Text weight="semibold" style={{ color: t.colorBrandForeground1 }}>得分：{fmtScore(data.score)}</Text>
              )}
            </>
          )
        }
      />

      {data.status_text && !data.verdict && !judging && (
        <MessageBar intent="info" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>测试模式下判定详情不可见，教师放出成绩后即可查看。</MessageBarBody>
        </MessageBar>
      )}

      {error !== null && judging && (
        <MessageBar intent="warning" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>刷新判定结果时出错：{errMessage(error)}，将继续重试。</MessageBarBody>
        </MessageBar>
      )}

      {data.code_text !== undefined && (
        <Card size="medium">
          <CardHeader header={<Text weight="semibold">提交的代码</Text>} />
          <CodeEditor value={data.code_text} readOnly height="320px" />
        </Card>
      )}

      {data.results && data.results.length > 0 && (
        <Card size="medium">
          <CardHeader header={<Text weight="semibold">逐测试点判定</Text>} />
          <DataGrid items={data.results} columns={resultColumns} focusMode="cell">
            <DataGridHeader>
              <DataGridRow>
                {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
              </DataGridRow>
            </DataGridHeader>
            <DataGridBody<StudentSubmissionResultRow>>
              {({ item, rowId }) => (
                <DataGridRow<StudentSubmissionResultRow> key={rowId}>
                  {({ columnId }) => (
                    <DataGridCell>
                      {columnId === 'seq' && item.seq}
                      {columnId === 'kind' && (
                        <Caption1 style={{ color: t.colorNeutralForeground3 }}>{item.is_sample ? '样例' : '隐藏'}</Caption1>
                      )}
                      {columnId === 'verdict' && <VerdictBadge verdict={item.verdict} short />}
                      {columnId === 'time' && `${item.time_ms} ms`}
                      {columnId === 'score' && fmtScore(item.score)}
                    </DataGridCell>
                  )}
                </DataGridRow>
              )}
            </DataGridBody>
          </DataGrid>
        </Card>
      )}

      <Caption1>
        <Link to=".." style={{ color: t.colorBrandForeground1 }}>← 返回题目</Link>
      </Caption1>
    </div>
  );
}
