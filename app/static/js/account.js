/**
 * Account Settings Page Functionality
 */

(function() {
  'use strict';

  // Display browser's actual timezone when using default
  const browserTzDisplay = document.getElementById('browser-timezone-display');
  if (browserTzDisplay) {
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    browserTzDisplay.textContent = browserTz.replace(/_/g, ' ');
  }
})();
