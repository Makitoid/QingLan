import { useTheme } from '../../appTheme';
import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Button,
  Caption1,
  Card,
  CardHeader,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Image,
  MessageBar,
  MessageBarBody,
  Slider,
  SpinButton,
  Switch,
  Text,
  tokens,
} from '@fluentui/react-components';
import { ArrowDownload24Regular, Delete24Regular, History24Regular, ImageAdd24Regular, Save24Regular } from '@fluentui/react-icons';
import { deleteBgImage, getAdminSettings, updateSettings, uploadBgImage } from '../../api';
import type { BgMode } from '../../api/types';
import { useSettings } from '../../context';
import { ErrorView, errMessage } from '../../components/StateViews';
import { ACCEPTED_TYPES, ACCEPT_ATTR, MAX_BG_BYTES, compressImage, extractBrandColor, formatMB } from '../../components/imageTools';
import { PageHeader } from '../../components/PageHeader';

interface SlotProps {
  label: string;
  url: string | null;
  disabled: boolean;
  onSelect: () => void;
  onClear: () => void;
}

// Fluent 的开关轨道自带 8px 左外边距（点击热区），会让开关比卡片内其他内容缩进一截。
const switchIndicator = { style: { marginLeft: 0 } };

/** 撤销取色时要回写的槽位；空值（暗色尚未单独设置过）不生成撤销项。 */
type ColorUndo = { mode: BgMode; color: string }[];

const RETENTION_MIN = 1;
const RETENTION_MAX = 3650;
const RETENTION_HINT = `留空 = 永久保存；填 ${RETENTION_MIN}–${RETENTION_MAX} 天则自动清理超期日志`;

const undoEntry = (previous: string, mode: BgMode): ColorUndo =>
  /^#[0-9a-fA-F]{6}$/.test(previous) ? [{ mode, color: previous }] : [];

interface ColorFieldProps {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
}

function BrandColorField({ label, hint, value, onChange }: ColorFieldProps) {
  const t = useTheme();
  return (
    <Field label={label} hint={hint}>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM }}>
        <input
          type="color"
          value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : '#000000'}
          onChange={(e) => onChange(e.target.value)}
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
        <Text style={{ fontFamily: 'Consolas, monospace' }}>{value}</Text>
      </div>
    </Field>
  );
}

