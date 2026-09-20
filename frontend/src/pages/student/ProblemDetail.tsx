import { useTheme } from '../../appTheme';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Caption1,
  Card,
  CardHeader,
  createTableColumn, DataGrid,
  DataGridBody,
  DataGridCell,
  DataGridHeader,
  DataGridHeaderCell,
  DataGridRow,
  Divider,
  MessageBar,
  MessageBarBody,
  Text,
  tokens,

  type TableColumnDefinition,
} from '@fluentui/react-components';
import { Send24Regular } from '@fluentui/react-icons';
import { createSubmission, getStudentProblem } from '../../api';
import type { StudentProblemDetail, StudentSubmissionSummary } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { useAsync } from '../../components/useAsync';
import { LoadingView, ErrorView, errMessage } from '../../components/StateViews';
import { fmtTime } from '../../components/time';
import { fmtScore } from '../../components/score';
import { CodeEditor } from '../../components/CodeEditor';
import { MarkdownBody } from '../../components/Markdown';
import { VerdictBadge } from '../../components/VerdictBadge';

const historyColumns: TableColumnDefinition<StudentSubmissionSummary>[] = [
  createTableColumn({ columnId: 'id', renderHeaderCell: () => '编号' }),
  createTableColumn({ columnId: 'submitted_at', renderHeaderCell: () => '提交时间' }),
  createTableColumn({ columnId: 'result', renderHeaderCell: () => '结果' }),
];

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

export function StudentProblemPage() {
  const { id, pid } = useParams();
  const navigate = useNavigate();
  const t = useTheme();
  const assignmentId = Number(id);
  const problemId = Number(pid);
  const { data, error, loading, reload } = useAsync<StudentProblemDetail>(
    () => getStudentProblem(assignmentId, problemId),
    [assignmentId, problemId],
  );
  const [code, setCode] = useState('#include <stdio.h>\n\nint main() {\n    \n    return 0;\n}\n');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!code.trim()) {
      setSubmitError('代码不能为空');
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const resp = await createSubmission(assignmentId, problemId, code);
      navigate(`/student/submissions/${resp.id}`);
    } catch (err) {
      setSubmitError(errMessage(err));
      setSubmitting(false);
    }
  };

  if (loading) return <LoadingView />;
  if (error) return <ErrorView error={error} onRetry={reload} />;
  if (!data) return null;

  const p = data;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Caption1>
          <Button appearance="subtle" size="small" onClick={() => navigate(`/student/assignments/${assignmentId}`)}>
            ← 返回场次
          </Button>
        </Caption1>
        <PageHeader
          title={p.title}
          subtitle={<>时间限制：{p.time_limit_ms} ms · 内存限制：{p.memory_limit_mb} MB · 本题满分：{p.full_score}</>}
        />
      </div>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">题目描述</Text>} />
        <MarkdownBody>{p.description}</MarkdownBody>
        <Divider />
        <Text weight="semibold">输入格式</Text>
        <MarkdownBody>{p.input_format}</MarkdownBody>
        <Text weight="semibold">输出格式</Text>
        <MarkdownBody>{p.output_format}</MarkdownBody>
      </Card>

      {data.samples.length > 0 && (
        <Card size="medium">
          <CardHeader header={<Text weight="semibold">样例</Text>} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
            {data.samples.map((s) => (
              <div key={s.seq} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: tokens.spacingHorizontalM }}>
                <div>
                  <Caption1 style={{ color: t.colorNeutralForeground3 }}>样例 {s.seq} 输入</Caption1>
                  <PreBlock text={s.input} />
                </div>
                <div>
                  <Caption1 style={{ color: t.colorNeutralForeground3 }}>样例 {s.seq} 输出</Caption1>
                  <PreBlock text={s.expected} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">提交代码（C 语言）</Text>} />
        <CodeEditor value={code} onChange={setCode} height="360px" />
        {submitError && (
          <MessageBar intent="error" style={{ marginTop: tokens.spacingVerticalS, borderRadius: tokens.borderRadiusMedium }}>
            <MessageBarBody>{submitError}</MessageBarBody>
          </MessageBar>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: tokens.spacingVerticalM }}>
          <Button appearance="primary" icon={<Send24Regular />} onClick={handleSubmit} disabled={submitting}>
            {submitting ? '提交中…' : '提交'}
          </Button>
        </div>
      </Card>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">我的提交历史</Text>} />
        {data.my_submissions.length === 0 ? (
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>还没有提交记录。</Caption1>
        ) : (
          <DataGrid items={data.my_submissions} columns={historyColumns} focusMode="cell">
            <DataGridHeader>
              <DataGridRow>
                {({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}
              </DataGridRow>
            </DataGridHeader>
            <DataGridBody<StudentSubmissionSummary>>
              {({ item, rowId }) => (
                <DataGridRow<StudentSubmissionSummary> key={rowId}>
                  {({ columnId }) => (
                    <DataGridCell>
                      {columnId === 'id' && (
                        <Link to={`/student/submissions/${item.id}`} style={{ color: t.colorBrandForeground1 }}>
                          #{item.id}
                        </Link>
                      )}
                      {columnId === 'submitted_at' && fmtTime(item.submitted_at)}
                      {columnId === 'result' && (
                        <Link to={`/student/submissions/${item.id}`} style={{ textDecoration: 'none' }}>
                          {item.status_text ? (
                            <Caption1 style={{ color: t.colorNeutralForeground2 }}>{item.status_text}</Caption1>
                          ) : (
                            <span style={{ display: 'inline-flex', gap: tokens.spacingHorizontalS, alignItems: 'center' }}>
                              <VerdictBadge verdict={item.verdict} />
                              {item.score !== null && item.score !== undefined && (
                                <Caption1 style={{ color: t.colorNeutralForeground3 }}>{fmtScore(item.score)} 分</Caption1>
                              )}
                            </span>
                          )}
                        </Link>
                      )}
                    </DataGridCell>
                  )}
                </DataGridRow>
              )}
            </DataGridBody>
          </DataGrid>
        )}
      </Card>
    </div>
  );
}
