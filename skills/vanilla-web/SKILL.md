---
name: vanilla-web
description: Browser-native vanilla HTML5, CSS3, and modern JavaScript patterns with DOM manipulation and responsive styling
triggers: [html, css, javascript, vanilla, vanilla-web, website, webpage, frontend, web, landing-page, ui, webapp, responsive, lost-and-found]
priority: 1
max_tokens: 450
---

# Vanilla Web Application Specialist

Apply these production-quality rules for all browser-native HTML5, CSS3, and modern Vanilla JavaScript tasks.

## 1. Architectural Principles
1. **Zero Build Step:** Code must execute natively in modern web browsers without transpilers (Babel), bundlers (Webpack/Vite), or frameworks.
2. **Framework Isolation:** Absolutely no React, JSX, or external frontend framework imports unless explicitly requested by the user.
3. **Application Entrypoint:** Default entrypoint is `index.html` at the project root, with linked stylesheets and scripts.

## 2. HTML5 Semantic Structure (index.html)
4. Use standard semantic HTML5: `<!DOCTYPE html>`, `<html lang="en">`, `<head>`, `<meta charset="UTF-8">`, `<meta name="viewport" content="width=device-width, initial-scale=1.0">`.
5. Organize page layout with semantic landmarks: `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<footer>`.
6. Link stylesheets in the `<head>` and load scripts with `defer` or before the closing `</body>` tag.
7. Ensure all interactive controls (buttons, links, form inputs) are keyboard-navigable and have accessible labels.

## 3. Modern CSS Styling (styles.css)
8. Use CSS custom properties for cohesive theming (`:root { --primary: #...; --bg: #...; }`).
9. Build responsive layouts mobile-first using modern CSS Flexbox and CSS Grid. Include `@media` breakpoints for tablets and desktops.
10. Define polished visual interactive states: smooth hover/active transitions, focus rings (`:focus-visible`), and consistent spacing units.

## 4. Modern Vanilla JavaScript (app.js)
11. Encapsulate client logic inside a `DOMContentLoaded` event listener or ES module to ensure DOM readiness.
12. Use `document.querySelector` / `document.querySelectorAll` or `document.getElementById` for clear element targeting.
13. Attach events with `addEventListener`:
    - Handle form submissions with `event.preventDefault()`.
    - Handle interactive button clicks, filter inputs, and modal toggles cleanly.
14. **Safe DOM Manipulation:** When rendering dynamic content, avoid injecting unescaped user strings into `innerHTML`. Use `textContent`, `document.createElement`, or sanitize template inputs to prevent XSS.
15. **State & Persistence (Conditional):** If the application requires client-side persistence, store state in `localStorage` with `JSON.stringify` / `JSON.parse`. Do not force `localStorage` on purely static or informational landing pages.
