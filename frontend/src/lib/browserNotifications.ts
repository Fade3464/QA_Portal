import type { SystemNotification } from '../types';

const CLAIM_PREFIX = 'calllens:browser-notification:';
const CLAIM_TTL_MS = 10_000;
let permissionRequest: Promise<NotificationPermission> | null = null;

export function browserNotificationPermission(): NotificationPermission | 'unsupported' {
  if (!window.isSecureContext || !('Notification' in window)) return 'unsupported';
  return window.Notification.permission;
}

export function requestBrowserNotificationPermission() {
  const current = browserNotificationPermission();
  if (current !== 'default') return Promise.resolve(current);
  if (!permissionRequest) {
    permissionRequest = window.Notification.requestPermission().finally(() => {
      permissionRequest = null;
    });
  }
  return permissionRequest;
}

function claimNotification(item: SystemNotification) {
  const key = `${CLAIM_PREFIX}${item.id}`;
  const now = Date.now();
  try {
    const [lastVersion = '', lastClaimedAt = '0'] = (window.localStorage.getItem(key) || '').split('|');
    if (lastVersion === item.updated_at && now - Number(lastClaimedAt) < CLAIM_TTL_MS) return false;
    window.localStorage.setItem(key, `${item.updated_at}|${now}`);
  } catch {
    // Storage can be unavailable in privacy modes; the browser tag still
    // coalesces repeated notifications from the same origin.
  }
  return true;
}

export function showBrowserNotification(item: SystemNotification, onClick: () => void) {
  if (browserNotificationPermission() !== 'granted' || !claimNotification(item)) return;
  try {
    const nativeNotification = new window.Notification(item.title, {
      body: item.message,
      icon: '/brand/calllens-icon.png',
      badge: '/brand/calllens-icon.png',
      tag: `calllens-${item.id}`,
    });
    nativeNotification.onclick = () => {
      window.focus();
      onClick();
      nativeNotification.close();
    };
  } catch {
    // The in-app notification remains available if the operating system
    // rejects a native notification after permission was granted.
  }
}
