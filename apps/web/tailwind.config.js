/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Surface colors
        background: '#111318',
        surface: '#111318',
        'surface-dim': '#111318',
        'surface-bright': '#37393e',
        'surface-container-lowest': '#0c0e12',
        'surface-container-low': '#1a1c20',
        'surface-container': '#1e2024',
        'surface-container-high': '#282a2e',
        'surface-container-highest': '#333539',
        'surface-variant': '#333539',
        
        // Primary (cyan)
        primary: '#c3f5ff',
        'primary-container': '#00e5ff',
        'on-primary': '#00363d',
        'on-primary-container': '#00626e',
        
        // Secondary (purple)
        secondary: '#bdc2ff',
        'secondary-container': '#343d96',
        'on-secondary': '#1b247f',
        'on-secondary-container': '#a8afff',
        
        // Tertiary (amber)
        tertiary: '#ffeac0',
        'tertiary-container': '#fec931',
        'on-tertiary': '#3e2e00',
        'on-tertiary-container': '#6f5500',
        
        // Error
        error: '#ffb4ab',
        'error-container': '#93000a',
        'on-error': '#690005',
        'on-error-container': '#ffdad6',
        
        // Text
        'on-background': '#e2e2e8',
        'on-surface': '#e2e2e8',
        'on-surface-variant': '#bac9cc',
        
        // Borders
        outline: '#849396',
        'outline-variant': '#3b494c',
      },
      fontFamily: {
        headline: ['Space Grotesk', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        label: ['Inter', 'sans-serif'],
      },
      borderRadius: {
        DEFAULT: '0.125rem',
        lg: '0.25rem',
        xl: '0.5rem',
        full: '0.75rem',
      },
    },
  },
  plugins: [],
};
