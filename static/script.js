document.addEventListener("DOMContentLoaded", () => {
    const topbar = document.querySelector(".topbar");
    const menuButton = document.querySelector(".mobile-menu-btn");
    const navLinks = document.querySelector(".nav-links");
    const revealItems = document.querySelectorAll(".reveal");
    const theaterFrame = document.querySelector(".theater-frame");

    const syncTopbarState = () => {
        if (!topbar) {
            return;
        }
        topbar.classList.toggle("scrolled", window.scrollY > 12);
    };

    syncTopbarState();
    window.addEventListener("scroll", syncTopbarState);

    if (menuButton && navLinks) {
        menuButton.addEventListener("click", () => {
            navLinks.classList.toggle("open");
        });

        navLinks.querySelectorAll("a").forEach((link) => {
            link.addEventListener("click", () => {
                navLinks.classList.remove("open");
            });
        });
    }

    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
        anchor.addEventListener("click", (event) => {
            const href = anchor.getAttribute("href");
            if (!href || href === "#") {
                return;
            }

            const target = document.querySelector(href);
            if (!target) {
                return;
            }

            event.preventDefault();
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });

    if (revealItems.length > 0) {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("is-visible");
                    }
                });
            },
            { threshold: 0.14, rootMargin: "0px 0px -48px 0px" },
        );

        revealItems.forEach((item) => observer.observe(item));
    }

    if (theaterFrame) {
        const resetPointer = () => {
            theaterFrame.style.setProperty("--spot-x", "50%");
            theaterFrame.style.setProperty("--spot-y", "50%");
        };

        resetPointer();

        theaterFrame.addEventListener("pointermove", (event) => {
            const rect = theaterFrame.getBoundingClientRect();
            const x = ((event.clientX - rect.left) / rect.width) * 100;
            const y = ((event.clientY - rect.top) / rect.height) * 100;
            theaterFrame.style.setProperty("--spot-x", `${x}%`);
            theaterFrame.style.setProperty("--spot-y", `${y}%`);
        });

        theaterFrame.addEventListener("pointerleave", resetPointer);
    }
});
