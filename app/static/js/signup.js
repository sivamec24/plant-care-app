/**
 * Signup Form - Bot protection and validation
 */
(function() {
  'use strict';

  document.addEventListener('DOMContentLoaded', function() {
    const form = document.querySelector('.auth-form');
    if (!form) return;

    const honeypot = document.getElementById('website');
    const submitBtn = form.querySelector('button[type="submit"]');
    const emailInput = document.getElementById('email');

    if (!submitBtn) return;
    const originalBtnText = submitBtn.textContent;

    // Bot protection: Check honeypot field on submit
    form.addEventListener('submit', function(e) {
      // If honeypot filled, likely a bot
      if (honeypot && honeypot.value !== '') {
        e.preventDefault();
        // Suspicious form submission blocked silently
        return false;
      }

      // Show loading state
      submitBtn.disabled = true;
      submitBtn.textContent = 'Sending...';
      submitBtn.setAttribute('aria-busy', 'true');

      // If form validation fails, re-enable button
      if (!form.checkValidity()) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalBtnText;
        submitBtn.removeAttribute('aria-busy');
      }
    });

    // Email validation feedback
    if (emailInput) {
      emailInput.addEventListener('blur', function() {
        if (emailInput.value && !emailInput.checkValidity()) {
          emailInput.setAttribute('aria-invalid', 'true');
        } else {
          emailInput.removeAttribute('aria-invalid');
        }
      });
    }
  });
})();
