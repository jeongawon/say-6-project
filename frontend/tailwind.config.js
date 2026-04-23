/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        monitor: {
          bg: "#0a0f0a",
          grid: "#1a2a1a",
          wave: "#00e676",
          text: "#80cbc4",
        },
        clinical: {
          dark: "#0b1120",
          card: "#111827",
          border: "#1e2d3d",
        },
      },
    },
  },
  plugins: [],
};
