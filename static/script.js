document.addEventListener('DOMContentLoaded', () => {

    /* --- Navbar Scroll Effect --- */
    const navbar = document.querySelector('.navbar');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 20) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });

    /* --- Scroll Reveal Animations --- */
    const revealElements = document.querySelectorAll('.reveal');

    const revealOptions = {
        threshold: 0.05,
        rootMargin: "0px 0px -20px 0px"
    };

    const revealOnScroll = new IntersectionObserver(function (entries, observer) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('active');
                observer.unobserve(entry.target);
            }
        });
    }, revealOptions);

    revealElements.forEach(el => {
        revealOnScroll.observe(el);
    });

    // Trigger for elements already in viewport
    setTimeout(() => {
        revealElements.forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.top < window.innerHeight && rect.bottom > 0) {
                el.classList.add('active');
            }
        });
    }, 100);

    /* --- Composio-style Mouse Hover Glow --- */
    const cards = document.querySelectorAll('.hover-glow');

    document.addEventListener('mousemove', e => {
        for (const card of cards) {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);

            // Set custom glow color if data attribute exists
            const glowColor = card.getAttribute('data-glow-color');
            if (glowColor) {
                card.style.setProperty('--mouse-color', glowColor);
            }
        }
    });

    /* --- Terminal Sequence Animation --- */
    function runTerminalDemo() {
        const cmdResp1 = document.getElementById('cmd-resp-1');
        const cmdResp2 = document.getElementById('cmd-resp-2');

        if (!cmdResp1 || !cmdResp2) return;

        // Sequence timing
        setTimeout(() => {
            cmdResp1.classList.remove('hidden');
        }, 1200);

        setTimeout(() => {
            cmdResp1.querySelector('.clr-dim').textContent = "Processing... ✓";
            cmdResp2.classList.remove('hidden');
        }, 3000);
    }

    /* --- Typewriter Effect for Hero --- */
    const typeText = document.querySelector('.type-effect');
    if (typeText) {
        const textToType = typeText.textContent;
        typeText.textContent = '';
        let i = 0;

        function typeWriter() {
            if (i < textToType.length) {
                typeText.textContent += textToType.charAt(i);
                i++;
                setTimeout(typeWriter, 40);
            } else {
                runTerminalDemo();
            }
        }

        setTimeout(typeWriter, 600);
    } else {
        runTerminalDemo();
    }

    /* --- Infinite Marquee Cloning --- */
    const marqueeContent = document.querySelector('.marquee-content');
    if (marqueeContent) {
        // Clone items for smooth infinite scroll
        const clone = marqueeContent.innerHTML;
        marqueeContent.innerHTML += clone + clone;

        // Simple GSAP-less marquee animation using Web Animations API
        const scrollWidth = marqueeContent.scrollWidth / 3;

        marqueeContent.animate([
            { transform: 'translateX(0)' },
            { transform: `translateX(-${scrollWidth}px)` }
        ], {
            duration: 20000,
            iterations: Infinity,
            easing: 'linear'
        });
    }

});
