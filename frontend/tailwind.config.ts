import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Segoe UI Variable"', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      colors: {
        surface: {
          950: '#07090f',
          900: '#0d111a',
          800: '#151b27',
          700: '#1f2937',
        },
        accent: {
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
        },
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(125, 211, 252, 0.16), 0 18px 60px rgba(2, 8, 23, 0.55)',
      },
      backgroundImage: {
        'app-radial': 'radial-gradient(circle at top, rgba(14, 165, 233, 0.12), transparent 40%), radial-gradient(circle at right, rgba(56, 189, 248, 0.08), transparent 24%)',
      },
    },
  },
  plugins: [],
} satisfies Config;
