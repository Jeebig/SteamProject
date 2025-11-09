(function () {
  // Swap main media when clicking a thumbnail
  const main = document.getElementById("mainMedia");
  document.querySelectorAll(".thumbs .thumb").forEach((btn) => {
    btn.addEventListener("click", () => {
      const src = btn.getAttribute("data-src");
      if (main && src) main.src = src;
      // active state
      document
        .querySelectorAll(".thumbs .thumb")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });

  // Simple horizontal scroll via wheel for carousels
  document.querySelectorAll(".carousel-track").forEach((track) => {
    track.addEventListener(
      "wheel",
      (e) => {
        if (Math.abs(e.deltaX) < Math.abs(e.deltaY)) {
          track.scrollLeft += e.deltaY;
          e.preventDefault();
        }
      },
      { passive: false }
    );
  });

  // Arrow controls + edge fade visibility
  function getTrack(name) {
    const track = document.querySelector(
      `.carousel-track[data-carousel="${name}"]`
    );
    return track;
  }

  function updateCarouselState(track) {
    const wrap = track.closest(".carousel");
    if (!wrap) return;
    const atLeft = track.scrollLeft <= 2;
    const atRight =
      track.scrollLeft + track.clientWidth >= track.scrollWidth - 2;
    wrap.classList.toggle("has-left", !atLeft);
    wrap.classList.toggle("has-right", !atRight);
    const leftBtn = wrap.querySelector(".carousel-arrow.left");
    const rightBtn = wrap.querySelector(".carousel-arrow.right");
    if (leftBtn) leftBtn.classList.toggle("disabled", atLeft);
    if (rightBtn) rightBtn.classList.toggle("disabled", atRight);
  }

  function scrollTrack(name, dir) {
    const track = getTrack(name);
    if (!track) return;
    const amount = track.clientWidth * 0.9;
    track.scrollBy({ left: dir > 0 ? amount : -amount, behavior: "smooth" });
    // update after the scroll animation starts
    setTimeout(() => updateCarouselState(track), 60);
  }
  document.querySelectorAll(".carousel-arrow").forEach((btn) => {
    btn.addEventListener("click", () => {
      const t = btn.getAttribute("data-target");
      const dir = btn.classList.contains("right") ? 1 : -1;
      scrollTrack(t, dir);
    });
  });

  // Initialize edge fades and disabled arrows
  document.querySelectorAll(".carousel-track").forEach((track) => {
    const onScroll = () => updateCarouselState(track);
    track.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    // initial
    updateCarouselState(track);
  });

  // Star rating widgets: fill stars up to selected value
  function initStarGroup(group) {
    const inputs = Array.from(
      group.querySelectorAll('input[type="radio"][name="rating"]')
    );
    // Map each label to its associated input value
    const entries = Array.from(group.querySelectorAll("label")).map((lbl) => {
      const inp = lbl.previousElementSibling;
      const val = inp ? parseFloat(inp.value) : NaN;
      return { lbl, val };
    });

    function update() {
      const checked = inputs.find((i) => i.checked);
      const value = checked ? parseFloat(checked.value) : 0;
      entries.forEach(({ lbl }) => lbl.classList.remove("filled"));
      entries.forEach(({ lbl, val }) => {
        if (!isNaN(val) && val <= value + 0.0001) lbl.classList.add("filled");
      });
    }
    inputs.forEach((i) => i.addEventListener("change", update));
    // hover preview
    entries.forEach((entry) => {
      const { lbl, val } = entry;
      lbl.addEventListener("mouseenter", () => {
        entries.forEach((e) => e.lbl.classList.remove("preview"));
        entries.forEach((e) => {
          if (!isNaN(e.val) && e.val <= val + 0.0001)
            e.lbl.classList.add("preview");
        });
      });
      lbl.addEventListener("mouseleave", () => {
        entries.forEach((e) => e.lbl.classList.remove("preview"));
      });
    });
    // keyboard support on container
    group.setAttribute("role", "radiogroup");
    group.tabIndex = 0;
    group.addEventListener("keydown", (e) => {
      const key = e.key;
      const current = inputs.findIndex((i) => i.checked);
      let next = current;
      if (key === "ArrowRight" || key === "ArrowUp")
        next = Math.min(inputs.length - 1, current + 1);
      if (key === "ArrowLeft" || key === "ArrowDown")
        next = Math.max(0, current - 1);
      if (key === "Home") next = 0;
      if (key === "End") next = inputs.length - 1;
      if (next !== current) {
        e.preventDefault();
        inputs[next].checked = true;
        inputs[next].dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    update();
  }
  document.querySelectorAll(".rating-stars").forEach(initStarGroup);

  // AJAX review voting
  function getCookie(name) {
    const v = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return v ? v.pop() : "";
  }
  const csrftoken = getCookie("csrftoken");
  document.querySelectorAll("form.vote-form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const action = form.getAttribute("action");
      const container = form.closest(".bg-gray-900");
      fetch(action, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": csrftoken,
        },
        body: fd,
        credentials: "same-origin",
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data || data.ok === false) {
            if (data && data.message) {
              console.info(data.message);
            }
            return;
          }
          // update counts and active state within this review block
          const reviewBlock = form.closest(".bg-gray-900");
          if (!reviewBlock) return;
          const yesSpan = reviewBlock.querySelector(".vote-yes");
          const noSpan = reviewBlock.querySelector(".vote-no");
          if (yesSpan) yesSpan.textContent = data.helpful_yes;
          if (noSpan) noSpan.textContent = data.helpful_no;
          // toggle active classes
          reviewBlock
            .querySelectorAll(".vote-btn")
            .forEach((btn) => btn.classList.remove("active"));
          if (data.user_vote === "up") {
            const upBtn = reviewBlock.querySelector(".vote-btn.up");
            upBtn && upBtn.classList.add("active");
          } else if (data.user_vote === "down") {
            const downBtn = reviewBlock.querySelector(".vote-btn.down");
            downBtn && downBtn.classList.add("active");
          }
        })
        .catch((err) => console.warn("Vote failed", err));
    });
  });
})();
