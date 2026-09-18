import { useTheme } from '../../appTheme';
import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Caption1,
  Card,
  CardHeader,
  Field,
  Image,
  MessageBar,
  MessageBarBody,
  Slider,
  Text,
  tokens,

} from '@fluentui/react-components';
import { Delete24Regular, ImageAdd24Regular, Save24Regular } from '@fluentui/react-icons';
import { deleteBgImage, updateSettings, uploadBgImage } from '../../api';
import { useSettings } from '../../context';
import { ErrorView, errMessage } from '../../components/StateViews';

const MAX_BG_SIZE = 5 * 1024 * 1024;
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

export function AdminSettingsPage() {
  const t = useTheme();
  const { settings, effective, setPreview, reload } = useSettings();

  const [brandColor, setBrandColor] = useState(settings?.brand_color ?? '');
  const [bgOpacity, setBgOpacity] = useState(settings?.bg_opacity ?? 0.15);
  const [busy, setBusy] = useState(false);
  const bgFileRef = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState<{ intent: 'success' | 'error' | 'info'; text: string } | null>(null);

  useEffect(() => {
    if (settings) {
      setBrandColor(settings.brand_color);
      setBgOpacity(settings.bg_opacity);
    }
  }, [settings]);

  useEffect(() => {
    if (brandColor) setPreview({ brand_color: brandColor });
  }, [brandColor, setPreview]);

  useEffect(() => {
    setPreview({ bg_opacity: bgOpacity });
  }, [bgOpacity, setPreview]);

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    setMessage(null);
    if (!ACCEPTED_TYPES.includes(file.type)) {
      setMessage({ intent: 'error', text: '仅支持 jpg / png / webp 格式' });
      return;
    }
    if (file.size > MAX_BG_SIZE) {
      setMessage({ intent: 'error', text: '图片超过 5MB 上限，请先压缩后再上传（服务端不做二次压缩）' });
      return;
    }
    setBusy(true);
    try {
      const resp = await uploadBgImage(file);
      setPreview({ bg_image_url: resp.url });
      setMessage({ intent: 'success', text: '背景图已上传并即时预览' });
      await reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteBg = async () => {
    if (!window.confirm('确定清除背景图？将恢复纯色背景。')) return;
    setBusy(true);
    setMessage(null);
    try {
      await deleteBgImage();
      setPreview({ bg_image_url: null });
      setMessage({ intent: 'success', text: '背景图已清除' });
      await reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await updateSettings({ brand_color: brandColor, bg_opacity: bgOpacity });
      await reload();
      setMessage({ intent: 'success', text: '设置已保存，其他用户下次加载时生效' });
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  if (!settings) {
    return <ErrorView error={new Error('无法加载当前站点设置，后端可能未启动。')} />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <div>
        <Text as="h2" size={600} weight="semibold">主题设置</Text>
        <Caption1 style={{ color: t.colorNeutralForeground3 }}>
          修改会即时全站预览；点击「保存」后写入数据库，其他用户下次加载时生效。
        </Caption1>
      </div>

      {message && (
        <MessageBar intent={message.intent} style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{message.text}</MessageBarBody>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">主题色</Text>} />
        <Field
          label="品牌色"
          hint="用于生成全站 16 阶品牌色阶（chroma-js 插值），影响按钮、链接、焦点环、图表等。"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM }}>
            <input
              type="color"
              value={/^#[0-9a-fA-F]{6}$/.test(brandColor) ? brandColor : '#000000'}
              onChange={(e) => setBrandColor(e.target.value)}
              style={{
                width: '48px',
                height: '32px',
                padding: 0,
                border: `1px solid ${t.colorNeutralStroke1}`,
                borderRadius: tokens.borderRadiusMedium,
                backgroundColor: 'transparent',
                cursor: 'pointer',
              }}
            />
            <Text style={{ fontFamily: 'Consolas, monospace' }}>{brandColor}</Text>
          </div>
        </Field>
      </Card>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">网页背景图</Text>} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            仅支持 jpg / png / webp，≤5MB；服务端不做二次压缩，请先自行压缩到合适大小。
          </Caption1>
          {effective?.bg_image_url ? (
            <div style={{ display: 'flex', gap: tokens.spacingHorizontalM, alignItems: 'flex-start' }}>
              <Image
                src={effective.bg_image_url}
                alt="背景图预览"
                width={240}
                height={135}
                fit="cover"
                style={{ borderRadius: tokens.borderRadiusMedium, border: `1px solid ${t.colorNeutralStroke2}` }}
              />
              <Button appearance="secondary" icon={<Delete24Regular />} onClick={handleDeleteBg} disabled={busy}>
                清除背景图
              </Button>
            </div>
          ) : (
            <Caption1 style={{ color: t.colorNeutralForeground4 }}>当前无背景图（纯色背景）。</Caption1>
          )}
          <div>
            <Button appearance="secondary" icon={<ImageAdd24Regular />} disabled={busy} onClick={() => bgFileRef.current?.click()}>
              上传背景图
            </Button>
            <input
              ref={bgFileRef}
              type="file"
              accept=".jpg,.jpeg,.png,.webp"
              style={{ display: 'none' }}
              onChange={(e) => void handleUpload(e.target.files?.[0])}
            />
          </div>
          <Field label={`背景图透明度：${bgOpacity.toFixed(2)}`}>
            <Slider
              min={0}
              max={1}
              step={0.01}
              value={bgOpacity}
              onChange={(_, d) => setBgOpacity(d.value)}
              style={{ maxWidth: '360px' }}
            />
          </Field>
        </div>
      </Card>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button appearance="primary" size="large" icon={<Save24Regular />} onClick={handleSave} disabled={busy}>
          {busy ? '保存中…' : '保存设置'}
        </Button>
      </div>
    </div>
  );
}
