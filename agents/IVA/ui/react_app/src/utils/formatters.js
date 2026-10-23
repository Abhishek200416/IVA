/**
 * Universal Formatting Utilities for AGI 1.7 OMEGA COMMAND
 * Enforces 12-Hour AM/PM Time Presentation across all UI Panels
 */

export function formatTo12Hour(timeStr) {
  if (!timeStr || typeof timeStr !== 'string') return timeStr || '';

  const trimmed = timeStr.trim();
  
  // Return early if already in 12-hour AM/PM format
  if (/\b(AM|PM)\b/i.test(trimmed)) {
    return trimmed;
  }

  // Case 1: "YYYY-MM-DD HH:MM:SS IST" or "YYYY-MM-DD HH:MM IST"
  const isoDateMatch = trimmed.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?(\s*IST)?$/i);
  if (isoDateMatch) {
    const [, datePart, hStr, mStr, sStr, istPart] = isoDateMatch;
    let h = parseInt(hStr, 10);
    const m = mStr;
    const s = sStr;
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    const formattedH = String(h).padStart(2, '0');
    const timePart = s !== undefined ? `${formattedH}:${m}:${s} ${ampm}` : `${formattedH}:${m} ${ampm}`;
    return `${datePart} ${timePart}${istPart ? ' IST' : ''}`;
  }

  // Case 2: "HH:MM:SS IST" or "HH:MM IST"
  const timeWithIstMatch = trimmed.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?(\s*IST)?$/i);
  if (timeWithIstMatch) {
    const [, hStr, mStr, sStr, istPart] = timeWithIstMatch;
    let h = parseInt(hStr, 10);
    const m = mStr;
    const s = sStr;
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    const formattedH = String(h).padStart(2, '0');
    const timePart = s !== undefined ? `${formattedH}:${m}:${s} ${ampm}` : `${formattedH}:${m} ${ampm}`;
    return `${timePart}${istPart ? ' IST' : ''}`;
  }

  // Case 3: ISO 8601 string like "2026-10-15T11:00:00+05:30" or "2026-10-15T14:48:15Z"
  try {
    const parsedDate = new Date(trimmed);
    if (!isNaN(parsedDate.getTime())) {
      return parsedDate.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      }) + ' IST';
    }
  } catch (e) {
    // ignore
  }

  return trimmed;
}

export function getCurrent12HourIST() {
  return new Date().toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true
  }) + ' IST';
}

export function formatCurrency(val) {
  if (val === null || val === undefined || isNaN(val)) return '₹0.00';
  const num = Number(val);
  const prefix = num < 0 ? '-₹' : '₹';
  return `${prefix}${Math.abs(num).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}`;
}

export function formatPercent(val) {
  if (val === null || val === undefined || isNaN(val)) return '0.00%';
  const num = Number(val);
  const prefix = num > 0 ? '+' : '';
  return `${prefix}${num.toFixed(2)}%`;
}
