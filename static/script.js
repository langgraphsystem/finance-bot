document.addEventListener('DOMContentLoaded', () => {

    /* --- Navbar Scroll Effect --- */
    const navbar = document.querySelector('.navbar');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });

    /* --- Scroll Reveal Animations (Intersection Observer) --- */
    const revealElements = document.querySelectorAll('.reveal');

    // Fallback: if nothing triggers in 2s, show everything
    const fallbackTimer = setTimeout(() => {
        revealElements.forEach(el => el.classList.add('active'));
    }, 2000);

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

    // Immediately trigger for elements already in viewport on load
    requestAnimationFrame(() => {
        revealElements.forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.top < window.innerHeight && rect.bottom > 0) {
                el.classList.add('active');
            }
        });
    });

    /* --- Typewriter Effect & Chat Demo Simulation --- */
    const typeText = document.querySelector('.type-effect');
    if (typeText) {
        const textToType = typeText.textContent;
        typeText.textContent = '';
        let i = 0;

        function typeWriter() {
            if (i < textToType.length) {
                typeText.innerHTML += textToType.charAt(i);
                i++;
                setTimeout(typeWriter, 50);
            } else {
                startChatDemo();
            }
        }

        setTimeout(typeWriter, 500);
    }

    /* --- Mockup Chat Sequence --- */
    function startChatDemo() {
        const loadingMsg = document.getElementById('demo-bot-msg');
        const finalMsg = document.getElementById('demo-bot-res');

        if (!loadingMsg || !finalMsg) return;

        setTimeout(() => {
            loadingMsg.classList.add('hidden');
            finalMsg.classList.remove('hidden');
            finalMsg.style.animation = 'none';
            finalMsg.offsetHeight;
            finalMsg.style.animation = 'slideUpFade 0.4s ease forwards';
        }, 2500);
    }

    /* --- Use Cases Tabs --- */
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            const tabId = btn.getAttribute('data-tab');
            document.getElementById('tab-' + tabId).classList.add('active');
        });
    });

    /* --- 3D Tilt Effect on Hover (Desktop only) --- */
    const tiltElements = document.querySelectorAll('.tilt-effect');

    if (window.matchMedia("(pointer: fine)").matches) {
        tiltElements.forEach(el => {
            el.addEventListener('mousemove', (e) => {
                const rect = el.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const centerX = rect.width / 2;
                const centerY = rect.height / 2;
                const rotateX = ((y - centerY) / centerY) * -5;
                const rotateY = ((x - centerX) / centerX) * 5;
                el.style.transform = 'perspective(1000px) rotateX(' + rotateX + 'deg) rotateY(' + rotateY + 'deg) scale3d(1.02, 1.02, 1.02)';
                if (el.classList.contains('bento-card')) {
                    el.style.borderColor = 'rgba(255,255,255,0.3)';
                }
            });
            el.addEventListener('mouseleave', () => {
                el.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
                if (el.classList.contains('bento-card')) {
                    el.style.borderColor = '';
                }
            });
        });
    }

});
