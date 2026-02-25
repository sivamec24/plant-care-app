/**
 * Care Assistant Page Functionality
 * Handles scroll-to-answer, preset chips, plant selection, and carousel.
 */

(function() {
  'use strict';

  // Scroll to answer box when page loads with an answer
  const answerBox = document.getElementById('answer-box');
  const hasAnswer = answerBox && answerBox.querySelector('.prewrap');
  if (hasAnswer) {
    // Small delay to ensure page layout is complete
    setTimeout(function() {
      // Get the sticky header height to offset the scroll position
      const header = document.querySelector('header.sticky');
      const headerHeight = header ? header.offsetHeight : 0;
      const padding = 16; // Extra padding for visual breathing room

      // Calculate scroll position: element top minus header and padding
      const elementTop = answerBox.getBoundingClientRect().top + window.scrollY;
      const scrollTarget = elementTop - headerHeight - padding;

      window.scrollTo({
        top: scrollTarget,
        behavior: 'smooth'
      });
    }, 100);
  }

  // Helper function to scroll to form with header offset
  function scrollToForm() {
    const askForm = document.getElementById('ask-form');
    const formCard = askForm ? askForm.closest('.card') : null;
    if (formCard) {
      const header = document.querySelector('header.sticky');
      const headerHeight = header ? header.offsetHeight : 0;
      const padding = 16;
      const elementTop = formCard.getBoundingClientRect().top + window.scrollY;
      const scrollTarget = elementTop - headerHeight - padding;
      window.scrollTo({ top: scrollTarget, behavior: 'smooth' });
    }
  }

  // Preset chip click handlers (unauthenticated users only)
  document.querySelectorAll('.preset-chip').forEach(function(chip) {
    chip.addEventListener('click', function(e) {
      e.preventDefault();

      // Get data attributes
      const plant = this.dataset.plant;
      const question = this.dataset.question;
      const context = this.dataset.context;

      // Get form fields
      const plantField = document.getElementById('plant');
      const questionField = document.getElementById('question');
      const contextField = document.getElementById('care_context');

      // Always replace all fields with preset values
      if (plant && plantField) {
        plantField.value = plant;
      }

      if (question && questionField) {
        questionField.value = question;
      }

      if (context && contextField) {
        contextField.value = context;
      }

      // Scroll to form so user can see what was filled
      scrollToForm();

      // Focus the question field (most likely next action)
      if (questionField) {
        questionField.focus();
      }
    });
  });

  // Plant selection click handlers (authenticated users)
  document.querySelectorAll('.plant-select-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault();

      // Get data attributes
      const plantId = this.dataset.plantId;
      const plantName = this.dataset.plantName;
      const plantLocation = this.dataset.plantLocation || 'indoor_potted';

      // Get form fields
      const plantField = document.getElementById('plant');
      const contextField = document.getElementById('care_context');
      const selectedPlantIdField = document.getElementById('selected_plant_id');
      const questionField = document.getElementById('question');

      // Fill plant name (always overwrite to ensure consistency)
      if (plantName && plantField) {
        plantField.value = plantName;
      }

      // Fill care context from plant's location
      if (plantLocation && contextField) {
        contextField.value = plantLocation;
      }

      // Store selected plant ID for AI context
      if (plantId && selectedPlantIdField) {
        selectedPlantIdField.value = plantId;
      }

      // Visual feedback: highlight selected plant
      document.querySelectorAll('.plant-select-btn').forEach(function(b) {
        b.classList.remove('ring-2', 'ring-emerald-500', 'dark:ring-emerald-400');
      });
      this.classList.add('ring-2', 'ring-emerald-500', 'dark:ring-emerald-400');

      // Scroll to form so user can see what was filled
      scrollToForm();

      // Focus the question field (most likely next action)
      if (questionField) {
        questionField.focus();
      }
    });
  });

  // Highlight pre-selected plant on page load (from URL plant_id param)
  (function() {
    const selectedPlantIdField = document.getElementById('selected_plant_id');
    if (selectedPlantIdField && selectedPlantIdField.value) {
      const preSelectedId = selectedPlantIdField.value;
      const matchingBtn = document.querySelector('.plant-select-btn[data-plant-id="' + preSelectedId + '"]');
      if (matchingBtn) {
        // Add highlight ring
        matchingBtn.classList.add('ring-2', 'ring-emerald-500', 'dark:ring-emerald-400');
        // Scroll the carousel to show the selected plant
        const scrollContainer = document.getElementById('plants-scroll-container');
        if (scrollContainer) {
          // Calculate scroll position to center the selected plant
          const containerRect = scrollContainer.getBoundingClientRect();
          const btnRect = matchingBtn.getBoundingClientRect();
          const scrollOffset = btnRect.left - containerRect.left - (containerRect.width / 2) + (btnRect.width / 2);
          scrollContainer.scrollLeft += scrollOffset;
        }
      }
    }
  })();

  // Plant carousel scroll functionality with gradient indicators
  (function() {
    const scrollContainer = document.getElementById('plants-scroll-container');
    const scrollLeftBtn = document.getElementById('scroll-left-btn');
    const scrollRightBtn = document.getElementById('scroll-right-btn');
    const gradientLeft = document.getElementById('gradient-left');
    const gradientRight = document.getElementById('gradient-right');

    // Only run if elements exist (user has plants)
    if (!scrollContainer || !scrollLeftBtn || !scrollRightBtn) {
      return;
    }

    /**
     * Update scroll button states and gradient visibility
     * based on current scroll position.
     */
    function updateScrollState() {
      const scrollLeft = scrollContainer.scrollLeft;
      const scrollWidth = scrollContainer.scrollWidth;
      const clientWidth = scrollContainer.clientWidth;
      const maxScroll = scrollWidth - clientWidth;

      // Update left button and gradient
      const isAtStart = scrollLeft <= 1; // 1px threshold for rounding
      scrollLeftBtn.disabled = isAtStart;
      if (gradientLeft) {
        gradientLeft.style.opacity = isAtStart ? '0' : '1';
      }

      // Update right button and gradient
      const isAtEnd = scrollLeft >= maxScroll - 1; // 1px threshold for rounding
      scrollRightBtn.disabled = isAtEnd;
      if (gradientRight) {
        gradientRight.style.opacity = isAtEnd ? '0' : '1';
      }

      // Update ARIA labels for accessibility
      scrollLeftBtn.setAttribute('aria-disabled', isAtStart ? 'true' : 'false');
      scrollRightBtn.setAttribute('aria-disabled', isAtEnd ? 'true' : 'false');
    }

    /**
     * Scroll the carousel by approximately one plant width.
     * @param {string} direction - 'left' or 'right'
     */
    function scrollCarousel(direction) {
      const plantWidth = 112 + 12; // w-28 (112px) + gap-3 (12px)
      const scrollAmount = plantWidth * 2; // Scroll 2 plants at a time
      const currentScroll = scrollContainer.scrollLeft;
      const targetScroll = direction === 'left'
        ? currentScroll - scrollAmount
        : currentScroll + scrollAmount;

      scrollContainer.scrollTo({
        left: targetScroll,
        behavior: 'smooth'
      });
    }

    // Event listeners for scroll buttons
    scrollLeftBtn.addEventListener('click', () => scrollCarousel('left'));
    scrollRightBtn.addEventListener('click', () => scrollCarousel('right'));

    // Update state on scroll
    scrollContainer.addEventListener('scroll', updateScrollState);

    // Update state on window resize
    window.addEventListener('resize', updateScrollState);

    // Initialize state on page load
    updateScrollState();

    // Re-check after images load (they might affect scrollWidth)
    window.addEventListener('load', () => {
      setTimeout(updateScrollState, 100);
    });
  })();
})();

