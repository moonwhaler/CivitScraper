// Base functionality
document.addEventListener('DOMContentLoaded', function() {
    // Initialize copy functionality
    initCopyFunctionality();
});

/**
 * Initializes copy-to-clipboard functionality for elements with the copy-icon class
 */
function initCopyFunctionality() {
    document.querySelectorAll('.copy-icon').forEach(icon => {
        icon.addEventListener('click', function() {
            const textToCopy = this.getAttribute('data-copy');
            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalText = this.textContent.trim();
                this.textContent = '✓';
                setTimeout(() => {
                    this.textContent = originalText;
                }, 2000);
            });
        });
    });
}
