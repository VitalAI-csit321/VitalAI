/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Pulled to match the sponsor-approved prototype exactly.
        sidebar: {
          DEFAULT: "#1b2432", // dark navy sidebar / auth background
          hover: "#273140",
          active: "#2b3646",
        },
        brand: {
          // teal primary used on all primary buttons and active accents
          DEFAULT: "#0f766e",
          hover: "#115e59",
          light: "#14b8a6",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
