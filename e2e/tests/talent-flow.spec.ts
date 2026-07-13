import { expect, test } from '@playwright/test'

const candidateName = '端對端測試人才'
const resumeName = 'talenthub-e2e-resume.pdf'

// The upload validator requires a PDF signature. The parser may mark this tiny
// synthetic document for review; submitted form fields remain the source of truth.
const minimalPdf = Buffer.from('%PDF-1.4\n% synthetic E2E resume - no personal data\n%%EOF\n')

test.describe.serial('public submission to HR review', () => {
  test('public career page submits a resume without authentication', async ({ page }) => {
    await page.goto('http://127.0.0.1:4174')
    await expect(page.getByText('不需註冊或登入')).toBeVisible()
    await expect(page.getByText('登入 HR 工作台')).toHaveCount(0)

    await page.getByRole('button', { name: '直接留下履歷' }).click()
    await page.getByLabel('姓名 *').fill(candidateName)
    await page.getByLabel('Email *').fill('e2e-candidate@example.test')
    await page.getByLabel('手機 *').fill('0912-345-678')
    await page.getByLabel('居住地 *').fill('台北市')
    await page.getByLabel('目前職稱').fill('測試工程師')
    await page.getByLabel('技能').fill('Playwright, TypeScript')
    await page.locator('input[type="file"]').setInputFiles({
      name: resumeName,
      mimeType: 'application/pdf',
      buffer: minimalPdf,
    })
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: '送出履歷' }).click()

    await expect(page.getByRole('heading', { name: '履歷已成功送出' })).toBeVisible()
    await expect(page.getByText(/參考編號：\d+/)).toBeVisible()
  })

  test('HR requires login, admin loads core pages and confirms submitted talent', async ({ page }) => {
    await page.goto('http://127.0.0.1:4173')
    await expect(page.getByRole('heading', { name: '登入 HR 工作台' })).toBeVisible()
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()

    await expect(page.getByRole('heading', { name: '招募工作總覽' })).toBeVisible()
    for (const label of ['智慧配對', '數據報表', '帳號與權限']) {
      await expect(page.getByRole('button', { name: label })).toBeVisible()
    }

    await page.getByRole('button', { name: /履歷匯入與校對/ }).click()
    await page.getByRole('button', { name: new RegExp(resumeName) }).click()
    await expect(page.getByLabel('姓名 *')).toHaveValue(candidateName)
    await page.getByRole('button', { name: '確認並寫入人才庫' }).click()
    await expect(page.getByText(/已建立人才|已更新人才/)).toBeVisible()

    await page.getByRole('button', { name: '人才資料庫' }).click()
    await expect(page.getByRole('button', { name: new RegExp(candidateName) })).toBeVisible()

    await page.getByRole('button', { name: '帳號與權限' }).click()
    await expect(page.getByRole('heading', { name: '帳號與權限' })).toBeVisible()
    await expect(page.getByText('e2e-admin@example.test')).toBeVisible()
  })
})
