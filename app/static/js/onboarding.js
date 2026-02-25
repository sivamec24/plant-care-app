/**
 * Plant Onboarding Wizard
 * Multi-step wizard for user preferences, adding a plant, and setting reminders.
 */

(function() {
  'use strict';

  let currentStep = 1;
  const totalSteps = 4;
  let plantId = null; // Will be set after step 3 submission

  // Store preferences from step 2
  let userPreferences = {
    experience_level: '',
    primary_goal: '',
    time_commitment: '',
    environment_preference: ''
  };

  function updateProgress() {
    const stepEl = document.getElementById('current-step');
    const progressBar = document.getElementById('progress-bar');
    if (stepEl) stepEl.textContent = currentStep;
    if (progressBar) progressBar.style.width = `${(currentStep / totalSteps) * 100}%`;
  }

  function showStep(step) {
    // Hide all steps
    document.querySelectorAll('.step-content').forEach(el => {
      el.classList.add('hidden');
    });

    // Show current step
    const stepEl = document.getElementById(`step-${step}`);
    if (stepEl) stepEl.classList.remove('hidden');

    // Update progress
    updateProgress();

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function nextStep() {
    if (currentStep < totalSteps) {
      // If moving from step 1 to step 2, copy marketing opt-in preference
      if (currentStep === 1) {
        const marketingCheckbox = document.getElementById('onboarding_marketing_opt_in');
        const marketingHidden = document.getElementById('marketing_opt_in_hidden');
        if (marketingCheckbox && marketingHidden) {
          marketingHidden.value = marketingCheckbox.checked ? 'on' : '';
        }
      }

      currentStep++;
      showStep(currentStep);
    }
  }

  function prevStep() {
    if (currentStep > 1) {
      currentStep--;
      showStep(currentStep);
    }
  }

  function savePreferences() {
    // Get selected values from preferences form
    const form = document.getElementById('preferences-form');
    if (!form) return;

    // Get selected radio values
    const experienceEl = form.querySelector('input[name="experience_level"]:checked');
    const goalEl = form.querySelector('input[name="primary_goal"]:checked');
    const timeEl = form.querySelector('input[name="time_commitment"]:checked');
    const envEl = form.querySelector('input[name="environment_preference"]:checked');

    // Store preferences
    userPreferences.experience_level = experienceEl ? experienceEl.value : '';
    userPreferences.primary_goal = goalEl ? goalEl.value : '';
    userPreferences.time_commitment = timeEl ? timeEl.value : '';
    userPreferences.environment_preference = envEl ? envEl.value : '';

    // Copy to hidden fields in the plant form (step 3)
    copyPreferencesToHiddenFields();

    // Move to next step
    nextStep();
  }

  function skipPreferences() {
    // Clear preferences
    userPreferences = {
      experience_level: '',
      primary_goal: '',
      time_commitment: '',
      environment_preference: ''
    };

    // Move to next step
    nextStep();
  }

  function copyPreferencesToHiddenFields() {
    // Copy stored preferences to hidden fields in the plant form
    const expHidden = document.getElementById('pref_experience_level');
    const goalHidden = document.getElementById('pref_primary_goal');
    const timeHidden = document.getElementById('pref_time_commitment');
    const envHidden = document.getElementById('pref_environment_preference');

    if (expHidden) expHidden.value = userPreferences.experience_level;
    if (goalHidden) goalHidden.value = userPreferences.primary_goal;
    if (timeHidden) timeHidden.value = userPreferences.time_commitment;
    if (envHidden) envHidden.value = userPreferences.environment_preference;
  }

  function submitAndContinue() {
    const form = document.getElementById('onboarding-form');
    if (!form) return;

    // Ensure preferences are copied to hidden fields
    copyPreferencesToHiddenFields();

    const formData = new FormData(form);

    // Validate required fields
    const nameInput = document.getElementById('name');
    if (nameInput && !nameInput.value.trim()) {
      nameInput.focus();
      nameInput.reportValidity();
      return;
    }

    // Submit form via fetch to avoid page reload
    fetch(form.action, {
      method: 'POST',
      body: formData
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Store plant ID for step 4
        plantId = data.plant_id;

        // Move to step 4
        nextStep();
      } else {
        alert(data.message || 'Error creating plant. Please try again.');
      }
    })
    .catch(error => {
      console.error('Error:', error);
      alert('Error creating plant. Please try again.');
    });
  }

  function toggleReminderFields(skipChecked) {
    const frequencySelect = document.getElementById('watering_frequency');
    if (frequencySelect) {
      if (skipChecked) {
        frequencySelect.removeAttribute('required');
        frequencySelect.disabled = true;
      } else {
        frequencySelect.setAttribute('required', 'required');
        frequencySelect.disabled = false;
      }
    }
  }

  // Initialize when DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    // Only run on onboarding page
    if (!document.getElementById('step-1')) return;

    // Initialize first step
    showStep(1);

    // Event delegation for step navigation buttons
    document.addEventListener('click', function(e) {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;

      const action = btn.dataset.action;
      switch (action) {
        case 'next-step':
          nextStep();
          break;
        case 'prev-step':
          prevStep();
          break;
        case 'submit-continue':
          submitAndContinue();
          break;
        case 'save-preferences':
          savePreferences();
          break;
        case 'skip-preferences':
          skipPreferences();
          break;
      }
    });

    // Handle skip reminder checkbox
    const skipReminderCheckbox = document.getElementById('skip_reminder');
    if (skipReminderCheckbox) {
      skipReminderCheckbox.addEventListener('change', function() {
        toggleReminderFields(this.checked);
      });
    }
  });
})();