// --- Copy/Share Answer Functionality ---
(function() {
  'use strict';

  const copyBtn = document.getElementById('copy-answer-btn');
  const shareBtn = document.getElementById('share-answer-btn');

  if (!copyBtn && !shareBtn) return;

  // Map care_context values to readable labels
  const contextLabels = {
    'indoor_potted': 'Indoor, potted',
    'outdoor_potted': 'Outdoor, potted',
    'outdoor_bed': 'Outdoor, in-ground',
    'greenhouse': 'Greenhouse',
    'office': 'Office'
  };

  /**
   * Build formatted text for copying/sharing
   */
  function buildShareText(btn) {
    const question = btn.dataset.question || '';
    const plant = btn.dataset.plant || '';
    const city = btn.dataset.city || '';
    const context = btn.dataset.context || '';
    const answer = btn.dataset.answer || '';

    let text = 'Q: ' + question + '\n';

    // Build context line with non-empty values
    const contextParts = [];
    if (plant) contextParts.push('Plant: ' + plant);
    if (context) contextParts.push('Location: ' + (contextLabels[context] || context));
    if (city) contextParts.push('City: ' + city);

    if (contextParts.length > 0) {
      text += contextParts.join(' | ') + '\n';
    }

    text += '\nA: ' + answer + '\n\n— PlantCareAI';

    return text;
  }

  /**
   * Copy text to clipboard with feedback
   */
  async function copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      // Fallback for older browsers
      var textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand('copy');
        document.body.removeChild(textarea);
        return true;
      } catch (e) {
        document.body.removeChild(textarea);
        return false;
      }
    }
  }

  /**
   * Show "Copied!" feedback on button
   */
  function showCopiedFeedback(btn) {
    var textEl = btn.querySelector('#copy-text') || btn.querySelector('span:last-child');
    var iconEl = btn.querySelector('#copy-icon') || btn.querySelector('span:first-child');
    var originalText = textEl.textContent;
    var originalIcon = iconEl.textContent;

    textEl.textContent = 'Copied!';
    iconEl.textContent = '✓';
    btn.classList.add('!bg-emerald-100', 'dark:!bg-emerald-900/30');

    setTimeout(function() {
      textEl.textContent = originalText;
      iconEl.textContent = originalIcon;
      btn.classList.remove('!bg-emerald-100', 'dark:!bg-emerald-900/30');
    }, 2000);
  }

  // Copy button handler
  if (copyBtn) {
    copyBtn.addEventListener('click', async function() {
      var text = buildShareText(this);
      var success = await copyToClipboard(text);
      if (success) {
        showCopiedFeedback(this);
      }
    });
  }

  // Share button handler
  if (shareBtn) {
    shareBtn.addEventListener('click', async function() {
      var text = buildShareText(this);

      // Check if Web Share API is available
      if (navigator.share) {
        try {
          // Embed URL in text - some apps ignore the url parameter and only share text
          var shareText = text + '\n\nhttps://plantcareai.app/ask';
          await navigator.share({
            title: 'Plant Care Advice from PlantCareAI',
            text: shareText
          });
        } catch (err) {
          // User cancelled or share failed - fall back to copy
          if (err.name !== 'AbortError') {
            var success = await copyToClipboard(text);
            if (success) {
              showCopiedFeedback(copyBtn || this);
            }
          }
        }
      } else {
        // Desktop fallback - copy to clipboard
        var success = await copyToClipboard(text);
        if (success) {
          showCopiedFeedback(copyBtn || this);
        }
      }
    });
  }
})();

