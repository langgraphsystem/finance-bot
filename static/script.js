document.addEventListener("DOMContentLoaded", () => {
    const navbar = document.querySelector(".navbar");
    const menuBtn = document.querySelector(".mobile-menu-btn");
    const navLinks = document.querySelector(".nav-links");
    const revealItems = document.querySelectorAll(".reveal");
    const showcaseBoard = document.querySelector(".showcase-board");

    const syncNavbarState = () => {
        if (!navbar) {
            return;
        }
        navbar.classList.toggle("scrolled", window.scrollY > 12);
    };

    syncNavbarState();
    window.addEventListener("scroll", syncNavbarState);

    if (menuBtn && navLinks) {
        menuBtn.addEventListener("click", () => {
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
            const target = document.querySelector(anchor.getAttribute("href"));
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
            { threshold: 0.16, rootMargin: "0px 0px -40px 0px" },
        );

        revealItems.forEach((item) => observer.observe(item));
    }

    if (showcaseBoard) {
        const resetCursor = () => {
            showcaseBoard.style.setProperty("--cursor-x", "50%");
            showcaseBoard.style.setProperty("--cursor-y", "50%");
        };

        resetCursor();

        showcaseBoard.addEventListener("pointermove", (event) => {
            const rect = showcaseBoard.getBoundingClientRect();
            const x = ((event.clientX - rect.left) / rect.width) * 100;
            const y = ((event.clientY - rect.top) / rect.height) * 100;
            showcaseBoard.style.setProperty("--cursor-x", `${x}%`);
            showcaseBoard.style.setProperty("--cursor-y", `${y}%`);
        });

        showcaseBoard.addEventListener("pointerleave", resetCursor);
    }
});
