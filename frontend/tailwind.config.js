/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Industrial railway monitoring palette
        rail: {
          navy: '#0B2440',     // deep panel / sidebar
          navyLight: '#13335A',
          blue: '#1B5FAE',     // primary signal blue
          blueLight: '#2E7BD6',
          steel: '#4A5566',    // dark gray - structural elements, borders
          steelLight: '#7B879A',
          fog: '#EEF1F5',      // page background
          line: '#DCE2EA',     // hairline dividers
        },
        status: {
          ok: '#1C8A53',
          warning: '#C77A12',
          critical: '#C5293A',
          info: '#2E7BD6',
          offline: '#8A93A3',
        },
      },
      fontFamily: {
        display: ['"Oswald"', '"Arial Narrow"', 'sans-serif'],
        body: ['"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', '"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(11, 36, 64, 0.06), 0 1px 0 rgba(11, 36, 64, 0.04)',
      },
      borderRadius: {
        panel: '6px',
      },
    },
  },
  plugins: [],
}
