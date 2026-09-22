(() => {
  // Wait for DOM to load
  document.addEventListener('DOMContentLoaded', () => {
    // Get all sections
    const sections = {
      'home': document.getElementById('home-section'),
      'courses': document.getElementById('courses-section'),
      'resources': document.getElementById('resources-section'),
      'contact': document.getElementById('contact-section')
    };

    // Navigation function
    function navigateTo(hash) {
      // Hide all sections
      Object.values(sections).forEach(section => {
        section.style.display = 'none';
      });

      // Show the selected section
      const selectedSection = sections[hash];
      if (selectedSection) {
        selectedSection.style.display = 'block';
      }

      // Update URL without reloading
      window.location.hash = hash;
    }

    // Handle hash change
    window.addEventListener('hashchange', (event) => {
      const newHash = event.newURL.split('#')[1] || 'home';
      navigateTo(newHash);
    });

    // Initial navigation
    const initialHash = window.location.hash.substring(1) || 'home';
    navigateTo(initialHash);
  });
})();