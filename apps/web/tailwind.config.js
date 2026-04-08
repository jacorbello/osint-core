/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Surface colors — blue-tinted neutrals
        background: '#0f1114',
        surface: '#13161b',
        'surface-dim': '#0a0c10',
        'surface-bright': '#252a34',
        'surface-container-lowest': '#0a0c10',
        'surface-container-low': '#13161b',
        'surface-container': '#181b22',
        'surface-container-high': '#1e2229',
        'surface-container-highest': '#252a34',
        'surface-variant': '#1e2229',

        // Primary — Intelligence Slate blue
        primary: '#5b8def',
        'primary-container': '#3d6fd1',
        'on-primary': '#ffffff',
        'on-primary-container': '#c5d7fa',

        // Critical / Error — muted red
        critical: '#e06c75',
        error: '#e06c75',
        'error-container': '#4a1c20',
        'on-error': '#ffffff',
        'on-error-container': '#f5c6c9',

        // Warning — muted amber
        warning: '#e5c07b',
        'warning-container': '#4a3d1c',
        'on-warning': '#1a1400',
        'on-warning-container': '#f5e6c0',

        // Success — muted green
        success: '#98c379',
        'success-container': '#1c3a1c',
        'on-success': '#ffffff',
        'on-success-container': '#c6e6b8',

        // Text
        'text-primary': '#d4dae5',
        'text-secondary': 'rgba(180, 190, 210, 0.65)',
        'text-tertiary': 'rgba(180, 190, 210, 0.4)',
        'text-muted': 'rgba(180, 190, 210, 0.25)',
        'on-background': '#d4dae5',
        'on-surface': '#d4dae5',
        'on-surface-variant': 'rgba(180, 190, 210, 0.65)',

        // Borders
        outline: 'rgba(180, 190, 210, 0.25)',
        'outline-variant': 'rgba(180, 190, 210, 0.12)',
      },
      fontFamily: {
        headline: ['IBM Plex Sans', 'sans-serif'],
        body: ['IBM Plex Sans', 'sans-serif'],
        label: ['IBM Plex Sans', 'sans-serif'],
        mono: ['IBM Plex Mono', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '4px',
        sm: '4px',
        md: '8px',
        lg: '12px',
        full: '9999px',
      },
    },
  },
  plugins: [],
};
