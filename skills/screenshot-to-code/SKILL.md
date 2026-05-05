---
name: screenshot-to-code
description: Convert UI screenshots and design mockups to HTML/CSS or React code using vision
triggers: [screenshot, image, ui design, design to code, mockup, convert image, figma, visual, html]
priority: 1
max_tokens: 300
---
# Screenshot-to-Code Specialist
Apply these rules when converting images to code.
## Reading the Image
1. Use read_image tool to load the image file as base64
2. Identify: layout type (flex/grid), colour scheme, component hierarchy, text content
3. Note exact colours from the screenshot — use hex values not colour names
## Output Format Decision
4. Simple static page → HTML + Tailwind CSS in one file
5. Interactive components → React with useState for interactive elements
6. Mobile-first design → start with mobile layout, add responsive breakpoints
## HTML/CSS Rules
7. Use semantic HTML: header, nav, main, section, article, footer
8. Flexbox for 1D layouts (row/column), CSS Grid for 2D layouts
9. Use CSS custom properties for colours: --primary: #3B82F6
## Accuracy Rules
10. Match the screenshot layout as closely as possible
11. Use actual text from the screenshot — do not invent placeholder text
12. If a font is visible, name it in a comment — use system-ui as fallback
## File Output
13. Write the complete file using write_file
14. File goes at generated_projects/screenshot_output.html or .jsx
15. After writing, report: which layout technique used, approximate match quality (1-10)
