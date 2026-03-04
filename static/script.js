document.addEventListener('DOMContentLoaded', () => {

    /* --- 1. Lenis Smooth Scroll --- */
    const lenis = new Lenis();
    function raf(time) {
        lenis.raf(time);
        requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);

    /* --- 2. GSAP Animations --- */
    gsap.registerPlugin(ScrollTrigger);

    // Reveal on Scroll
    gsap.utils.toArray('.reveal').forEach(el => {
        gsap.fromTo(el, { opacity: 0, y: 30 }, {
            opacity: 1, y: 0,
            duration: 1,
            ease: "power3.out",
            scrollTrigger: {
                trigger: el,
                start: "top 85%",
                toggleActions: "play none none reverse"
            }
        });
    });

    // Node & Line Animation (Composio Style)
    const tl = gsap.timeline({ repeat: -1 });
    tl.to('.connector-line', {
        opacity: 0.8,
        duration: 0.8,
        stagger: 0.2,
        yoyo: true,
        repeat: 1
    });

    gsap.to('.node', {
        y: -10,
        duration: 2,
        stagger: 0.3,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut"
    });

    // Mouse Tracking for Bento Cards
    const cards = document.querySelectorAll('.bento-card');
    cards.forEach(card => {
        card.addEventListener('mousemove', e => {
            const rect = card.getBoundingClientRect();
            const x = ((e.clientX - rect.left) / rect.width) * 100;
            const y = ((e.clientY - rect.top) / rect.height) * 100;
            card.style.setProperty('--mouse-x', `${x}%`);
            card.style.setProperty('--mouse-y', `${y}%`);
        });
    });

    // Parallax on Scroll for Mesh Glow
    window.addEventListener('scroll', () => {
        const scrolled = window.scrollY;
        gsap.to('.glow-mesh', {
            y: scrolled * 0.2,
            duration: 0.5
        });
    });

});
