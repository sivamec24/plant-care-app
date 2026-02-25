/**
 * OTP Verification Page Functionality
 * Handles auto-focus, input validation, and form submission state.
 */

(function() {
  'use strict';

  const codeInput = document.getElementById('code');
  const form = document.querySelector('form');
  const submitBtn = document.getElementById('verify-btn');
  const verifyIcon = document.getElementById('verify-icon');
  const verifyText = document.getElementById('verify-text');
  const verifyLoading = document.getElementById('verify-loading');
  let isSubmitting = false;

  if (!codeInput || !form) return;

  // Auto-focus on code input
  codeInput.focus();

  // Remove non-digits as user types
  codeInput.addEventListener('input', function() {
    this.value = this.value.replace(/\D/g, '');
  });

  // Prevent double submission with loading state
  form.addEventListener('submit', function(e) {
    // Prevent double submission
    if (isSubmitting) {
      e.preventDefault();
      return false;
    }

    // Mark as submitting
    isSubmitting = true;

    // Show loading state
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.classList.add('opacity-75', 'cursor-not-allowed');
    }
    if (verifyIcon) verifyIcon.classList.add('hidden');
    if (verifyText) verifyText.classList.add('hidden');
    if (verifyLoading) verifyLoading.classList.remove('hidden');

    // Allow form to submit normally
    return true;
  });
})();
