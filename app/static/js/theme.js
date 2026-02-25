/**
 * PlantCareAI Theme Manager
 * Handles light/dark/auto theme switching with database persistence
 * WCAG 2.1 AAA compliant with system preference support
 */

class ThemeManager {
  constructor() {
    // Priority: server-side theme (from meta tag) > localStorage > default 'auto'
    const themeMeta = document.querySelector('meta[name="x-initial-theme"]');
    const serverTheme = themeMeta ? themeMeta.content : null;
    const localTheme = localStorage.getItem('theme');

    // Use server theme if available, otherwise use localStorage, otherwise default to 'auto'
    this.theme = serverTheme || localTheme || 'auto';

    // Sync localStorage with server theme if they differ
    if (serverTheme && serverTheme !== localTheme) {
      localStorage.setItem('theme', serverTheme);
    }

    // Media query for system dark mode preference
    this.darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');

    // Apply theme immediately (prevent flash)
    this.applyTheme();

    // Watch for system preference changes
    this.watchSystemPreference();
  }

  /**
   * Determines if dark mode should be active
   * @returns {boolean}
   */
  isDarkMode() {
    if (this.theme === 'dark') return true;
    if (this.theme === 'light') return false;
    // 'auto' mode - follow system preference
    return this.darkModeQuery.matches;
  }

  /**
   * Applies the current theme to the document
   * Updates <html> element's class and data attribute
   */
  applyTheme() {
    const htmlElement = document.documentElement;
    const isDark = this.isDarkMode();

    // Update class for Tailwind dark mode
    if (isDark) {
      htmlElement.classList.add('dark');
    } else {
      htmlElement.classList.remove('dark');
    }

    // Update data attribute for JavaScript access
    htmlElement.setAttribute('data-theme', this.theme);

    // Update theme toggle UI if it exists
    this.updateToggleUI();
  }

  /**
   * Sets a new theme preference
   * @param {string} mode - 'light', 'dark', or 'auto'
   * @param {boolean} syncWithServer - Whether to save to database (default: true)
   */
  async setTheme(mode, syncWithServer = true) {
    // Validate input
    if (!['light', 'dark', 'auto'].includes(mode)) {
      // Invalid theme mode, fail silently
      return;
    }

    // Update local state
    this.theme = mode;
    localStorage.setItem('theme', mode);

    // Apply theme immediately
    this.applyTheme();

    // Sync with database if requested
    if (syncWithServer) {
      await this.syncWithDatabase();
    }

    // Dispatch custom event for other components
    window.dispatchEvent(new CustomEvent('themechange', {
      detail: { theme: mode, isDark: this.isDarkMode() }
    }));
  }

  /**
   * Watches for system preference changes (for 'auto' mode)
   */
  watchSystemPreference() {
    // Modern browsers
    if (this.darkModeQuery.addEventListener) {
      this.darkModeQuery.addEventListener('change', (e) => {
        if (this.theme === 'auto') {
          this.applyTheme();
        }
      });
    }
    // Legacy browsers
    else if (this.darkModeQuery.addListener) {
      this.darkModeQuery.addListener((e) => {
        if (this.theme === 'auto') {
          this.applyTheme();
        }
      });
    }
  }

  /**
   * Syncs theme preference with database
   * @returns {Promise<boolean>}
   */
  async syncWithDatabase() {
    try {
      const response = await fetch('/api/v1/user/theme', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({ theme: this.theme })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();

      if (!data.success) {
        // Failed to save theme preference, fail silently
        return false;
      }

      return true;

    } catch (error) {
      // Silently fail - localStorage still works
      return false;
    }
  }

  /**
   * Updates theme toggle UI elements
   * Looks for elements with data-theme-toggle attribute
   */
  updateToggleUI() {
    const toggles = document.querySelectorAll('[data-theme-toggle]');

    toggles.forEach(toggle => {
      const targetTheme = toggle.getAttribute('data-theme-value');

      // Update active state
      if (targetTheme === this.theme) {
        toggle.classList.add('active');
        toggle.setAttribute('aria-pressed', 'true');
      } else {
        toggle.classList.remove('active');
        toggle.setAttribute('aria-pressed', 'false');
      }
    });

    // Update theme icon if present
    const themeIcon = document.querySelector('[data-theme-icon]');
    if (themeIcon) {
      const icons = {
        light: '☀️',
        dark: '🌙',
        auto: '🌓'
      };
      themeIcon.textContent = icons[this.theme] || icons.auto;
    }
  }

  /**
   * Initialize theme toggle buttons and radio inputs
   * Call this after DOM is loaded
   */
  initializeToggles() {
    const toggles = document.querySelectorAll('[data-theme-toggle]');

    toggles.forEach(toggle => {
      // Handle radio inputs differently from buttons
      if (toggle.type === 'radio') {
        toggle.addEventListener('change', (e) => {
          if (toggle.checked) {
            const targetTheme = toggle.getAttribute('data-theme-value');
            this.setTheme(targetTheme);
          }
        });
      } else {
        // Buttons and other toggle elements
        toggle.addEventListener('click', (e) => {
          e.preventDefault();
          const targetTheme = toggle.getAttribute('data-theme-value');
          this.setTheme(targetTheme);
        });
      }
    });
  }

  /**
   * Gets current theme state
   * @returns {object}
   */
  getState() {
    return {
      theme: this.theme,
      isDark: this.isDarkMode(),
      systemPrefersDark: this.darkModeQuery.matches
    };
  }
}

// Initialize theme manager immediately (before DOM loads to prevent flash)
window.themeManager = new ThemeManager();

// Initialize toggle buttons after DOM loads
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.themeManager.initializeToggles();
  });
} else {
  // DOM already loaded
  window.themeManager.initializeToggles();
}

// Expose for console debugging
if (typeof window !== 'undefined') {
  window.ThemeManager = ThemeManager;
}
