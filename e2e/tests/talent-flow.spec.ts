import { expect, test } from '@playwright/test'

const candidateName = '端對端測試人才'
const resumeName = 'talenthub-e2e-resume.pdf'

// The upload validator requires a PDF signature. The parser may mark this tiny
// synthetic document for review; submitted form fields remain the source of truth.
const minimalPdf = Buffer.from('%PDF-1.4\n% synthetic E2E resume - no personal data\n%%EOF\n')

test.describe.serial('public submission to HR review', () => {
  test('talent can join with selections and no resume file', async ({ page }) => {
    await page.goto('http://127.0.0.1:4174')
    await page.getByRole('button', { name: '加入人才庫' }).first().click()
    await page.getByLabel('姓名 *').fill('無履歷測試人才')
    await page.getByLabel('手機（與 Email 擇一）').fill('0912-000-123')
    await page.getByLabel('希望工作地點').selectOption('遠端工作')
    await page.getByLabel('職務類別').selectOption('產品／專案管理')
    await page.getByLabel('工作年資').selectOption({ label: '3–5 年' })
    await page.getByLabel('主要專長').selectOption('專案管理')
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: '加入人才庫', exact: true }).last().click()
    await expect(page.getByRole('heading', { name: '已成功加入人才庫' })).toBeVisible()
    await expect(page.getByText(/參考編號：\d+/)).toBeVisible()
  })

  test('public career page submits a resume without authentication', async ({ page }) => {
    await page.goto('http://127.0.0.1:4174')
    await expect(page.getByText('不需註冊或登入')).toBeVisible()
    await expect(page.getByText('登入 HR 工作台')).toHaveCount(0)

    await page.getByRole('button', { name: '加入人才庫' }).first().click()
    await page.getByLabel('姓名 *').fill(candidateName)
    await page.getByLabel('Email（與手機擇一）').fill('e2e-candidate@example.test')
    await page.getByLabel('希望工作地點').selectOption('台北市')
    await page.getByLabel('職務類別').selectOption('軟體／資訊')
    await page.getByLabel('主要專長').selectOption('軟體開發')
    await page.locator('input[type="file"]').setInputFiles({
      name: resumeName,
      mimeType: 'application/pdf',
      buffer: minimalPdf,
    })
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: '加入人才庫', exact: true }).last().click()

    await expect(page.getByRole('heading', { name: '已成功加入人才庫' })).toBeVisible()
    await expect(page.getByText(/參考編號：\d+/)).toBeVisible()
  })

  test('HR requires login, admin loads core pages and confirms submitted talent', async ({ page }) => {
    await page.goto('http://127.0.0.1:4173')
    await expect(page.getByRole('heading', { name: '登入 HR 工作台' })).toBeVisible()
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()

    await expect(page.getByRole('heading', { name: /今天想認識哪位人才/ })).toBeVisible()
    for (const label of ['媒合程度', '招募分析', '帳號與權限']) {
      await expect(page.getByRole('button', { name: label })).toBeVisible()
    }

    await page.getByRole('button', { name: /履歷辨識中心/ }).click()
    await page.getByRole('button', { name: new RegExp(resumeName) }).click()
    await expect(page.getByLabel('姓名 *')).toHaveValue(candidateName)
    // A synthetic PDF has no verifiable platform signature, so HR must explicitly
    // confirm the detected source before the record can enter the talent pool.
    await page.getByRole('button', { name: '一般／自製履歷', exact: true }).click()
    await page.getByRole('button', { name: '確認並寫入人才庫' }).click()
    await expect(page.getByText(/已建立人才|已更新人才/)).toBeVisible()

    await page.getByRole('button', { name: '人才庫' }).click()
    await expect(page.getByRole('button', { name: new RegExp(candidateName) })).toBeVisible()

    await page.getByRole('button', { name: '帳號與權限' }).click()
    await expect(page.getByRole('heading', { name: '帳號與權限' })).toBeVisible()
    await expect(page.getByText('e2e-admin@example.test')).toBeVisible()
  })

  test('IT can temporarily reveal and re-mask candidate PII with a reason', async ({ page }) => {
    await page.goto('http://127.0.0.1:4173')
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await page.getByRole('button', { name: '帳號與權限' }).click()
    await page.getByRole('tab', { name: '資料表維護' }).click()
    await page.getByRole('button', { name: /人才主檔/ }).click()

    await page.getByRole('button', { name: '顯示個資' }).click()
    await page.getByLabel('查閱原因 *').fill('E2E 驗證 HR 人才同步問題')
    await page.getByRole('button', { name: '確認並顯示' }).click()
    await expect(page.getByRole('button', { name: '重新遮罩' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'name', exact: true })).toBeVisible()

    await page.getByRole('button', { name: '重新遮罩' }).click()
    await expect(page.getByRole('button', { name: '顯示個資' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'name', exact: true })).toHaveCount(0)
  })

  test('department manager creates an own-department job that global recruiting can see', async ({ page }) => {
    await page.goto('http://127.0.0.1:4173')
    await page.getByLabel('帳號或 Email').fill('it_manager')
    await page.getByLabel('密碼').fill('dept123')
    await page.getByRole('button', { name: '登入工作台' }).click()

    await expect(page.getByRole('heading', { name: '資訊技術部' })).toBeVisible()
    await page.getByRole('button', { name: '＋ 建立本部門職缺' }).click()
    await page.getByLabel('職缺名稱 *').fill('E2E 部門雲端工程師')
    await page.getByLabel('工作地點 *').fill('台北市')
    await page.getByLabel('技能條件').fill('Python, AWS, SQL')
    await page.getByLabel('職務說明 *').fill('由部門主管建立並送交 HR 核准的端對端測試職缺。')
    await page.getByRole('button', { name: '建立並送交 HR' }).click()
    await expect(page.getByText(/已寫入資料庫並送交 HR 核准/)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'E2E 部門雲端工程師' })).toBeVisible()

    await page.getByRole('button', { name: /資深後端工程師/ }).click()
    await expect(page.getByText('展示人才－林怡君')).toBeVisible()
    await expect(page.getByRole('button', { name: '人才庫' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '帳號與權限' })).toHaveCount(0)

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await page.getByRole('button', { name: '職缺管理' }).click()
    await expect(page.getByRole('heading', { name: 'E2E 部門雲端工程師' })).toBeVisible()
  })
})
