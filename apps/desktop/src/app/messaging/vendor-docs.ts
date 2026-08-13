const HERMES_DOCS_HOST = /(?:^|\.)hermes-agent\.nousresearch\.com$/i

export function isVendorSetupUrl(url: null | string | undefined): boolean {
  const raw = (url || '').trim()

  if (!raw) {
    return false
  }

  try {
    const host = new URL(raw).hostname

    return Boolean(host) && !HERMES_DOCS_HOST.test(host)
  } catch {
    return false
  }
}
