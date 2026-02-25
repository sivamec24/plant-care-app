/**
 * Dashboard Quick Complete Functionality
 * Handles AJAX completion of reminders from the dashboard view
 */

(function() {
  'use strict';

  // Escape HTML to prevent XSS
  function escapeHTML(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  document.addEventListener('DOMContentLoaded', function() {

    // ========================================================================
    // ACCESSIBILITY: Screen Reader Announcements
    // ========================================================================

    // Create a live region for screen reader announcements
    let srAnnouncer = document.getElementById('sr-announcer');
    if (!srAnnouncer) {
      srAnnouncer = document.createElement('div');
      srAnnouncer.id = 'sr-announcer';
      srAnnouncer.className = 'sr-only';
      srAnnouncer.setAttribute('aria-live', 'polite');
      srAnnouncer.setAttribute('aria-atomic', 'true');
      srAnnouncer.setAttribute('role', 'status');
      document.body.appendChild(srAnnouncer);
    }

    // Announce message to screen readers
    function announceToScreenReader(message) {
      if (srAnnouncer) {
        // Clear first to ensure announcement even if same message
        srAnnouncer.textContent = '';
        setTimeout(() => {
          srAnnouncer.textContent = message;
        }, 100);
      }
    }

    // ========================================================================
    // GREETING
    // ========================================================================

    function updateGreeting() {
        // Get the current local hour using the client's system clock
        const now = new Date();
        const hour = now.getHours(); // getHours() returns 0-23
        let greetingMessage;

        // Determine the appropriate greeting based on the hour
        if (hour < 12) {
            greetingMessage = "Good morning";
        } else if (hour < 18) {
            greetingMessage = "Good afternoon";
        } else {
            greetingMessage = "Good evening";
        }

        const greetingElement = document.getElementById('greeting-display'); 
        if (greetingElement) {
            greetingElement.textContent = greetingMessage + "!";
        } else {
            console.error("Error: Could not find element with ID 'greeting-display'.");
        }
    }

    // Call the greeting function immediately when the DOM is ready
    updateGreeting();

    // Plant carousel scroll functionality with gradient indicators
    const scrollContainer = document.getElementById('dashboard-plants-scroll-container');
    const scrollLeftBtn = document.getElementById('dashboard-scroll-left-btn');
    const scrollRightBtn = document.getElementById('dashboard-scroll-right-btn');
    const gradientLeft = document.getElementById('dashboard-gradient-left');
    const gradientRight = document.getElementById('dashboard-gradient-right');

    if (scrollContainer && scrollLeftBtn && scrollRightBtn) {
      // Scroll distance (approximately 3 plant cards)
      const scrollDistance = 300;

      // Update button states and gradient visibility based on scroll position
      function updateScrollState() {
        const { scrollLeft, scrollWidth, clientWidth } = scrollContainer;
        const maxScroll = scrollWidth - clientWidth;

        // Update button states
        scrollLeftBtn.disabled = scrollLeft <= 1;
        scrollRightBtn.disabled = scrollLeft >= maxScroll - 1;

        // Update gradient indicators
        if (gradientLeft) {
          gradientLeft.style.opacity = scrollLeft > 10 ? '1' : '0';
        }
        if (gradientRight) {
          gradientRight.style.opacity = scrollLeft < maxScroll - 10 ? '1' : '0';
        }
      }

      // Scroll left
      scrollLeftBtn.addEventListener('click', () => {
        scrollContainer.scrollBy({ left: -scrollDistance, behavior: 'smooth' });
      });

      // Scroll right
      scrollRightBtn.addEventListener('click', () => {
        scrollContainer.scrollBy({ left: scrollDistance, behavior: 'smooth' });
      });

      // Update states on scroll
      scrollContainer.addEventListener('scroll', updateScrollState);

      // Keyboard navigation for carousel (WCAG 2.1 compliance)
      scrollContainer.addEventListener('keydown', function(e) {
        switch (e.key) {
          case 'ArrowLeft':
            e.preventDefault();
            scrollContainer.scrollBy({ left: -scrollDistance, behavior: 'smooth' });
            break;
          case 'ArrowRight':
            e.preventDefault();
            scrollContainer.scrollBy({ left: scrollDistance, behavior: 'smooth' });
            break;
          case 'Home':
            e.preventDefault();
            scrollContainer.scrollTo({ left: 0, behavior: 'smooth' });
            break;
          case 'End':
            e.preventDefault();
            scrollContainer.scrollTo({ left: scrollContainer.scrollWidth, behavior: 'smooth' });
            break;
        }
      });

      // Initial state
      updateScrollState();

      // Re-check after images load (they might affect scrollWidth)
      window.addEventListener('load', () => {
        setTimeout(updateScrollState, 100);
      });
    }

    // Get CSRF token securely from data attribute
    const csrfTokenEl = document.getElementById('csrf-token');
    if (!csrfTokenEl) return; // No CSRF token, no reminders to complete

    const csrfToken = csrfTokenEl.dataset.csrf;
    const completeButtons = document.querySelectorAll('.quick-complete-btn');

    completeButtons.forEach(button => {
      button.addEventListener('click', async function(e) {
        e.preventDefault();

        const reminderId = this.dataset.reminderId;
        const reminderTitle = this.dataset.reminderTitle;
        const reminderItem = this.closest('[data-reminder-id]');

        // Disable button and show loading state
        this.disabled = true;
        this.innerHTML = '⏳ Completing...';

        try {
          const response = await fetch(`/reminders/api/${reminderId}/complete`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrfToken
            }
          });

          const data = await response.json();

          if (data.success) {
            // Check if user prefers reduced motion
            const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

            if (prefersReducedMotion) {
              // Instant removal for reduced motion preference
              reminderItem.remove();
              handlePostRemoval();
            } else {
              // Fade out and remove the reminder item
              reminderItem.style.opacity = '0';
              reminderItem.style.transition = 'opacity 0.3s ease';

              setTimeout(() => {
                reminderItem.remove();
                handlePostRemoval();
              }, 300);
            }

            function handlePostRemoval() {
              // Check if Today's Focus or Reminders list is empty
              const focusList = document.getElementById('todays-focus-list');
              const remindersList = document.getElementById('dashboard-reminders-list');

              const focusEmpty = focusList && focusList.children.length === 0;
              const remindersEmpty = remindersList && remindersList.children.length === 0;

              // Reload page if either list becomes empty to show proper empty state
              if (focusEmpty || remindersEmpty) {
                window.location.reload();
              } else {
                // Show success message
                if (window.showToast) {
                  window.showToast(`✓ ${reminderTitle} marked complete!`, 'success');
                }

                // Update the "Due Today" badge count
                const badge = document.querySelector('#reminders-title .badge-amber');
                if (badge) {
                  const currentCount = parseInt(badge.textContent) || 0;
                  const newCount = currentCount - 1;
                  if (newCount > 0) {
                    badge.textContent = newCount;
                  } else {
                    badge.remove();
                  }
                }
              }
            }

          } else {
            // Show error
            this.disabled = false;
            this.innerHTML = '✓ Done';
            if (window.showToast) {
              window.showToast(data.error || 'Failed to complete reminder', 'error');
            } else {
              alert(data.error || 'Failed to complete reminder');
            }
          }
        } catch (error) {
          // Network or other error
          this.disabled = false;
          this.innerHTML = '✓ Done';
          if (window.showToast) {
            window.showToast('Network error. Please try again.', 'error');
          } else {
            alert('Network error. Please try again.');
          }
        }
      });
    });

    // ========================================================================
    // WEATHER SUGGESTION HANDLERS
    // ========================================================================

    // Shared function to check if suggestions section is empty and remove it
    function checkEmptySuggestionsSection() {
      const suggestionsSection = document.querySelector('[aria-labelledby="weather-title"]');
      if (suggestionsSection) {
        const remainingSuggestions = suggestionsSection.querySelectorAll('[data-reminder-id]');
        if (remainingSuggestions.length === 0) {
          suggestionsSection.remove();
        }
      }
    }

    // Handle weather suggestion accept buttons
    const acceptButtons = document.querySelectorAll('.weather-accept-btn');
    acceptButtons.forEach(button => {
      button.addEventListener('click', async function(e) {
        e.preventDefault();

        // Get reminder ID from parent card (not the button itself)
        const suggestionCard = this.closest('[data-reminder-id]');
        if (!suggestionCard) {
          console.error('Could not find suggestion card element');
          return;
        }

        const reminderId = suggestionCard.dataset.reminderId;
        const days = parseInt(this.dataset.days || 0);
        const reason = this.dataset.reason || '';

        // Validate reminder ID is present and looks like a UUID
        if (!reminderId || reminderId === 'undefined' || reminderId === 'null') {
          console.error('Invalid reminder ID:', reminderId);
          return;
        }

        // Basic UUID format check (8-4-4-4-12 hex chars)
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        if (!uuidRegex.test(reminderId)) {
          console.error('Reminder ID is not a valid UUID:', reminderId);
          return;
        }

        // Disable button and show loading state
        this.disabled = true;
        const originalText = this.innerHTML;
        this.innerHTML = '⏳ Applying...';

        try {
          // Call API to adjust reminder with reason
          const response = await fetch(`/reminders/api/${reminderId}/adjust`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
              days: days,
              reason: reason
            })
          });

          // Check HTTP status before parsing JSON
          if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            console.error('Weather adjustment API error:', response.status, errorData);
            throw new Error(errorData.error || `Server error (${response.status})`);
          }

          const data = await response.json();

          if (data.success) {
            // Check if user prefers reduced motion
            const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

            // Announce to screen readers and show toast
            const successMessage = 'Reminder adjusted based on weather';
            announceToScreenReader(successMessage);
            if (window.showToast) {
              window.showToast('✓ ' + successMessage, 'success');
            }

            if (prefersReducedMotion) {
              // Instant reload for accessibility
              window.location.reload();
            } else {
              // Quick fade (150ms) then immediate reload
              suggestionCard.style.opacity = '0';
              suggestionCard.style.transition = 'opacity 0.15s ease';
              setTimeout(() => window.location.reload(), 150);
            }
          } else {
            // Show error
            console.error('Weather adjustment failed:', data.error);
            this.disabled = false;
            this.innerHTML = originalText;
            const errorMsg = data.error || 'Failed to adjust reminder';
            announceToScreenReader('Error: ' + errorMsg);
            if (window.showToast) {
              window.showToast(errorMsg, 'error');
            } else {
              alert(errorMsg);
            }
          }
        } catch (error) {
          // Network or server error
          console.error('Weather adjustment error:', error);
          this.disabled = false;
          this.innerHTML = originalText;
          const errorMsg = error.message || 'Network error. Please try again.';
          announceToScreenReader('Error: ' + errorMsg);
          if (window.showToast) {
            window.showToast(errorMsg, 'error');
          } else {
            alert(errorMsg);
          }
        }
      });
    });

    // Handle weather suggestion dismiss buttons
    const dismissButtons = document.querySelectorAll('.weather-dismiss-btn');
    dismissButtons.forEach(button => {
      button.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();

        // Get reminder ID from parent card (not the button itself)
        const suggestionCard = this.closest('[data-reminder-id]');
        if (!suggestionCard) {
          console.error('Could not find suggestion card to dismiss');
          return;
        }

        const reminderId = suggestionCard.dataset.reminderId;

        // Store dismissal in session storage
        const dismissed = JSON.parse(sessionStorage.getItem('dismissedSuggestions') || '[]');
        if (!dismissed.includes(reminderId)) {
          dismissed.push(reminderId);
          sessionStorage.setItem('dismissedSuggestions', JSON.stringify(dismissed));
        }

        // Get the next focusable element before removing the card
        const nextCard = suggestionCard.nextElementSibling;
        const prevCard = suggestionCard.previousElementSibling;
        const suggestionsSection = document.querySelector('[aria-labelledby="weather-title"]');

        // Check if user prefers reduced motion
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        // Announce and show toast
        const dismissMessage = 'Suggestion dismissed. Proceeding with original schedule.';
        announceToScreenReader(dismissMessage);

        function handleAfterRemoval() {
          suggestionCard.remove();
          checkEmptySuggestionsSection();

          // Move focus to next suggestion, previous suggestion, or section heading
          if (nextCard && nextCard.querySelector('button')) {
            nextCard.querySelector('button').focus();
          } else if (prevCard && prevCard.querySelector('button')) {
            prevCard.querySelector('button').focus();
          } else if (suggestionsSection) {
            // Section is now empty, focus on weather title or next section
            const weatherTitle = document.getElementById('weather-title');
            if (weatherTitle) {
              weatherTitle.focus();
            }
          }

          if (window.showToast) {
            window.showToast(dismissMessage, 'info');
          }
        }

        if (prefersReducedMotion) {
          // Instant removal for accessibility
          handleAfterRemoval();
        } else {
          // Quick fade (150ms) then remove
          suggestionCard.style.opacity = '0';
          suggestionCard.style.transition = 'opacity 0.15s ease';
          setTimeout(handleAfterRemoval, 150);
        }
      });
    });

    // Hide dismissed suggestions on page load
    const dismissedSuggestions = JSON.parse(sessionStorage.getItem('dismissedSuggestions') || '[]');
    dismissedSuggestions.forEach(reminderId => {
      const card = document.querySelector(`[data-reminder-id="${reminderId}"]`);
      if (card && card.closest('[aria-labelledby="weather-title"]')) {
        card.remove();
      }
    });
    // Check if suggestions section is now empty after removing dismissed cards
    checkEmptySuggestionsSection();

    // ========================================================================
    // "WHY?" EXPLANATION MODAL
    // ========================================================================

    // Handle "Why?" button clicks (data attribute instead of inline onclick)
    const whyButtons = document.querySelectorAll('.adjustment-why-btn');
    whyButtons.forEach(button => {
      button.addEventListener('click', function(e) {
        e.preventDefault();
        try {
          const adjustmentData = JSON.parse(this.dataset.adjustment || '{}');
          window.showAdjustmentDetails(adjustmentData);
        } catch (err) {
          console.error('Failed to parse adjustment data:', err);
        }
      });
    });

    // Helper function to format dates relatively (e.g., "today", "2 days ago")
    function formatRelativeDate(isoDate) {
      if (!isoDate) return '';
      const date = new Date(isoDate);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const dateOnly = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      const diffDays = Math.floor((today - dateOnly) / (1000 * 60 * 60 * 24));

      if (diffDays === 0) return 'today';
      if (diffDays === 1) return 'yesterday';
      if (diffDays > 1 && diffDays < 7) return `${diffDays} days ago`;
      if (diffDays >= 7 && diffDays < 14) return 'last week';
      // Fall back to formatted date
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    // Show adjustment details modal
    window.showAdjustmentDetails = function(adjustment) {
      const modal = document.createElement('div');
      modal.className = 'fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 flex items-center justify-center z-50 p-4';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-labelledby', 'modal-title');
      modal.setAttribute('aria-modal', 'true');

      const details = adjustment.details || {};
      const adjustedAt = adjustment.adjusted_at ? formatRelativeDate(adjustment.adjusted_at) : '';

      // Build details HTML
      let detailsHTML = '<dl class="space-y-3 mt-4">';

      if (details.weather_condition) {
        detailsHTML += `
          <div>
            <dt class="text-sm font-semibold text-slate-700 dark:text-slate-300">Condition</dt>
            <dd class="text-sm text-slate-600 dark:text-slate-400 capitalize">${escapeHTML(details.weather_condition.replace(/_/g, ' '))}</dd>
          </div>
        `;
      }

      if (details.precipitation_inches !== undefined) {
        detailsHTML += `
          <div>
            <dt class="text-sm font-semibold text-slate-700 dark:text-slate-300">Precipitation</dt>
            <dd class="text-sm text-slate-600 dark:text-slate-400">${details.precipitation_inches}" expected</dd>
          </div>
        `;
      }

      if (details.temp_min_f !== undefined) {
        detailsHTML += `
          <div>
            <dt class="text-sm font-semibold text-slate-700 dark:text-slate-300">Temperature Range</dt>
            <dd class="text-sm text-slate-600 dark:text-slate-400">${details.temp_min_f}°F - ${details.temp_max_f || 'N/A'}°F</dd>
          </div>
        `;
      }

      if (details.freeze_risk !== undefined) {
        detailsHTML += `
          <div>
            <dt class="text-sm font-semibold text-slate-700 dark:text-slate-300">Freeze Risk</dt>
            <dd class="text-sm text-slate-600 dark:text-slate-400">${details.freeze_risk ? 'Yes' : 'No'}</dd>
          </div>
        `;
      }

      if (details.light_factor !== undefined) {
        detailsHTML += `
          <div>
            <dt class="text-sm font-semibold text-slate-700 dark:text-slate-300">Light Adjustment</dt>
            <dd class="text-sm text-slate-600 dark:text-slate-400">${((details.light_factor - 1) * 100).toFixed(0)}% ${details.light_factor > 1 ? 'more' : 'less'} water needed</dd>
          </div>
        `;
      }

      detailsHTML += '</dl>';

      modal.innerHTML = `
        <div class="bg-white dark:bg-slate-800 rounded-xl shadow-2xl max-w-md w-full p-6 max-h-[90vh] overflow-y-auto">
          <div class="flex items-start justify-between mb-4">
            <div>
              <h3 id="modal-title" class="text-xl font-bold text-slate-900 dark:text-slate-100">
                Adjustment Details
              </h3>
              <p class="text-sm text-slate-600 dark:text-slate-400 mt-1">
                Why this reminder was adjusted
              </p>
            </div>
            <button
              onclick="this.closest('[role=dialog]').remove()"
              class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
              aria-label="Close modal"
            >
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <div class="p-4 bg-cyan-50 dark:bg-cyan-900/20 border-l-4 border-cyan-400 dark:border-cyan-500 rounded-r mb-4">
            <p class="text-sm font-medium text-slate-700 dark:text-slate-300">
              ${escapeHTML(adjustment.reason)}
            </p>
            ${adjustedAt ? `<p class="text-xs text-slate-500 dark:text-slate-500 mt-1">Adjusted ${escapeHTML(adjustedAt)}</p>` : ''}
          </div>

          ${detailsHTML}

          <div class="mt-6 flex justify-end gap-3">
            <button
              onclick="this.closest('[role=dialog]').remove()"
              class="btn btn-secondary"
            >
              Close
            </button>
          </div>
        </div>
      `;

      // Store the element that triggered the modal for focus restoration
      const triggerElement = document.activeElement;

      // Close modal and restore focus
      function closeModal() {
        modal.remove();
        document.removeEventListener('keydown', keyHandler);
        // Restore focus to the trigger element
        if (triggerElement && triggerElement.focus) {
          triggerElement.focus();
        }
      }

      // Close on background click
      modal.addEventListener('click', function(e) {
        if (e.target === modal) {
          closeModal();
        }
      });

      // Update close buttons to use closeModal function
      modal.querySelectorAll('button[aria-label="Close modal"], button:last-child').forEach(btn => {
        btn.onclick = closeModal;
      });

      // Keyboard handler for Escape and focus trap
      function keyHandler(e) {
        if (e.key === 'Escape') {
          closeModal();
          return;
        }

        // Focus trap: keep focus within modal
        if (e.key === 'Tab') {
          const focusableElements = modal.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          );
          const firstElement = focusableElements[0];
          const lastElement = focusableElements[focusableElements.length - 1];

          if (e.shiftKey) {
            // Shift+Tab: if on first element, go to last
            if (document.activeElement === firstElement) {
              e.preventDefault();
              lastElement.focus();
            }
          } else {
            // Tab: if on last element, go to first
            if (document.activeElement === lastElement) {
              e.preventDefault();
              firstElement.focus();
            }
          }
        }
      }

      document.addEventListener('keydown', keyHandler);

      document.body.appendChild(modal);

      // Focus the close button when modal opens
      const closeBtn = modal.querySelector('button[aria-label="Close modal"]');
      if (closeBtn) {
        closeBtn.focus();
      }
    };
  });
})();
