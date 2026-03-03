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

    // Update ScrollTrigger on Lenis scroll
    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add((time) => {
        lenis.raf(time * 1000);
    });

    // Hero Animations
    const tl = gsap.timeline();
    tl.fromTo('.hero-badge', { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.8, delay: 0.2 })
      .fromTo('.hero-title', { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 1 }, "-=0.6")
      .fromTo('.hero-subtitle', { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.8 }, "-=0.8")
      .fromTo('.hero-cta', { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.8 }, "-=0.8");

    // Reveal on Scroll
    const reveals = gsap.utils.toArray('.reveal');
    reveals.forEach(el => {
        gsap.fromTo(el, { opacity: 0, y: 40 }, {
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

    // Aurora Parallax
    gsap.to('.aurora-1', {
        y: 200, x: 100,
        scrollTrigger: { scrub: 1 }
    });
    gsap.to('.aurora-2', {
        y: -200, x: -100,
        scrollTrigger: { scrub: 1 }
    });

    /* --- 3. Infinite Marquee --- */
    const marqueeContent = document.querySelector('.marquee-content');
    if (marqueeContent) {
        const clone = marqueeContent.innerHTML;
        marqueeContent.innerHTML += clone + clone;
        
        const scrollWidth = marqueeContent.scrollWidth / 3;
        gsap.to(marqueeContent, {
            x: -scrollWidth,
            duration: 30,
            repeat: -1,
            ease: "none"
        });
    }

    /* --- 4. Navbar Background on Scroll --- */
    const navbar = document.querySelector('.navbar');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) navbar.classList.add('scrolled');
        else navbar.classList.remove('scrolled');
    });

    /* --- 5. Magnetic Hover Effect (Subtle) --- */
    const btns = document.querySelectorAll('.btn');
    btns.forEach(btn => {
        btn.addEventListener('mousemove', (e) => {
            const rect = btn.getBoundingClientRect();
            const x = e.clientX - rect.left - rect.width / 2;
            const y = e.clientY - rect.top - rect.height / 2;
            gsap.to(btn, { x: x * 0.2, y: y * 0.2, duration: 0.3 });
        });
        btn.addEventListener('mouseleave', () => {
            gsap.to(btn, { x: 0, y: 0, duration: 0.5, ease: "elastic.out(1, 0.3)" });
        });
    });

});