// --- Micro-Feedback Functionality ---
(function() {
  'use strict';

  var feedbackSection = document.getElementById('feedback-section');
  var feedbackButtons = document.getElementById('feedback-buttons');
  var feedbackThanks = document.getElementById('feedback-thanks');
  var feedbackDataEl = document.getElementById('feedback-data');

  if (!feedbackSection || !feedbackButtons || !feedbackDataEl) return;

  // Parse feedback context data
  var feedbackData = {};
  try {
    feedbackData = JSON.parse(feedbackDataEl.textContent);
  } catch (e) {
    console.error('Failed to parse feedback data');
    return;
  }

  // Check if feedback already submitted (session storage)
  var feedbackKey = 'pcai-feedback-' + btoa(feedbackData.question || '').slice(0, 20);
  if (sessionStorage.getItem(feedbackKey)) {
    feedbackButtons.classList.add('hidden');
    feedbackThanks.classList.remove('hidden');
    return;
  }

  // Handle feedback button clicks
  feedbackButtons.addEventListener('click', async function(e) {
    var btn = e.target.closest('.feedback-btn');
    if (!btn) return;

    var rating = btn.dataset.rating;
    if (!rating) return;

    // Disable buttons immediately
    feedbackButtons.querySelectorAll('.feedback-btn').forEach(function(b) {
      b.disabled = true;
      b.classList.add('opacity-50', 'cursor-not-allowed');
    });

    // Highlight selected button
    btn.classList.remove('opacity-50');
    btn.classList.add('ring-2', 'ring-emerald-500');

    try {
      var response = await fetch('/api/v1/feedback/answer', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
          rating: rating,
          question: feedbackData.question,
          plant: feedbackData.plant,
          city: feedbackData.city,
          care_context: feedbackData.care_context,
          ai_source: feedbackData.ai_source
        })
      });

      if (response.ok) {
        // Mark as submitted
        sessionStorage.setItem(feedbackKey, rating);

        // Show thanks message
        feedbackButtons.classList.add('hidden');
        feedbackThanks.classList.remove('hidden');
      } else {
        // Re-enable buttons on error
        feedbackButtons.querySelectorAll('.feedback-btn').forEach(function(b) {
          b.disabled = false;
          b.classList.remove('opacity-50', 'cursor-not-allowed');
        });
        btn.classList.remove('ring-2', 'ring-emerald-500');
      }
    } catch (err) {
      // Re-enable buttons on network error
      feedbackButtons.querySelectorAll('.feedback-btn').forEach(function(b) {
        b.disabled = false;
        b.classList.remove('opacity-50', 'cursor-not-allowed');
      });
      btn.classList.remove('ring-2', 'ring-emerald-500');
    }
  });
})();
