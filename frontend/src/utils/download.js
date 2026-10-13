export function savePdfBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  try {
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
  } finally {
    link.remove()
    // Give browsers time to consume the download before releasing its bytes.
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
}
