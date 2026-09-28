/* Qisutu Monitoring: persistent desktop navigation and compact mobile menu. */
(function () {
  'use strict';
  const root = document.documentElement;
  const storageKey = 'qisutu-monitoring.sidebar-collapsed';
  const mobile = window.matchMedia('(max-width: 850px)');
  let collapsed = false;
  let mobileCollapsed = true;
  try { collapsed = window.localStorage.getItem(storageKey) === '1'; } catch (_) {}
  root.classList.toggle('sidebar-collapsed', collapsed);
  root.classList.toggle('sidebar-mobile-collapsed', mobileCollapsed);

  function init() {
    const button = document.getElementById('sidebar-toggle');
    const navigation = document.getElementById('main-navigation');
    if (!button || !navigation) return;

    function update() {
      const isCollapsed = mobile.matches ? mobileCollapsed : collapsed;
      const label = isCollapsed ? 'Navigation ausklappen' : 'Navigation einklappen';
      root.classList.toggle('sidebar-collapsed', collapsed);
      root.classList.toggle('sidebar-mobile-collapsed', mobileCollapsed);
      button.setAttribute('aria-expanded', String(!isCollapsed));
      button.setAttribute('aria-label', label);
      button.title = label;
    }

    button.addEventListener('click', function () {
      if (mobile.matches) {
        mobileCollapsed = !mobileCollapsed;
      } else {
        collapsed = !collapsed;
        try { window.localStorage.setItem(storageKey, collapsed ? '1' : '0'); } catch (_) {}
      }
      update();
      // Existing charts and the connection graph also adapt to the new workspace width.
      window.dispatchEvent(new Event('resize'));
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && mobile.matches && !mobileCollapsed) {
        mobileCollapsed = true;
        update();
        button.focus();
      }
    });
    function mediaChanged() {
      if (mobile.matches && mobileCollapsed && navigation.contains(document.activeElement)) {
        button.focus();
      }
      update();
    }
    if (mobile.addEventListener) mobile.addEventListener('change', mediaChanged);
    else mobile.addListener(mediaChanged);
    window.addEventListener('storage', function (event) {
      if (event.key === storageKey || event.key === null) {
        collapsed = event.newValue === '1';
        update();
        window.dispatchEvent(new Event('resize'));
      }
    });
    update();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
}());