function BgSlot({ label, url, disabled, onSelect, onClear }: SlotProps) {
  const t = useTheme();
  return (
    <div style={{ display: 'flex', gap: tokens.spacingHorizontalM, alignItems: 'flex-start' }}>
      {url ? (
        <Image
          src={url}
          alt={`${label}预览`}
          width={200}
          height={112}
          fit="cover"
          style={{ borderRadius: tokens.borderRadiusMedium, border: `1px solid ${t.colorNeutralStroke2}` }}
        />
      ) : (
        <div
          style={{
            width: '200px',
            height: '112px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: `1px dashed ${t.colorNeutralStroke2}`,
            borderRadius: tokens.borderRadiusMedium,
          }}
        >
          <Caption1 style={{ color: t.colorNeutralForeground4 }}>未设置</Caption1>
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
        <Text weight="semibold">{label}</Text>
        <div style={{ display: 'flex', gap: tokens.spacingHorizontalS }}>
          <Button size="small" appearance="secondary" icon={<ImageAdd24Regular />} disabled={disabled} onClick={onSelect}>
            上传
          </Button>
          {url && (
            <Button size="small" appearance="secondary" icon={<Delete24Regular />} disabled={disabled} onClick={onClear}>
              清除
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function AdminSettingsPage() {
  const t = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const { settings, effective, setPreview, reload } = useSettings();

  const [brandColor, setBrandColor] = useState(settings?.brand_color ?? '');
  const [brandColorDark, setBrandColorDark] = useState(settings?.brand_color_dark ?? '');
  const [bgOpacity, setBgOpacity] = useState(settings?.bg_opacity ?? 0.15);
  const [bgDual, setBgDual] = useState(settings?.bg_dual ?? false);
  const [colorFromImage, setColorFromImage] = useState(settings?.brand_color_source === 'image');
  const [auditEnabled, setAuditEnabled] = useState(true);
  const [retentionDays, setRetentionDays] = useState<number | null>(null);
  const [auditLoading, setAuditLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [compressing, setCompressing] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'error' | 'info'; text: string; undo?: ColorUndo } | null>(null);
  const [oversize, setOversize] = useState<{ file: File; mode: BgMode } | null>(null);
  const lightInput = useRef<HTMLInputElement>(null);
  const darkInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (settings) {
      setBrandColor(settings.brand_color);
      setBrandColorDark(settings.brand_color_dark ?? '');
      setBgOpacity(settings.bg_opacity);
      setBgDual(settings.bg_dual);
      setColorFromImage(settings.brand_color_source === 'image');
    }
  }, [settings]);

  useEffect(() => {
    let cancelled = false;
    getAdminSettings()
      .then((admin) => {
        if (cancelled) return;
        setAuditEnabled(admin.audit_enabled);
        setRetentionDays(admin.audit_retention_days);
      })
      .catch((err) => {
        if (!cancelled) setMessage({ intent: 'error', text: errMessage(err) });
      })
      .finally(() => {
        if (!cancelled) setAuditLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const notice = (location.state as { auditNotice?: string } | null)?.auditNotice;
    if (!notice) return;
    setMessage({ intent: 'info', text: notice });
    navigate(location.pathname, { replace: true, state: null });
  }, [location, navigate]);

  useEffect(() => {
    if (brandColor) setPreview({ brand_color: brandColor });
  }, [brandColor, setPreview]);

  useEffect(() => {
    if (brandColorDark) setPreview({ brand_color_dark: brandColorDark });
  }, [brandColorDark, setPreview]);

  useEffect(() => {
    setPreview({ bg_opacity: bgOpacity });
  }, [bgOpacity, setPreview]);

  /** 从一张图里取色并写进对应模式的字段；提不出色时返回 null，由调用方决定提示文案。 */
  const extractInto = async (file: File | Blob, mode: BgMode): Promise<string | null> => {
    const extracted = await extractBrandColor(file);
    if (!extracted) return null;
    if (mode === 'dark') setBrandColorDark(extracted);
    else setBrandColor(extracted);
    await updateSettings(
      mode === 'dark'
        ? { brand_color_dark: extracted, brand_color_source: 'image' }
        : { brand_color: extracted, brand_color_source: 'image' },
    );
    return extracted;
  };

  const slotLabel = (mode: BgMode) => (bgDual ? (mode === 'dark' ? '暗色' : '亮色') : '');

  const upload = async (file: File | Blob, mode: BgMode) => {
    setBusy(true);
    setMessage(null);
    try {
      const resp = await uploadBgImage(file, mode);
      setPreview(mode === 'dark' ? { bg_image_url_dark: resp.url } : { bg_image_url: resp.url });
      const okText = mode === 'dark' ? '暗色背景图已上传' : '背景图已上传';
      if (colorFromImage) {
        const previous = mode === 'dark' ? brandColorDark : brandColor;
        const extracted = await extractInto(file, mode);
        setMessage(
          extracted
            ? {
                intent: 'success',
                text: `${okText}，${slotLabel(mode)}主题色已更新为 ${extracted}`,
                undo: undoEntry(previous, mode),
              }
            : { intent: 'info', text: `${okText}；但这张图里没找到合适的主题色，已保留当前主题色` },
        );
      } else {
        setMessage({ intent: 'success', text: `${okText}并即时预览` });
      }
      await reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const pickFile = (mode: BgMode, file: File | undefined) => {
    if (!file) return;
    setMessage(null);
    if (!ACCEPTED_TYPES.includes(file.type)) {
      setMessage({ intent: 'error', text: '仅支持 jpg / png / webp 格式' });
      return;
    }
    if (file.size > MAX_BG_BYTES) {
      setOversize({ file, mode });
      return;
    }
    void upload(file, mode);
  };

  const confirmCompress = async () => {
    if (!oversize) return;
    setCompressing(true);
    try {
      let out = await compressImage(oversize.file);
      if (out.size > MAX_BG_BYTES && oversize.file.type !== 'image/jpeg') {
        out = await compressImage(oversize.file, 'image/jpeg');
      }
      if (out.size > MAX_BG_BYTES) {
        setMessage({ intent: 'error', text: `压缩后仍有 ${formatMB(out.size)}，超过 5MB 上限，请换一张尺寸更小的图片` });
        setOversize(null);
        return;
      }
      const note = `${formatMB(oversize.file.size)} → ${formatMB(out.size)}`;
      const { mode } = oversize;
      setOversize(null);
      await upload(out, mode);
      setMessage((prev) => (prev?.intent === 'error' ? prev : { ...(prev ?? { intent: 'success', text: '' }), text: `${prev?.text ?? '已上传'}（已压缩 ${note}）` }));
    } catch {
      setOversize(null);
      setMessage({ intent: 'error', text: '图片压缩失败，请换一张图片或先自行压缩后再上传' });
    } finally {
      setCompressing(false);
    }
  };

  const clearImage = async (mode: BgMode) => {
    const label = mode === 'dark' ? '暗色背景图' : '背景图';
    if (!window.confirm(`确定清除${label}？`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const next = await deleteBgImage(mode);
      setPreview(mode === 'dark' ? { bg_image_url_dark: next.bg_image_url_dark } : { bg_image_url: next.bg_image_url });
      setMessage({ intent: 'success', text: `${label}已清除` });
      await reload();
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const toggleExtract = async (on: boolean) => {
    setColorFromImage(on);
    // 抽色开关决定"以后上传是否自动改主题色"，改了就立刻落库，避免刷新后状态跳回去
    await updateSettings({ brand_color_source: on ? 'image' : 'manual' });
    if (!on) return;

    const slots: { mode: BgMode; url: string }[] = [];
    if (effective?.bg_image_url) slots.push({ mode: 'light', url: effective.bg_image_url });
    if (bgDual && effective?.bg_image_url_dark) slots.push({ mode: 'dark', url: effective.bg_image_url_dark });
    if (!slots.length) {
      setMessage({ intent: 'info', text: '先上传一张背景图，主题色才能跟着它走' });
      return;
    }

    setBusy(true);
    const done: string[] = [];
    const undo: ColorUndo = [];
    let failed = false;
    for (const { mode, url } of slots) {
      try {
        const previous = mode === 'dark' ? brandColorDark : brandColor;
        const blob = await fetch(url).then((r) => r.blob());
        const extracted = await extractInto(blob, mode);
        if (extracted) {
          done.push(`${slotLabel(mode)}主题色 ${extracted}`);
          undo.push(...undoEntry(previous, mode));
        }
      } catch {
        failed = true;
      }
    }
    setBusy(false);

    if (done.length) setMessage({ intent: 'success', text: `已按背景图提取：${done.join('；')}`, undo });
    else if (failed) setMessage({ intent: 'error', text: '读取背景图失败，无法提取主题色' });
    else setMessage({ intent: 'info', text: '背景图里没找到合适的主题色，已保留当前主题色' });
  };

  const editColorManually = async (value: string, mode: BgMode) => {
    const wasFollowing = colorFromImage;
    if (mode === 'dark') setBrandColorDark(value);
    else setBrandColor(value);
    setColorFromImage(false);
    if (wasFollowing) await updateSettings({ brand_color_source: 'manual' });
  };

  const undoColor = async () => {
    const entries = message?.undo;
    if (!entries?.length) return;
    for (const entry of entries) {
      if (entry.mode === 'dark') setBrandColorDark(entry.color);
      else setBrandColor(entry.color);
    }
    await updateSettings({
      brand_color: entries.find((e) => e.mode === 'light')?.color,
      brand_color_dark: entries.find((e) => e.mode === 'dark')?.color,
    });
    setMessage({ intent: 'info', text: `已恢复为主题色 ${entries.map((e) => e.color).join(' / ')}` });
    await reload();
  };

  const handleSave = async () => {
    if (retentionDays !== null && (!Number.isInteger(retentionDays) || retentionDays < RETENTION_MIN || retentionDays > RETENTION_MAX)) {
      setMessage({ intent: 'error', text: `审计保留天数需为 ${RETENTION_MIN}–${RETENTION_MAX} 之间的整数，留空表示永久保存` });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const next = await updateSettings({
        brand_color: brandColor,
        brand_color_dark: brandColorDark || undefined,
        brand_color_source: colorFromImage ? 'image' : 'manual',
        bg_dual: bgDual,
        bg_opacity: bgOpacity,
        audit_enabled: auditEnabled,
        audit_retention_days: retentionDays,
      });
      setAuditEnabled(next.audit_enabled);
      setRetentionDays(next.audit_retention_days);
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

  const lightUrl = effective?.bg_image_url ?? null;
  const darkUrl = effective?.bg_image_url_dark ?? null;
  // 与 resolveBrandColors 同一条规则：只有真的在用两张图时，暗色主题色才独立生效
  const darkSlotInUse = bgDual && Boolean(darkUrl);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL }}>
      <PageHeader
        title="系统设置"
        subtitle="修改会即时全站预览；点击「保存」后写入数据库，其他用户下次加载时生效。"
      />

      {message && (
        <MessageBar intent={message.intent} style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>
            {message.text}
            {Boolean(message.undo?.length) && (
              <Button size="small" appearance="transparent" onClick={() => void undoColor()}>
                撤销取色
              </Button>
            )}
          </MessageBarBody>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">主题色</Text>} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <BrandColorField
            label={darkSlotInUse ? '亮色模式品牌色' : '品牌色'}
            hint="用于生成全站 16 阶品牌色阶（chroma-js 插值），影响按钮、链接、焦点环、图表等。"
            value={brandColor}
            onChange={(v) => void editColorManually(v, 'light')}
          />
          {darkSlotInUse && (
            <BrandColorField
              label="暗色模式品牌色"
              hint="暗色模式在用自己的背景图，主题色也可以独立于亮色；未单独提取过时沿用亮色。"
              value={brandColorDark || brandColor}
              onChange={(v) => void editColorManually(v, 'dark')}
            />
          )}
          <Switch
            checked={colorFromImage}
            disabled={busy}
            label="主题色从背景图提取"
            indicator={switchIndicator}
            onChange={(_, data) => void toggleExtract(data.checked)}
          />
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            打开后主题色跟随背景图：每次换图都会重新提取并写入对应模式的主题色（可撤销）；亮暗各用一张图时分别提取、互不覆盖。手动改上面的品牌色会自动关闭此开关。
          </Caption1>
        </div>
      </Card>

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">网页背景图</Text>} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            仅支持 jpg / png / webp，≤5MB；服务端不做二次压缩，超过 5MB 的图可在上传时选择浏览器本地压缩。
          </Caption1>
          <Switch
            checked={bgDual}
            disabled={busy}
            label="亮色 / 暗色使用不同背景图"
            indicator={switchIndicator}
            onChange={(_, data) => {
              setBgDual(data.checked);
              setPreview({ bg_dual: data.checked });
            }}
          />
          {bgDual ? (
            <>
              <BgSlot
                label="亮色模式背景图"
                url={lightUrl}
                disabled={busy}
                onSelect={() => lightInput.current?.click()}
                onClear={() => void clearImage('light')}
              />
              <BgSlot
                label="暗色模式背景图"
                url={darkUrl}
                disabled={busy}
                onSelect={() => darkInput.current?.click()}
                onClear={() => void clearImage('dark')}
              />
            </>
          ) : (
            <BgSlot
              label="背景图"
              url={lightUrl}
              disabled={busy}
              onSelect={() => lightInput.current?.click()}
              onClear={() => void clearImage('light')}
            />
          )}
          <input
            ref={lightInput}
            type="file"
            accept={ACCEPT_ATTR}
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              pickFile('light', file);
            }}
          />
          <input
            ref={darkInput}
            type="file"
            accept={ACCEPT_ATTR}
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              pickFile('dark', file);
            }}
          />
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

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">审计日志</Text>} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Switch
            checked={auditEnabled}
            disabled={busy || auditLoading}
            label="启用审计"
            indicator={switchIndicator}
            onChange={(_, data) => setAuditEnabled(data.checked)}
          />
          <Field label="保留天数" hint={RETENTION_HINT} style={{ maxWidth: '360px' }}>
            <SpinButton
              value={retentionDays}
              min={RETENTION_MIN}
              max={RETENTION_MAX}
              disabled={busy || auditLoading}
              onChange={(_, data) => setRetentionDays(data.value ?? null)}
            />
          </Field>
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            关闭审计只停止写入新日志，已有记录不会被删除；重新开启后历史日志照常可见。填写保留天数后，超过该天数的日志会在应用启动、保存本页设置或下一次写入审计时自动清理；留空则永久保存。审计日志仅管理员可见、只读，不提供修改或删除入口。
          </Caption1>
          <div>
            <Button appearance="secondary" icon={<History24Regular />} onClick={() => navigate('/admin/audit')}>
              查看审计日志
            </Button>
          </div>
        </div>
      </Card>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button appearance="primary" size="large" icon={<Save24Regular />} onClick={handleSave} disabled={busy || auditLoading}>
          {busy ? '保存中…' : '保存设置'}
        </Button>
      </div>

      {/* 条件挂载：Fluent 的退出过渡在部分环境下不会触发 unmountOnClose，会留下带 modal 语义的残留节点 */}
      {oversize && (
        <Dialog
          open
          onOpenChange={(_, data) => {
            if (!data.open && !compressing) setOversize(null);
          }}
        >
          <DialogSurface>
            <DialogBody>
              <DialogTitle>图片超过 5MB</DialogTitle>
              <DialogContent>
                <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                  <Text>这张图 {formatMB(oversize.file.size)}，超过服务端 5MB 上限，无法直接上传。</Text>
                  <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                    是否先在浏览器本地压缩？目标：最长边 2560px、不超过 2MB；原图不会上传，压缩完成后才发送。
                  </Caption1>
                </div>
              </DialogContent>
              <DialogActions>
                <Button appearance="secondary" disabled={compressing} onClick={() => setOversize(null)}>
                  取消
                </Button>
                <Button
                  appearance="primary"
                  icon={compressing ? undefined : <ArrowDownload24Regular />}
                  disabled={compressing}
                  onClick={() => void confirmCompress()}
                >
                  {compressing ? '压缩中…' : '压缩并上传'}
                </Button>
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      )}
    </div>
  );
}
