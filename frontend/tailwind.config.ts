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
          950: '#111318',
          900: '#171a21',
          800: '#1b1f27',
          700: '#222733',
          600: '#303642',
        },
        accent: {
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
        },
        success: {
          100: '#dcfce7',
          200: '#bbf7d0',
          500: '#22c55e',
        },
        warning: {
          100: '#fef3c7',
          200: '#fde68a',
          500: '#f59e0b',
        },
        danger: {
          100: '#fee2e2',
          200: '#fecaca',
          500: '#ef4444',
        },
      },
      boxShadow: {
        subtle: '0 1px 2px rgba(0, 0, 0, 0.2), 0 12px 28px rgba(0, 0, 0, 0.18)',
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1rem',
      },
    },
  },
  plugins: [],
} satisfies Config;
