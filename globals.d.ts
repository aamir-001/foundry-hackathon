// Ambient declarations so a standalone `tsc`/Next type-check accepts global CSS
// side-effect imports (Next's loader handles the actual bundling).
declare module "*.css";
