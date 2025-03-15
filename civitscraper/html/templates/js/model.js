// Model page and image viewer functionality
document.addEventListener('DOMContentLoaded', function() {
    try {
        // Log initialization
        console.log('Initializing gallery functionality');

        const galleryItems = document.querySelectorAll('.gallery-item');
        console.log(`Found ${galleryItems.length} gallery items`);

        if (galleryItems.length === 0) {
            console.warn('No gallery items found, aborting initialization');
            return;
        }

        const imageViewer = document.getElementById('image-viewer');
        const viewerImage = document.getElementById('viewer-image');
        const viewerVideo = document.getElementById('viewer-video');
        const positivePrompt = document.getElementById('positive-prompt');
        const negativePrompt = document.getElementById('negative-prompt');
        const additionalInfo = document.getElementById('additional-info');
        const closeButton = document.getElementById('close-viewer');
        const prevButton = document.getElementById('prev-image');
        const nextButton = document.getElementById('next-image');
        const copyButtons = document.querySelectorAll('.copy-button');

        // Verify all required elements exist
        if (!imageViewer || !viewerImage || !viewerVideo || !positivePrompt || !negativePrompt ||
            !additionalInfo || !closeButton || !prevButton || !nextButton) {
            console.error('Missing required DOM elements for gallery functionality');
            return;
        }

        let currentIndex = 0;

        // Initialize the image viewer
        initializeImageViewer();

        /**
         * Initialize image viewer functionality
         */
        function initializeImageViewer() {
            // Function to decode base64 encoded JSON data with Unicode support
            function decodeBase64Json(base64String) {
                try {
                    // Decode base64 to binary
                    const binary = atob(base64String);

                    // Convert binary to Uint8Array to properly handle UTF-8
                    const bytes = new Uint8Array(binary.length);
                    for (let i = 0; i < binary.length; i++) {
                        bytes[i] = binary.charCodeAt(i);
                    }

                    // Use TextDecoder with explicit UTF-8 encoding
                    const jsonString = new TextDecoder('utf-8').decode(bytes);

                    console.log("Decoded JSON data sample:",
                        jsonString.length > 100 ?
                        jsonString.substring(0, 50) + "..." + jsonString.substring(jsonString.length - 50) :
                        jsonString);

                    // Parse JSON string to object
                    return JSON.parse(jsonString);
                } catch (e) {
                    console.error('Error decoding base64 JSON data:', e);
                    return [];
                }
            }

            // Parse image data from base64 encoded JSON
            let imageData;
            try {
                // Use the encoded data provided by the server
                imageData = decodeBase64Json(document.getElementById('images-data').getAttribute('data-images'));
                console.log(`Successfully decoded image data for ${imageData.length} images`);
            } catch (e) {
                console.error('Failed to decode image data:', e);
                return;
            }

            // Ensure imageData is valid
            if (!Array.isArray(imageData) || imageData.length === 0) {
                console.warn('Image data is empty or invalid');
                return;
            }

            // Attach click events with verification
            galleryItems.forEach((item, index) => {
                if (item) {
                    item.addEventListener('click', () => {
                        console.log(`Gallery item clicked: ${index}`);
                        currentIndex = index;
                        openImageViewer(currentIndex, imageData);
                    });
                    console.log(`Added click listener to gallery item ${index}`);
                }
            });

            // Close image viewer with error handling
            if (closeButton) {
                closeButton.addEventListener('click', () => {
                    try {
                        imageViewer.classList.remove('active');
                        console.log('Image viewer closed');
                    } catch (e) {
                        console.error('Error closing image viewer:', e);
                    }
                });
            }

            // Navigation with error handling
            if (prevButton) {
                prevButton.addEventListener('click', () => {
                    try {
                        currentIndex = (currentIndex - 1 + imageData.length) % imageData.length;
                        openImageViewer(currentIndex, imageData);
                        console.log(`Navigated to previous image: ${currentIndex}`);
                    } catch (e) {
                        console.error('Error navigating to previous image:', e);
                    }
                });
            }

            if (nextButton) {
                nextButton.addEventListener('click', () => {
                    try {
                        currentIndex = (currentIndex + 1) % imageData.length;
                        openImageViewer(currentIndex, imageData);
                        console.log(`Navigated to next image: ${currentIndex}`);
                    } catch (e) {
                        console.error('Error navigating to next image:', e);
                    }
                });
            }

            // Keyboard navigation with error handling
            document.addEventListener('keydown', (e) => {
                try {
                    if (!imageViewer.classList.contains('active')) return;

                    if (e.key === 'Escape') {
                        imageViewer.classList.remove('active');
                        console.log('Image viewer closed via Escape key');
                    } else if (e.key === 'ArrowLeft') {
                        currentIndex = (currentIndex - 1 + imageData.length) % imageData.length;
                        openImageViewer(currentIndex, imageData);
                        console.log(`Navigated to previous image via left arrow: ${currentIndex}`);
                    } else if (e.key === 'ArrowRight') {
                        currentIndex = (currentIndex + 1) % imageData.length;
                        openImageViewer(currentIndex, imageData);
                        console.log(`Navigated to next image via right arrow: ${currentIndex}`);
                    }
                } catch (e) {
                    console.error('Error in keyboard navigation:', e);
                }
            });

            // Copy to clipboard with error handling
            copyButtons.forEach(button => {
                if (button) {
                    button.addEventListener('click', () => {
                        try {
                            const targetId = button.getAttribute('data-target');
                            if (!targetId) {
                                console.error('Copy button missing data-target attribute');
                                return;
                            }

                            const targetElement = document.getElementById(targetId);
                            if (!targetElement) {
                                console.error(`Target element not found: ${targetId}`);
                                return;
                            }

                            const text = targetElement.textContent;

                            navigator.clipboard.writeText(text).then(() => {
                                button.textContent = '✓ Copied!';
                                setTimeout(() => {
                                    button.textContent = '📋 Copy';
                                }, 2000);
                                console.log(`Copied text from ${targetId}`);
                            }).catch(e => {
                                console.error('Error copying to clipboard:', e);
                            });
                        } catch (e) {
                            console.error('Error in copy functionality:', e);
                        }
                    });
                }
            });

            console.log('Gallery functionality initialized successfully');
        }

        /**
         * Open image viewer with the selected image
         */
        function openImageViewer(index, imageData) {
            try {
                console.log(`Opening image viewer for index: ${index}`);

                if (index < 0 || index >= imageData.length || index >= galleryItems.length) {
                    console.error(`Invalid index: ${index}`);
                    return;
                }

                const data = imageData[index];

                // Use direct array access and verify the element exists
                const galleryItem = galleryItems[index];
                if (!galleryItem) {
                    console.error(`Gallery item not found at index: ${index}`);
                    return;
                }

                // Check if this is a video or image
                const isVideo = data.is_video || false;

                if (isVideo) {
                    // Handle video
                    const videoElement = galleryItem.querySelector('video');
                    if (!videoElement) {
                        console.error(`Video element not found in gallery item at index: ${index}`);
                        return;
                    }

                    // Show video, hide image
                    viewerVideo.src = videoElement.src;
                    viewerVideo.style.display = 'block';
                    viewerImage.style.display = 'none';
                } else {
                    // Handle image
                    const imgElement = galleryItem.querySelector('img');
                    if (!imgElement) {
                        console.error(`Image element not found in gallery item at index: ${index}`);
                        return;
                    }

                    // Show image, hide video
                    viewerImage.src = imgElement.src;
                    viewerImage.style.display = 'block';
                    viewerVideo.style.display = 'none';
                }

                positivePrompt.textContent = data.prompt || 'No positive prompt available';
                negativePrompt.textContent = data.negative_prompt || 'No negative prompt available';

                // Format additional info
                let infoHTML = '';
                if (data.sampler) infoHTML += `<div><strong>Sampler:</strong> ${data.sampler}</div>`;
                if (data.cfg_scale) infoHTML += `<div><strong>CFG Scale:</strong> ${data.cfg_scale}</div>`;
                if (data.steps) infoHTML += `<div><strong>Steps:</strong> ${data.steps}</div>`;
                if (data.seed) infoHTML += `<div><strong>Seed:</strong> ${data.seed}</div>`;
                if (data.model) infoHTML += `<div><strong>Model:</strong> ${data.model}</div>`;

                additionalInfo.innerHTML = infoHTML || 'No additional information available';

                imageViewer.classList.add('active');
                console.log('Image viewer activated');
            } catch (e) {
                console.error('Error in openImageViewer:', e);
            }
        }

    } catch (e) {
        console.error('Fatal error in gallery initialization:', e);
    }
});
