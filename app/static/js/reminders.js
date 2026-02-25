/**
 * Reminders Form Functionality
 * Handles custom interval toggle and title auto-fill for reminder create/edit forms.
 */

(function() {
  'use strict';

  // Toggle custom interval field visibility
  function toggleCustomInterval(frequencyValue) {
    const customGroup = document.getElementById('custom-interval-group');
    const customInput = document.getElementById('custom_interval_days');
    const frequencySelect = document.getElementById('frequency');

    if (!customGroup || !customInput) return;

    var isCustom = frequencyValue === 'custom';
    if (isCustom) {
      customGroup.classList.remove('hidden');
      customInput.required = true;
    } else {
      customGroup.classList.add('hidden');
      customInput.required = false;
    }

    // Update aria-expanded on the controlling select
    if (frequencySelect) {
      frequencySelect.setAttribute('aria-expanded', isCustom ? 'true' : 'false');
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    const frequencySelect = document.getElementById('frequency');
    if (!frequencySelect) return;

    // Handle frequency change
    frequencySelect.addEventListener('change', function() {
      toggleCustomInterval(this.value);
    });

    // Initialize custom interval visibility on page load
    toggleCustomInterval(frequencySelect.value);

    // Auto-fill title based on plant and reminder type (create form only)
    const plantSelect = document.getElementById('plant_id');
    const typeSelect = document.getElementById('reminder_type');
    const titleInput = document.getElementById('title');

    if (plantSelect && typeSelect && titleInput) {
      function updateTitle() {
        if (!titleInput.value || titleInput.dataset.autoFilled) {
          const plantText = plantSelect.options[plantSelect.selectedIndex]?.text || '';
          const typeText = typeSelect.options[typeSelect.selectedIndex]?.text || '';

          if (plantText && plantText !== 'Select a plant...' && typeText) {
            titleInput.value = `${typeText} - ${plantText}`;
            titleInput.dataset.autoFilled = 'true';
          }
        }
      }

      plantSelect.addEventListener('change', updateTitle);
      typeSelect.addEventListener('change', updateTitle);

      // Clear auto-filled flag when user manually edits
      titleInput.addEventListener('input', function() {
        if (this.value !== titleInput.dataset.previousValue) {
          delete titleInput.dataset.autoFilled;
        }
        titleInput.dataset.previousValue = this.value;
      });

      // Auto-fill title on page load if plant is pre-selected
      if (plantSelect.value && plantSelect.value !== '') {
        updateTitle();
      }
    }
  });
})();
