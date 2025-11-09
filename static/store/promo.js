document.addEventListener('DOMContentLoaded', function () {
    const slides = Array.from(document.querySelectorAll('.promo-slide'));
    if (!slides.length) return;

    let current = slides.findIndex(s => s.classList.contains('opacity-100'));
    if (current === -1) current = 0;

    function show(index) {
        index = (index + slides.length) % slides.length;
        slides.forEach((s, i) => {
            const active = i === index;
            s.classList.toggle('opacity-100', active);
            s.classList.toggle('opacity-0', !active);
            s.classList.toggle('pointer-events-none', !active);
            s.classList.toggle('relative', active);
        });
        // update dots
        document.querySelectorAll('.promo-dot').forEach(btn => {
            const idx = parseInt(btn.getAttribute('data-index'), 10);
            const pressed = idx === index;
            btn.setAttribute('aria-pressed', pressed ? 'true' : 'false');
            btn.classList.toggle('active', pressed);
        });
        current = index;
    }

    // prev / next
    document.querySelectorAll('.promo-prev').forEach(b => b.addEventListener('click', () => show(current - 1)));
    document.querySelectorAll('.promo-next').forEach(b => b.addEventListener('click', () => show(current + 1)));

    // dots
    document.querySelectorAll('.promo-dot').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const idx = parseInt(btn.getAttribute('data-index'), 10);
            if (!Number.isNaN(idx)) show(idx);
        });
    });

    // keyboard navigation when focus is inside promo-outer
    document.querySelectorAll('.promo-outer').forEach(root => {
        root.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') { e.preventDefault(); show(current - 1); }
            if (e.key === 'ArrowRight') { e.preventDefault(); show(current + 1); }
        });
        // make it focusable
        if (!root.hasAttribute('tabindex')) root.setAttribute('tabindex', '0');
    });

    // autoplay (enabled)
    let autoplay = true;
    let autoplayInterval = null;
    function startAutoplay() {
        if (autoplayInterval) clearInterval(autoplayInterval);
        autoplayInterval = setInterval(() => show(current + 1), 6000);
    }
    function stopAutoplay() {
        if (autoplayInterval) { clearInterval(autoplayInterval); autoplayInterval = null; }
    }
    if (autoplay) startAutoplay();

    // pause autoplay on user interaction (click or focus)
    document.querySelectorAll('.promo-prev, .promo-next, .promo-dot').forEach(el => {
        el.addEventListener('click', () => {
            stopAutoplay();
            // restart after short delay
            setTimeout(() => { if (autoplay) startAutoplay(); }, 4000);
        });
    });

    // --- HOVER PREVIEW LOGIC ---
    slides.forEach(slide => {
        const leftImg = slide.querySelector('.promo-cover-image');
        const thumbs = slide.querySelectorAll('.promo-thumbs img');
        if (!leftImg || !thumbs.length) return;
        let origSrc = leftImg.getAttribute('data-src') || leftImg.getAttribute('src');
        thumbs.forEach(thumb => {
            function fadeSwap(newSrc) {
                leftImg.style.opacity = '0';
                setTimeout(() => {
                    leftImg.src = newSrc;
                    leftImg.style.opacity = '1';
                }, 180);
            }
            thumb.addEventListener('mouseenter', function () {
                fadeSwap(this.getAttribute('data-src') || this.src);
            });
            thumb.addEventListener('mouseleave', function () {
                fadeSwap(origSrc);
            });
            thumb.addEventListener('focus', function () {
                fadeSwap(this.getAttribute('data-src') || this.src);
            });
            thumb.addEventListener('blur', function () {
                fadeSwap(origSrc);
            });
        });
    });
});
