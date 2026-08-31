# Bundled fonts

Renderers reference these by path so output is byte-identical on every machine (SPEC §12).
`make bundle` places the Noto Sans / Serif / Mono families here (SIL Open Font License 1.1).
On a source checkout the renderers fall back to the platform default fonts; the bundle adds
the Noto faces for hermetic rendering. See NOTICE.md.
