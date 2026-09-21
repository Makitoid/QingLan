import { useState } from 'react';
import {
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  MessageBar,
  MessageBarBody,
  Text,
  tokens,
} from '@fluentui/react-components';
import { ArrowDownload24Regular, Checkmark24Regular, Copy24Regular } from '@fluentui/react-icons';
import { useTheme } from '../appTheme';
import type { TempCredential } from '../api/types';
import { downloadCredentialCsv, expiryLabel, formatCredential, formatCredentials, copyToClipboard } from './credentialCsv';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 标题，如「临时密码 · 张三」/「批量重置完成」。 */
  title: string;
  /** 重置接口返回的逐行凭证（PW-09）。 */
  credentials: TempCredential[];
  /** CSV 文件名前缀。 */
  csvPrefix?: string;
  /** 密码列的表头：随机重置用「临时密码」，初始密码表用「初始密码」。 */
  passwordHeader?: string;
}

/**
 * PW-09 凭证对话框：展示重置返回的随机密码，支持逐行复制、复制全部与下载 CSV。
 *
 * 密码只在**响应里存在一次**，关掉就查不到（PW-05：未改密的临时密码 7 天后过期，
 * 但界面上没有「查看当前密码」的能力），所以提示管理员先复制或下载再分发。
 */
export function CredentialDialog({ open, onOpenChange, title, credentials, csvPrefix = '临时密码', passwordHeader }: Props) {
  const t = useTheme();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copyFailed, setCopyFailed] = useState(false);

  const copy = async (key: string, text: string) => {
    const ok = await copyToClipboard(text);
    setCopyFailed(!ok);
    setCopiedKey(ok ? key : null);
    if (!ok) return;
    window.setTimeout(() => setCopiedKey((cur) => (cur === key ? null : cur)), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={(_, d) => onOpenChange(d.open)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent>
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                新密码只显示这一次，请复制或下载 CSV 后转告本人；对方首次（或下次）登录会被要求立即改密。
                {credentials.some((c) => c.expires_at) ? ' 随机密码自生成起 7 天内有效，逾期需重新重置。' : ''}
              </Caption1>

              {copyFailed && (
                <MessageBar intent="warning" style={{ borderRadius: tokens.borderRadiusMedium }}>
                  <MessageBarBody>
                    浏览器拒绝了自动复制，请手动选中文本复制，或改用「下载 CSV」。
                  </MessageBarBody>
                </MessageBar>
              )}

              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: tokens.spacingVerticalSNudge,
                  border: `1px solid ${t.colorNeutralStroke2}`,
                  borderRadius: tokens.borderRadiusMedium,
                  padding: tokens.spacingVerticalS,
                  maxHeight: '360px',
                  overflowY: 'auto',
                }}
              >
                {credentials.map((row) => {
                  const key = `${row.student_id}-${row.username}`;
                  return (
                    <div
                      key={key}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: tokens.spacingHorizontalS,
                        flexWrap: 'wrap',
                        paddingInline: tokens.spacingHorizontalSNudge,
                      }}
                    >
                      <div style={{ display: 'flex', flexDirection: 'column', minWidth: '160px' }}>
                        <Text weight="semibold">{`${row.display_name}（${row.username}）`}</Text>
                        <Caption1 style={{ color: t.colorNeutralForeground3 }}>有效期：{expiryLabel(row.expires_at)}</Caption1>
                      </div>
                      <Text
                        style={{
                          fontFamily: tokens.fontFamilyMonospace,
                          fontSize: tokens.fontSizeBase400,
                          color: t.colorNeutralForeground1,
                          paddingInline: tokens.spacingHorizontalSNudge,
                          paddingBlock: tokens.spacingVerticalXXS,
                          backgroundColor: t.colorNeutralBackground4,
                          borderRadius: tokens.borderRadiusSmall,
                        }}
                      >
                        {row.temp_password}
                      </Text>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={copiedKey === key ? <Checkmark24Regular /> : <Copy24Regular />}
                        onClick={() => void copy(key, formatCredential(row))}
                      >
                        {copiedKey === key ? '已复制' : '复制'}
                      </Button>
                    </div>
                  );
                })}
              </div>
            </div>
          </DialogContent>
          <DialogActions>
            <Button
              appearance="secondary"
              icon={copiedKey === '__all__' ? <Checkmark24Regular /> : <Copy24Regular />}
              onClick={() => void copy('__all__', formatCredentials(credentials))}
            >
              {copiedKey === '__all__' ? '已复制全部' : '复制全部'}
            </Button>
            <Button appearance="secondary" icon={<ArrowDownload24Regular />} onClick={() => downloadCredentialCsv(credentials, csvPrefix, passwordHeader)}>
              下载 CSV
            </Button>
            <Button appearance="primary" onClick={() => onOpenChange(false)}>
              完成
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
