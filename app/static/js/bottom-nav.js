/**
 * Bottom Navigation for Mobile
 * Provides app-like navigation experience on mobile devices
 */

(function() {
  'use strict';

  // Only initialize on mobile
  if (window.innerWidth > 768) return;

  let lastScrollTop = 0;
  let ticking = false;

  // Hide/show bottom nav on scroll (optional enhancement)
  function handleScroll() {
    if (ticking) return;

    window.requestAnimationFrame(() => {
      const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
      const bottomNav = document.querySelector('.bottom-nav');

      if (!bottomNav) {
        ticking = false;
        return;
      }

      // Hide on scroll down, show on scroll up
      if (scrollTop > lastScrollTop && scrollTop > 100) {
        // Scrolling down - hide nav
        bottomNav.classList.add('hidden');
      } else {
        // Scrolling up - show nav
        bottomNav.classList.remove('hidden');
      }

      lastScrollTop = scrollTop <= 0 ? 0 : scrollTop;
      ticking = false;
    });

    ticking = true;
  }

  // Set active state based on current page
  function setActiveNavItem() {
    const bottomNav = document.querySelector('.bottom-nav');
    if (!bottomNav) return;

    const currentPath = window.location.pathname;
    const navItems = bottomNav.querySelectorAll('.bottom-nav-item');

    navItems.forEach(item => {
      const href = item.getAttribute('href');

      // Remove active class from all
      item.classList.remove('active');

      // Add active class to matching item
      if (href === currentPath ||
          (href !== '/' && currentPath.startsWith(href))) {
        item.classList.add('active');
      }
    });
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function init() {
    setActiveNavItem();

    // Optional: Enable hide/show on scroll
    // Uncomment if you want this behavior
    // window.addEventListener('scroll', handleScroll, { passive: true });
  }

  // Re-check on window resize
  window.addEventListener('resize', () => {
    if (window.innerWidth > 768) {
      // Desktop view - remove any hidden class
      const bottomNav = document.querySelector('.bottom-nav');
      if (bottomNav) {
        bottomNav.classList.remove('hidden');
      }
    }
  });
})();
