document.addEventListener("DOMContentLoaded", () => {
    initializeTheme();
    initializeAudioButtons();
    initializeSpeechButtons();
    initializeRevealButtons();
});


function initializeTheme() {
    const themeToggle = document.querySelector("#theme-toggle");

    if (!themeToggle) {
        return;
    }

    function setTheme(dark) {
        document.documentElement.classList.toggle("dark", dark);

        themeToggle.textContent = dark
            ? "☀ Light"
            : "☾ Dark";

        themeToggle.setAttribute(
            "aria-label",
            dark
                ? "Switch to light mode"
                : "Switch to dark mode"
        );
    }

    const savedTheme = localStorage.getItem("theme");

    if (savedTheme === "dark") {
        setTheme(true);
    } else if (savedTheme === "light") {
        setTheme(false);
    } else {
        setTheme(
            window.matchMedia(
                "(prefers-color-scheme: dark)"
            ).matches
        );
    }

    themeToggle.addEventListener("click", () => {
        const dark =
            !document.documentElement.classList.contains("dark");

        setTheme(dark);

        localStorage.setItem(
            "theme",
            dark ? "dark" : "light"
        );
    });
}


function initializeAudioButtons() {
    document.querySelectorAll("[data-audio]").forEach(button => {
        button.addEventListener("click", () => {
            const url = button.dataset.audio;

            if (!url) {
                return;
            }

            const audio = new Audio(url);
            audio.play();
        });
    });
}


function initializeSpeechButtons() {
    if (!("speechSynthesis" in window)) {
        return;
    }

    document.querySelectorAll("[data-word]").forEach(button => {
        button.addEventListener("click", () => {
            const word = button.dataset.word;

            if (!word) {
                return;
            }

            window.speechSynthesis.cancel();

            const utterance =
                new SpeechSynthesisUtterance(word);

            utterance.lang = button.dataset.language || "en-US";

            window.speechSynthesis.speak(utterance);
        });
    });
}


function initializeRevealButtons() {
    document.querySelectorAll(".reveal-button").forEach(button => {
        button.addEventListener("click", () => {
            const word =
                button.parentElement.querySelector(".hidden-word");

            if (!word) {
                return;
            }

            word.classList.add("revealed");
            button.remove();
        });
    });
}