/**
 * Global form enhancements.
 *
 * - Character counters on textareas with maxlength
 * - Loading state on form submit buttons (prevents double-submit)
 */

(function () {
  'use strict';

  // --- Character Counters ---
  // Auto-attach to all textareas with a maxlength attribute.
  document.querySelectorAll('textarea[maxlength]').forEach(function (textarea) {
    var max = parseInt(textarea.getAttribute('maxlength'), 10);
    if (!max || max < 20) return; // skip tiny fields like OTP

    var counter = document.createElement('p');
    counter.className = 'text-xs text-slate-400 dark:text-slate-500 text-right mt-1';
    counter.setAttribute('aria-live', 'polite');

    function update() {
      var remaining = max - textarea.value.length;
      counter.textContent = remaining + ' / ' + max + ' characters remaining';
      if (remaining < max * 0.1) {
        counter.className = 'text-xs text-amber-600 dark:text-amber-400 text-right mt-1';
      } else {
        counter.className = 'text-xs text-slate-400 dark:text-slate-500 text-right mt-1';
      }
    }

    update();
    textarea.addEventListener('input', update);
    textarea.parentNode.insertBefore(counter, textarea.nextSibling);
  });

  // --- Form Submit Loading State ---
  // Auto-attach to forms with a submit button (not the assistant form which has its own).
  var spinner =
    '<svg class="animate-spin -ml-1 mr-2 h-4 w-4 inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">' +
    '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>' +
    '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>' +
    '</svg>';

  document.querySelectorAll('form').forEach(function (form) {
    if (form.id === 'ask-form') return; // assistant has its own loading overlay

    form.addEventListener('submit', function () {
      var btn = form.querySelector('button[type="submit"], input[type="submit"]');
      if (!btn || btn.disabled) return;

      btn.disabled = true;
      // Save original child nodes as clones (avoids innerHTML round-trip via data attribute)
      btn._savedNodes = Array.from(btn.childNodes).map(function(n) { return n.cloneNode(true); });
      btn.classList.add('is-loading');
      var loadingText = btn.getAttribute('data-loading-text') || btn.textContent.trim();
      // Build loading state via DOM APIs (no DOM-text-to-innerHTML conversion)
      btn.textContent = '';
      btn.insertAdjacentHTML('afterbegin', spinner);
      btn.appendChild(document.createTextNode(' ' + loadingText + '\u2026'));
    });
  });

  // Restore on bfcache navigation (back/forward) — single listener for all forms
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) {
      document.querySelectorAll('.is-loading').forEach(function (btn) {
        btn.disabled = false;
        btn.textContent = '';
        if (btn._savedNodes) {
          btn._savedNodes.forEach(function(n) { btn.appendChild(n); });
          delete btn._savedNodes;
        }
        btn.classList.remove('is-loading');
      });
    }
  });
})();
