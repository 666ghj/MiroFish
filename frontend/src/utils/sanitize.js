import DOMPurify from 'dompurify'

export function sanitizeHtml(html) {
  if (!html) return ''
  return DOMPurify.sanitize(html)
}
