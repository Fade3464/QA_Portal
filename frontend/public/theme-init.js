(function () {
  var defaults = { mode: 'light', primaryColor: '#1677ff', compact: false };
  var preferences = defaults;
  try {
    preferences = Object.assign({}, defaults, JSON.parse(localStorage.getItem('qa-portal-appearance-v2') || '{}'));
  } catch (_) {
    preferences = defaults;
  }
  var systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  var resolved = preferences.mode === 'system' ? (systemDark ? 'dark' : 'light') : preferences.mode;
  document.documentElement.dataset.theme = resolved === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.density = preferences.compact ? 'compact' : 'comfortable';
  document.documentElement.style.setProperty('--qa-primary', preferences.primaryColor || defaults.primaryColor);
  document.documentElement.style.colorScheme = resolved;
  var themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.setAttribute('content', resolved === 'dark' ? '#10131a' : '#f5f7fb');
}());
