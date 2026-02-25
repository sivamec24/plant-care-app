/**
 * Toast Notification System
 * Modern replacement for flash messages
 * Usage: showToast('Success!', 'Your plant was added', 'success')
 */

// Escape HTML to prevent XSS
function escapeHTML(str) {
  if (!str) return '';
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Create toast container if it doesn't exist
function ensureToastContainer() {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    container.setAttribute('aria-live', 'polite');
    container.setAttribute('aria-atomic', 'true');
    document.body.appendChild(container);
  }
  return container;
}

// Show a toast notification
function showToast(title, message, type = 'info', duration = 4000) {
  const container = ensureToastContainer();

  // Create toast element
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', 'alert');

  // Icon mapping
  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ'
  };

  toast.innerHTML = `
    <div class="toast-icon" aria-hidden="true">${icons[type] || icons.info}</div>
    <div class="toast-content">
      ${title ? `<div class="toast-title">${escapeHTML(title)}</div>` : ''}
      ${message ? `<div class="toast-message">${escapeHTML(message)}</div>` : ''}
    </div>
    <button class="toast-close" aria-label="Close notification">×</button>
  `;

  // Add to container
  container.appendChild(toast);

  // Close button handler
  const closeBtn = toast.querySelector('.toast-close');
  closeBtn.addEventListener('click', () => {
    dismissToast(toast);
  });

  // Auto-dismiss after duration
  if (duration > 0) {
    setTimeout(() => {
      dismissToast(toast);
    }, duration);
  }

  return toast;
}

// Dismiss a toast with animation
function dismissToast(toast) {
  if (!toast || toast.classList.contains('toast-exit')) return;

  toast.classList.add('toast-exit');

  // Remove from DOM after animation
  setTimeout(() => {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, 300); // Match CSS animation duration
}

// Convert flash messages to toasts on page load
document.addEventListener('DOMContentLoaded', () => {
  const flashMessages = document.querySelectorAll('.flash-messages .flash');

  flashMessages.forEach(flash => {
    // Extract type from class (flash-success, flash-error, etc.)
    const classList = Array.from(flash.classList);
    const typeClass = classList.find(c => c.startsWith('flash-'));
    const type = typeClass ? typeClass.replace('flash-', '') : 'info';

    // Extract message text
    const messageElement = flash.querySelector('.flash-message');
    const message = messageElement ? messageElement.textContent.trim() : flash.textContent.trim();

    // Show as toast
    showToast('', message, type);

    // Hide original flash message
    flash.style.display = 'none';
  });
});

// Export for use in other scripts
window.showToast = showToast;
window.dismissToast = dismissToast;
