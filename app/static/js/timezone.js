/**
 * Timezone conversion for timestamps
 *
 * Converts all <time datetime="..."> elements to the user's timezone.
 * Reads timezone from meta tag (CSP-compliant), or falls back
 * to the browser's default timezone.
 *
 * Usage:
 * <time datetime="2025-12-09T14:30:00+00:00">2025-12-09T14:30:00+00:00</time>
 *
 * Will be converted to display the time in the user's local timezone with
 * appropriate formatting.
 */

(function() {
  'use strict';

  /**
   * Get the effective timezone to use for conversion.
   * Prefers server-side profile timezone, falls back to browser default.
   */
  function getUserTimezone() {
    // Check if server provided a timezone from meta tag (CSP-compliant)
    const tzMeta = document.querySelector('meta[name="x-user-timezone"]');
    const serverTimezone = tzMeta ? tzMeta.content.trim() : '';
    if (serverTimezone) {
      return serverTimezone;
    }
    // Fall back to browser's default timezone
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  }

  /**
   * Format a date for display based on whether it has a time component.
   */
  function formatDateTime(date, timezone, hasTime) {
    try {
      if (hasTime) {
        // Full date and time
        return date.toLocaleString('en-US', {
          timeZone: timezone,
          dateStyle: 'medium',
          timeStyle: 'short'
        });
      } else {
        // Date only (for dates without time)
        return date.toLocaleDateString('en-US', {
          timeZone: timezone,
          dateStyle: 'medium'
        });
      }
    } catch (e) {
      console.warn('Timezone conversion failed:', e);
      // Fallback to default formatting
      return hasTime ? date.toLocaleString() : date.toLocaleDateString();
    }
  }

  /**
   * Check if a datetime string includes a time component.
   */
  function hasTimeComponent(dateTimeStr) {
    // ISO datetime with time has 'T' separator
    return dateTimeStr.includes('T');
  }

  /**
   * Convert all <time> elements with datetime attributes to user's timezone.
   */
  function convertTimestamps() {
    const timezone = getUserTimezone();
    const timeElements = document.querySelectorAll('time[datetime]');

    timeElements.forEach(function(el) {
      const datetimeStr = el.getAttribute('datetime');
      if (!datetimeStr) return;

      try {
        const date = new Date(datetimeStr);

        // Skip if invalid date
        if (isNaN(date.getTime())) {
          console.warn('Invalid datetime:', datetimeStr);
          return;
        }

        // Check if datetime has time component
        const hasTime = hasTimeComponent(datetimeStr);

        // Format and update the display text
        const formatted = formatDateTime(date, timezone, hasTime);
        el.textContent = formatted;

        // Add title attribute with full ISO string for accessibility
        el.setAttribute('title', date.toISOString());

      } catch (e) {
        console.warn('Failed to convert timestamp:', datetimeStr, e);
      }
    });
  }

  // Run conversion when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', convertTimestamps);
  } else {
    // DOM already loaded
    convertTimestamps();
  }

  // Expose for manual re-conversion (e.g., after AJAX loads new content)
  window.convertTimestamps = convertTimestamps;

})();
