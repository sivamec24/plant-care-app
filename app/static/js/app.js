/**
 * Client-side interactivity.
 *
 * - Prefill form from preset buttons (plant, question, context, optional city)
 * - One overlay for both columns; announces aria-busy/live
 * - Keeps select enabled so value posts; text inputs become readOnly while submitting
 * - After submit, focuses the Answer region and scrolls into view (reduced-motion aware)
 * - Units toggle (°F default, persisted to localStorage) controls presentation only
 * - Restores interactivity on bfcache navigation
 * - Reset button clears fields to a clean state (not just HTML "reset" to initial values)
 */

(function () {
  'use strict';
  const form = document.getElementById('ask-form');
  const presets = document.getElementById('presets');

  const plantInput = document.getElementById('plant');
  const cityInput = document.getElementById('city');
  const contextSelect = document.getElementById('care_context');
  const questionInput = document.getElementById('question');
  const submitBtn = document.getElementById('submit-btn');
  const resetBtn = document.getElementById('reset-btn');

  const gridTwo = document.querySelector('.grid-two');
  const answerCard = document.querySelector('.answer-card');

  // --- User Plants Selection (Plant-Aware AI) ---
  const userPlantsGrid = document.getElementById('user-plants-grid');
  if (userPlantsGrid) {
    userPlantsGrid.addEventListener('click', (e) => {
      const btn = e.target.closest('.plant-select-btn');
      if (!btn) return;

      const { plantId, plantName, plantSpecies, plantLocation } = btn.dataset;

      // Store selected plant ID for AI context
      const selectedPlantInput = document.getElementById('selected_plant_id');
      if (selectedPlantInput && plantId) {
        selectedPlantInput.value = plantId;
      }

      // Fill form with plant data
      if (plantInput && plantName) {
        // Use species if available, otherwise just name
        plantInput.value = plantSpecies && plantSpecies.trim() !== ''
          ? `${plantName} (${plantSpecies})`
          : plantName;
      }

      // Set location context
      if (contextSelect && plantLocation) {
        contextSelect.value = plantLocation;
      }

      // Visual feedback - highlight selected plant
      document.querySelectorAll('.plant-select-btn').forEach(btn => {
        btn.classList.remove('!border-emerald-500', '!dark:border-emerald-400', '!bg-emerald-50', '!dark:bg-emerald-900/20');
      });
      btn.classList.add('!border-emerald-500', '!dark:border-emerald-400', '!bg-emerald-50', '!dark:bg-emerald-900/20');

      // Focus question input for quick typing
      if (questionInput) questionInput.focus();
    });
  }

  // --- Presets ---
  if (presets) {
    presets.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-plant]');
      if (!btn) return;

      const { plant, city, question, context } = btn.dataset;

      if (typeof plant === 'string') plantInput.value = plant;
      if (typeof city === 'string' && city.trim() !== '') cityInput.value = city;
      if (typeof question === 'string') questionInput.value = question;
      if (typeof context === 'string') contextSelect.value = context;

      // Clear plant selection highlight when using presets
      if (userPlantsGrid) {
        document.querySelectorAll('.plant-select-btn').forEach(btn => {
          btn.classList.remove('!border-emerald-500', '!dark:border-emerald-400', '!bg-emerald-50', '!dark:bg-emerald-900/20');
        });
      }

      // Clear selected plant ID (presets don't provide plant context)
      const selectedPlantInput = document.getElementById('selected_plant_id');
      if (selectedPlantInput) selectedPlantInput.value = '';

      // Focus submit button after preset selection
      if (submitBtn) submitBtn.focus();
    });
  }

  // --- Reset (clear) button ---
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      // Clear all fields to blank, and reset context to the default option
      if (plantInput) plantInput.value = '';
      if (cityInput) cityInput.value = '';
      if (questionInput) questionInput.value = '';
      if (contextSelect) contextSelect.value = 'indoor_potted';

      // Clear plant selection highlight
      if (userPlantsGrid) {
        document.querySelectorAll('.plant-select-btn').forEach(btn => {
          btn.classList.remove('!border-emerald-500', '!dark:border-emerald-400', '!bg-emerald-50', '!dark:bg-emerald-900/20');
        });
      }

      // Clear selected plant ID
      const selectedPlantInput = document.getElementById('selected_plant_id');
      if (selectedPlantInput) selectedPlantInput.value = '';

      // Put focus in the first field for quick typing
      plantInput?.focus();
    });
  }

  // --- Plant-themed loading messages ---
  const plantLoadingPhrases = [
    'Germinating…',
    'Sprouting…',
    'Taking root…',
    'Growing leaves…',
    'Photosynthesizing…',
    'Soaking up sunshine…',
    'Absorbing nutrients…',
    'Unfurling petals…',
    'Reaching for the light…',
    'Blossoming…'
  ];

  let loadingPhraseInterval = null;
  let currentPhraseIndex = 0;

  function rotateLoadingMessage() {
    const loadingMessage = document.getElementById('loading-message');
    if (!loadingMessage) return;

    currentPhraseIndex = (currentPhraseIndex + 1) % plantLoadingPhrases.length;
    loadingMessage.textContent = plantLoadingPhrases[currentPhraseIndex];
  }

  function startLoadingRotation() {
    const loadingMessage = document.getElementById('loading-message');
    if (!loadingMessage) return;

    // Reset to first message
    currentPhraseIndex = 0;
    loadingMessage.textContent = plantLoadingPhrases[currentPhraseIndex];

    // Rotate through messages every 4 seconds (longer interval avoids excessive screen reader announcements)
    loadingPhraseInterval = setInterval(rotateLoadingMessage, 4000);
  }

  function stopLoadingRotation() {
    if (loadingPhraseInterval) {
      clearInterval(loadingPhraseInterval);
      loadingPhraseInterval = null;
    }
  }

  // --- Submit loading state ---
  function setSubmitting(on) {
    if (gridTwo) {
      gridTwo.classList.toggle('is-submitting', !!on);
      gridTwo.setAttribute('aria-busy', on ? 'true' : 'false');
    }
    if (submitBtn) submitBtn.disabled = !!on;
    ['plant','city','question'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.readOnly = !!on;
    });

    // Start/stop loading message rotation
    if (on) {
      startLoadingRotation();
    } else {
      stopLoadingRotation();
    }
  }

  function scrollIntoViewPref(el) {
    if (!el) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) el.scrollIntoView();
    else el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  if (form) {
    form.addEventListener('submit', (e) => {
      // Validate question field before submission
      const questionValue = questionInput ? questionInput.value.trim() : '';

      if (!questionValue) {
        e.preventDefault();

        // Focus the question field
        if (questionInput) questionInput.focus();

        // Show validation message (browser will handle with HTML5 required attribute)
        if (questionInput && questionInput.reportValidity) {
          questionInput.reportValidity();
        }

        return false;
      }

      // Check maxlength (1200 characters)
      if (questionValue.length > 1200) {
        e.preventDefault();

        if (questionInput) {
          questionInput.focus();
          questionInput.setCustomValidity('Question must be under 1200 characters.');
          questionInput.reportValidity();
          questionInput.setCustomValidity(''); // Clear after showing
        }

        return false;
      }

      // Clear any custom validity before submitting
      if (questionInput) questionInput.setCustomValidity('');

      try { sessionStorage.setItem('pcai-just-submitted', '1'); } catch (_) {}
      setSubmitting(true);
    });
    window.addEventListener('pageshow', (ev) => {
      if (ev.persisted) setSubmitting(false);
    });
  }

  window.addEventListener('DOMContentLoaded', () => {
    // Focus answer after successful submit
    let justSubmitted = false;
    try {
      justSubmitted = sessionStorage.getItem('pcai-just-submitted') === '1';
      sessionStorage.removeItem('pcai-just-submitted');
    } catch (_) {}
    const hasAnswer = !!document.querySelector('.answer-card .prewrap');
    if (justSubmitted && hasAnswer && answerCard) {
      try { answerCard.focus({ preventScroll: true }); } catch (_) {}
      scrollIntoViewPref(answerCard);
    }

    // Units toggle (persisted) — default °F
    const weatherSection = document.getElementById('weather-section');
    if (weatherSection) {
      const saved = (localStorage.getItem('pcai-units') || 'f').toLowerCase();
      if (saved === 'c' || saved === 'f') {
        weatherSection.setAttribute('data-units', saved);
        const radio = document.querySelector(`.units-toggle input[value="${saved}"]`);
        if (radio) radio.checked = true;
      } else {
        weatherSection.setAttribute('data-units', 'f');
        const radioF = document.querySelector('.units-toggle input[value="f"]');
        if (radioF) radioF.checked = true;
      }

      document.querySelectorAll('.units-toggle input[name="units"]').forEach((input) => {
        input.addEventListener('change', () => {
          const val = input.value === 'c' ? 'c' : 'f';
          weatherSection.setAttribute('data-units', val);
          try { localStorage.setItem('pcai-units', val); } catch (_) {}
        });
      });
    }
  });

  // Footer year
  const yearEl = document.getElementById('copyright-year');
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  // --- User Menu Dropdown (WCAG Compliant) ---
  const userMenuBtn = document.getElementById('user-menu-btn');
  const userMenuDropdown = document.getElementById('user-menu-dropdown');

  if (userMenuBtn && userMenuDropdown) {
    // Toggle dropdown on click
    userMenuBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      e.preventDefault();
      const isExpanded = userMenuBtn.getAttribute('aria-expanded') === 'true';

      if (isExpanded) {
        closeUserMenu();
      } else {
        openUserMenu();
      }
    });

    // Open menu with keyboard (Enter/Space handled by click event)
    userMenuBtn.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (userMenuBtn.getAttribute('aria-expanded') !== 'true') {
          openUserMenu();
        }
        // Focus first menu item
        const firstLink = userMenuDropdown.querySelector('a[role="menuitem"]');
        if (firstLink) firstLink.focus();
      }
    });

    // Close on Escape key (WCAG 2.1.1 Keyboard requirement)
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && userMenuBtn.getAttribute('aria-expanded') === 'true') {
        closeUserMenu();
        userMenuBtn.focus(); // Return focus to button
      }
    });

    // Close on outside click
    document.addEventListener('click', function(e) {
      if (userMenuBtn.getAttribute('aria-expanded') === 'true') {
        if (!userMenuDropdown.contains(e.target) && e.target !== userMenuBtn) {
          closeUserMenu();
        }
      }
    });

    // Arrow key + Tab navigation in dropdown (WCAG 2.4.3)
    userMenuDropdown.addEventListener('keydown', function(e) {
      const menuItems = Array.from(userMenuDropdown.querySelectorAll('a[role="menuitem"]'));
      const currentIndex = menuItems.indexOf(document.activeElement);

      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        let nextIndex;
        if (e.key === 'ArrowDown') {
          nextIndex = (currentIndex + 1) % menuItems.length;
        } else {
          nextIndex = currentIndex <= 0 ? menuItems.length - 1 : currentIndex - 1;
        }
        if (menuItems[nextIndex]) {
          menuItems[nextIndex].focus();
        }
      }

      // Tab dismisses menu and returns focus to natural tab order
      if (e.key === 'Tab') {
        closeUserMenu();
      }
    });

    function openUserMenu() {
      userMenuDropdown.classList.remove('hidden');
      userMenuBtn.setAttribute('aria-expanded', 'true');
    }

    function closeUserMenu() {
      userMenuDropdown.classList.add('hidden');
      userMenuBtn.setAttribute('aria-expanded', 'false');
    }
  }

  // --- Mobile Hamburger Menu Toggle ---
  const mobileMenuBtn = document.getElementById('mobile-menu-btn');
  const mobileMenuPanel = document.getElementById('mobile-menu-panel');

  if (mobileMenuBtn && mobileMenuPanel) {
    mobileMenuBtn.addEventListener('click', function() {
      const isExpanded = mobileMenuBtn.getAttribute('aria-expanded') === 'true';
      if (isExpanded) {
        mobileMenuPanel.classList.add('hidden');
        mobileMenuBtn.setAttribute('aria-expanded', 'false');
      } else {
        mobileMenuPanel.classList.remove('hidden');
        mobileMenuBtn.setAttribute('aria-expanded', 'true');
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && mobileMenuBtn.getAttribute('aria-expanded') === 'true') {
        mobileMenuPanel.classList.add('hidden');
        mobileMenuBtn.setAttribute('aria-expanded', 'false');
        mobileMenuBtn.focus();
      }
    });

    // Close on outside click
    document.addEventListener('click', function(e) {
      if (mobileMenuBtn.getAttribute('aria-expanded') === 'true') {
        if (!mobileMenuPanel.contains(e.target) && e.target !== mobileMenuBtn && !mobileMenuBtn.contains(e.target)) {
          mobileMenuPanel.classList.add('hidden');
          mobileMenuBtn.setAttribute('aria-expanded', 'false');
        }
      }
    });

    // Tab past last menu item closes the menu
    mobileMenuPanel.addEventListener('keydown', function(e) {
      if (e.key !== 'Tab') return;
      var links = mobileMenuPanel.querySelectorAll('a[href]');
      if (!links.length) return;
      var lastLink = links[links.length - 1];
      var firstLink = links[0];
      if (!e.shiftKey && document.activeElement === lastLink) {
        mobileMenuPanel.classList.add('hidden');
        mobileMenuBtn.setAttribute('aria-expanded', 'false');
      } else if (e.shiftKey && document.activeElement === firstLink) {
        mobileMenuPanel.classList.add('hidden');
        mobileMenuBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // --- Flash Message Dismissal (WCAG Compliant) ---
  const flashMessages = document.querySelectorAll('.flash');

  flashMessages.forEach(function(flash) {
    const closeBtn = flash.querySelector('.flash-dismiss-btn');

    if (closeBtn) {
      // Click handler
      closeBtn.addEventListener('click', function() {
        dismissFlash(flash);
      });

      // Keyboard handler (Enter/Space)
      closeBtn.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          dismissFlash(flash);
        }
      });
    }
  });

  function dismissFlash(flashEl) {
    // Check if user prefers reduced motion
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (prefersReducedMotion) {
      // Instant removal
      flashEl.remove();
    } else {
      // Fade out animation
      flashEl.style.opacity = '0';
      flashEl.style.transform = 'translateY(-10px)';
      flashEl.style.transition = 'opacity 0.3s ease, transform 0.3s ease';

      setTimeout(function() {
        flashEl.remove();
      }, 300);
    }
  }

  // --- Focus Management: move focus to error alerts on page load (WCAG 3.3.1) ---
  var errorAlert = document.querySelector('[role="alert"]');
  if (errorAlert) {
    errorAlert.setAttribute('tabindex', '-1');
    errorAlert.focus({ preventScroll: false });
  }

  // --- Flash Message Dismissal (Event Delegation for base.html alerts) ---
  document.addEventListener('click', function(e) {
    const dismissBtn = e.target.closest('.flash-dismiss-btn');
    if (dismissBtn) {
      const alertEl = dismissBtn.closest('[role="alert"]');
      if (alertEl) {
        dismissFlash(alertEl);
      }
    }
  });

  // --- Legal Banner Acknowledgment ---
  var legalBtn = document.getElementById('legal-acknowledge-btn');
  if (legalBtn) {
    legalBtn.addEventListener('click', function() {
      fetch('/api/v1/acknowledge-legal', {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type': 'application/json'
        }
      }).then(function(response) {
        return response.json();
      }).then(function(data) {
        if (data.success) {
          var container = document.getElementById('legal-banner-container');
          if (container) {
            dismissFlash(container);
          }
        }
      });
    });
  }

  // --- Form Confirmation Handler (CSP-compliant alternative to onclick confirm) ---
  document.addEventListener('submit', function(e) {
    const form = e.target;
    const confirmMessage = form.dataset.confirm;
    if (confirmMessage && !confirm(confirmMessage)) {
      e.preventDefault();
    }
  });

  // Footer year handled above in DOMContentLoaded
})();
