/** Types for xprobe.cjs, the thin Node entry that runs xprobe.py through vendor/py_launch.cjs. */
export interface PyLaunchOptions {
  /** Environment variable naming the Python interpreter (XPROBE_PYTHON). */
  envVar: string;
  /** Adds CPython -S. */
  noSite: boolean;
}
/** Absolute path of xprobe.py next to xprobe.cjs. */
export const PY_SCRIPT: string;
export const PY_LAUNCH: PyLaunchOptions;
