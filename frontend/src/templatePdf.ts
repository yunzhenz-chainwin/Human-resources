import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'

declare global {
  interface Window {
    downloadEditedResumePdf: () => Promise<void>
  }
}

window.downloadEditedResumePdf = async () => {
  const page = document.querySelector<HTMLElement>('.page')
  const button = document.querySelector<HTMLButtonElement>('#export-pdf')
  if (!page || !button) return

  const originalLabel = button.textContent || '下載目前內容 PDF'
  button.disabled = true
  button.textContent = 'PDF 製作中…'
  try {
    const canvas = await html2canvas(page, {
      backgroundColor: '#ffffff',
      scale: 2,
      useCORS: true,
      logging: false,
      windowWidth: page.scrollWidth,
      windowHeight: page.scrollHeight,
    })
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
    const pageWidth = 210
    const pageHeight = 297
    const imageHeight = (canvas.height * pageWidth) / canvas.width
    const image = canvas.toDataURL('image/jpeg', 0.94)
    const pageCount = Math.max(1, Math.ceil(imageHeight / pageHeight))

    for (let index = 0; index < pageCount; index += 1) {
      if (index > 0) pdf.addPage('a4', 'portrait')
      pdf.addImage(image, 'JPEG', 0, -(index * pageHeight), pageWidth, imageHeight)
    }
    pdf.save(`TalentHub-履歷-${new Date().toISOString().slice(0, 10)}.pdf`)
  } catch (error) {
    console.error(error)
    window.alert('PDF 產生失敗，請重新整理後再試一次。')
  } finally {
    button.disabled = false
    button.textContent = originalLabel
  }
}
