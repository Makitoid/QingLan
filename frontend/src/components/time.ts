import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);

const NAIVE_UTC = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$/;

function toDayjs(value: string) {
  const normalized = NAIVE_UTC.test(value) ? `${value.replace(' ', 'T')}Z` : value;
  return dayjs(normalized);
}

export function fmtTime(value?: string | null): string {
  if (!value) return '—';
  const d = toDayjs(value);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : value;
}

export function fmtTimeWithSeconds(value?: string | null): string {
  if (!value) return '—';
  const d = toDayjs(value);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : value;
}

export function toUtcString(localInputValue: string): string {
  const d = dayjs(localInputValue);
  return d.isValid() ? d.utc().format('YYYY-MM-DD HH:mm:ss') : localInputValue;
}

export function toLocalInputValue(utcValue?: string | null): string {
  if (!utcValue) return '';
  const d = toDayjs(utcValue);
  return d.isValid() ? d.format('YYYY-MM-DDTHH:mm') : '';
}
