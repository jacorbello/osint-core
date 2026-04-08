import tailwindConfig from '../../tailwind.config.js';

const theme = tailwindConfig.theme!.extend!;

describe('Tailwind design tokens — Intelligence Slate', () => {
  describe('color tokens', () => {
    const colors = theme.colors as Record<string, string>;

    it('uses Intelligence Slate primary blue', () => {
      expect(colors.primary).toBe('#5b8def');
    });

    it('uses muted critical/error red', () => {
      expect(colors.critical).toBe('#e06c75');
      expect(colors.error).toBe('#e06c75');
    });

    it('uses muted warning amber', () => {
      expect(colors.warning).toBe('#e5c07b');
    });

    it('uses muted success green', () => {
      expect(colors.success).toBe('#98c379');
    });

    it('uses blue-tinted neutral background', () => {
      expect(colors.background).toBe('#0f1114');
    });

    it('uses blue-tinted surface colors', () => {
      expect(colors['surface-dim']).toBe('#0a0c10');
      expect(colors.surface).toBe('#13161b');
      expect(colors['surface-bright']).toBe('#252a34');
    });

    it('defines text tokens with correct values', () => {
      expect(colors['text-primary']).toBe('#d4dae5');
      expect(colors['text-secondary']).toBe('rgba(180, 190, 210, 0.65)');
      expect(colors['text-tertiary']).toBe('rgba(180, 190, 210, 0.4)');
      expect(colors['text-muted']).toBe('rgba(180, 190, 210, 0.25)');
    });

    it('has no old cyan/purple/amber tokens', () => {
      const colorValues = Object.values(colors);
      const oldTokens = ['#00e5ff', '#c3f5ff', '#bdc2ff', '#343d96', '#ffeac0', '#fec931'];
      for (const oldToken of oldTokens) {
        expect(colorValues).not.toContain(oldToken);
      }
    });
  });

  describe('font families', () => {
    const fontFamily = theme.fontFamily as Record<string, string[]>;

    it('uses IBM Plex Sans for headings', () => {
      expect(fontFamily.headline[0]).toBe('IBM Plex Sans');
    });

    it('uses IBM Plex Sans for body text', () => {
      expect(fontFamily.body[0]).toBe('IBM Plex Sans');
    });

    it('uses IBM Plex Mono for data', () => {
      expect(fontFamily.mono[0]).toBe('IBM Plex Mono');
    });

    it('does not reference Space Grotesk or Inter', () => {
      const allFonts = Object.values(fontFamily).flat();
      expect(allFonts).not.toContain('Space Grotesk');
      expect(allFonts).not.toContain('Inter');
    });
  });

  describe('border radius', () => {
    const borderRadius = theme.borderRadius as Record<string, string>;

    it('uses 4px as default radius', () => {
      expect(borderRadius.DEFAULT).toBe('4px');
    });

    it('uses 4px for sm radius', () => {
      expect(borderRadius.sm).toBe('4px');
    });

    it('uses 8px for md radius', () => {
      expect(borderRadius.md).toBe('8px');
    });

    it('uses 12px for lg radius', () => {
      expect(borderRadius.lg).toBe('12px');
    });

    it('uses 9999px for full radius', () => {
      expect(borderRadius.full).toBe('9999px');
    });
  });
});
