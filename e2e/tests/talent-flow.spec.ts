import { expect, test } from '@playwright/test'

const candidateName = '端對端測試人才'
const resumeName = 'talenthub-e2e-resume.pdf'
const interviewCandidateName = 'E2E 面試流程人才'
const backendApi = 'http://127.0.0.1:8018/api/v1'

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
    await expect(page.getByTestId('resume-confirmed-summary')).toContainText('本次已入庫 1 份')
    await expect(page.getByRole('button', { name: new RegExp(resumeName) })).toHaveCount(0)

    await page.getByRole('button', { name: '人才庫' }).click()
    await expect(page.getByRole('button', { name: new RegExp(candidateName) })).toBeVisible()

    await page.getByRole('button', { name: '帳號與權限' }).click()
    await expect(page.getByRole('heading', { name: '帳號與權限' })).toBeVisible()
    await expect(page.getByText('e2e-admin@example.test')).toBeVisible()
    const salesAccount = page.locator('tr').filter({ hasText: 'sales' })
    await expect(salesAccount).toBeVisible()
    page.once('dialog', dialog => dialog.accept())
    const passwordReset = page.waitForResponse(response =>
      response.url().includes('/api/v1/admin/users/')
      && response.url().endsWith('/reset-password')
      && response.request().method() === 'POST',
    )
    await salesAccount.getByRole('button', { name: '產生一次性臨時密碼' }).click()
    expect((await passwordReset).status()).toBe(200)
    const temporaryPassword = page.getByTestId('temporary-password-value')
    await expect(page.getByTestId('temporary-password-dialog')).toBeVisible()
    await expect(temporaryPassword).toHaveValue(/^(?=.{24}$).+$/)
    await page.getByTestId('close-temp-password').click()
    await expect(page.getByTestId('temporary-password-dialog')).toHaveCount(0)
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

  test('HR creates a real application and only its department manager can manage the interview', async ({ page, request }) => {
    const adminLogin = await request.post(`${backendApi}/auth/login`, {
      data: { username: 'e2e-admin', password: 'E2E-Admin-Password-123!' },
    })
    expect(adminLogin.ok()).toBeTruthy()
    const adminToken = (await adminLogin.json()).access_token as string
    const createHr = await request.post(`${backendApi}/admin/users`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        username: 'e2e-hr',
        email: 'e2e-hr@example.test',
        password: 'E2E-HR-Password-123!',
        display_name: 'E2E HR',
        role: 'hr',
        department_id: null,
      },
    })
    expect([201, 409]).toContain(createHr.status())

    await page.goto('http://127.0.0.1:4173')
    await page.getByLabel('帳號或 Email').fill('e2e-hr')
    await page.getByLabel('密碼').fill('E2E-HR-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await expect(page.getByRole('heading', { name: /今天想認識哪位人才/ })).toBeVisible()

    await page.getByLabel('姓名 *').fill(interviewCandidateName)
    await page.getByLabel('Email').fill('e2e-interview-candidate@example.test')
    await page.getByLabel('目前職稱').fill('平台工程師')
    const departmentSelect = page.getByTestId('intake-department-select')
    const jobSelect = page.getByTestId('intake-job-select')
    await expect(jobSelect).toBeDisabled()
    await departmentSelect.selectOption({ label: '資訊技術部' })
    await expect(jobSelect).toBeEnabled()
    const targetJobId = await jobSelect.locator('option', { hasText: '資深後端工程師' }).getAttribute('value')
    expect(targetJobId).toBeTruthy()
    await jobSelect.selectOption(targetJobId!)
    await page.getByLabel('招募備註').fill('E2E 建檔後安排技術面試')

    const applicationCreated = page.waitForResponse(response =>
      response.url().endsWith('/api/v1/applications')
      && response.request().method() === 'POST',
    )
    await page.getByTestId('intake-submit').click()
    const createApplicationResponse = await applicationCreated
    expect(createApplicationResponse.status()).toBe(201)
    const application = await createApplicationResponse.json() as {
      id: number
      candidate: { name: string }
      requisition: { title: string; department_name: string | null }
    }
    expect(application.candidate.name).toBe(interviewCandidateName)
    expect(application.requisition.title).toBe('資深後端工程師')
    expect(application.requisition.department_name).toBe('資訊技術部')

    await page.getByTestId('nav-candidates').click()
    await page.getByRole('button', { name: new RegExp(interviewCandidateName) }).click()
    await page.getByTestId('add-shared-activity').click()
    await page.getByTestId('activity-content').fill('HR 留言：已完成初談，請資訊技術部主管確認技術深度。')
    const hrActivitySaved = page.waitForResponse(response =>
      response.url().includes('/api/v1/candidates/')
      && response.url().endsWith('/activities')
      && response.request().method() === 'POST',
    )
    await page.getByTestId('activity-submit').click()
    expect((await hrActivitySaved).status()).toBe(201)
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('HR 留言：已完成初談')
    await page.getByRole('button', { name: '關閉人才詳情' }).click()

    await page.getByTestId('nav-interviews').click()
    await expect(page.getByTestId('interview-management')).toBeVisible()
    const hrApplicationCard = page.getByTestId(`interview-application-${application.id}`)
    await expect(hrApplicationCard).toContainText(interviewCandidateName)
    await hrApplicationCard.getByTestId(`interview-edit-${application.id}-hr`).click()
    const hrInterviewForm = hrApplicationCard.getByTestId(`interview-form-${application.id}-hr`)
    await hrInterviewForm.getByTestId('interview-at-input').fill('2026-08-20T14:30')
    await hrInterviewForm.getByTestId('interview-result-select').selectOption('advance')
    await hrInterviewForm.getByTestId('interview-notes').fill('HR 已確認技術面試，請主管參與。')
    const hrInterviewSaved = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${application.id}/interviews/hr`)
      && response.request().method() === 'PATCH',
    )
    await hrInterviewForm.getByTestId('interview-save').click()
    const hrInterviewResponse = await hrInterviewSaved
    expect(hrInterviewResponse.status()).toBe(200)
    const hrInterview = await hrInterviewResponse.json()
    expect(hrInterview.hr_interview.interview_at).toBeTruthy()
    expect(hrInterview.hr_interview.interview_result).toBe('advance')
    expect(hrInterview.hr_interview.interview_notes).toBe('HR 已確認技術面試，請主管參與。')
    expect(hrInterview.manager_interview.interview_at).toBeNull()
    await expect(page.getByTestId('interview-success')).toContainText(interviewCandidateName)
    await expect(hrApplicationCard).toContainText('HR 已確認技術面試，請主管參與。')

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('it_manager')
    await page.getByLabel('密碼').fill('dept123')
    await page.getByRole('button', { name: '登入工作台' }).click()
    for (const testId of ['nav-candidates', 'nav-resumes', 'nav-interviews']) {
      await expect(page.getByTestId(testId)).toBeVisible()
    }
    await expect(page.getByTestId('nav-admin')).toHaveCount(0)

    await page.getByTestId('nav-candidates').click()
    const managerCandidate = page.getByRole('button', { name: new RegExp(interviewCandidateName) })
    await expect(managerCandidate).toBeVisible()
    await managerCandidate.click()
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('HR 留言：已完成初談')
    await page.getByTestId('add-shared-activity').click()
    await page.getByTestId('activity-content').fill('主管留言：技術面試將加強系統設計與協作能力確認。')
    const managerActivitySaved = page.waitForResponse(response =>
      response.url().includes('/api/v1/candidates/')
      && response.url().endsWith('/activities')
      && response.request().method() === 'POST',
    )
    await page.getByTestId('activity-submit').click()
    expect((await managerActivitySaved).status()).toBe(201)
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('主管留言：技術面試將加強')
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('資訊技術部主管')
    await page.getByRole('button', { name: '關閉人才詳情' }).click()
    await page.getByTestId('nav-resumes').click()
    await expect(page.getByRole('heading', { name: '新增履歷並指派職缺' })).toBeVisible()
    await page.getByTestId('nav-interviews').click()
    const managerApplicationCard = page.getByTestId(`interview-application-${application.id}`)
    await expect(managerApplicationCard).toContainText(interviewCandidateName)
    await expect(managerApplicationCard).toContainText('HR 已確認技術面試，請主管參與。')
    await managerApplicationCard.getByTestId(`interview-edit-${application.id}-manager`).click()
    const managerInterviewForm = managerApplicationCard.getByTestId(`interview-form-${application.id}-manager`)
    await managerInterviewForm.getByTestId('interview-at-input').fill('2026-08-21T10:00')
    await managerInterviewForm.getByTestId('interview-result-select').selectOption('hold')
    await managerInterviewForm.getByTestId('interview-notes').fill('資訊技術部主管已完成初談，暫列保留。')
    const managerInterviewSaved = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/applications/${application.id}/interviews/manager`)
      && response.request().method() === 'PATCH',
    )
    await managerInterviewForm.getByTestId('interview-save').click()
    const managerInterviewResponse = await managerInterviewSaved
    expect(managerInterviewResponse.status()).toBe(200)
    const managerInterview = await managerInterviewResponse.json()
    expect(managerInterview.hr_interview.interview_notes).toBe('HR 已確認技術面試，請主管參與。')
    expect(managerInterview.manager_interview.interview_result).toBe('hold')
    expect(managerInterview.manager_interview.interview_notes).toBe('資訊技術部主管已完成初談，暫列保留。')
    await expect(page.getByTestId('interview-success')).toContainText(interviewCandidateName)

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('e2e-hr')
    await page.getByLabel('密碼').fill('E2E-HR-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await page.getByTestId('nav-candidates').click()
    await page.getByRole('button', { name: new RegExp(interviewCandidateName) }).click()
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('主管留言：技術面試將加強')
    await expect(page.getByTestId('shared-activity-timeline')).toContainText('資訊技術部主管')
    await page.getByRole('button', { name: '關閉人才詳情' }).click()

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('design')
    await page.getByLabel('密碼').fill('dept123')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await page.getByTestId('nav-interviews').click()
    await expect(page.getByTestId('interview-management')).toBeVisible()
    await expect(page.getByTestId(`interview-application-${application.id}`)).toHaveCount(0)
    await expect(page.getByText(interviewCandidateName, { exact: true })).toHaveCount(0)
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
    await page.getByLabel('職務說明（JD）*').fill('由部門主管建立並送交 HR 核准的端對端測試職缺。')
    await page.getByRole('button', { name: '建立並送交 HR' }).click()
    await expect(page.getByText(/已建立並送交 HR 核准/)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'E2E 部門雲端工程師' })).toBeVisible()

    await page.getByRole('button', { name: /資深後端工程師/ }).click()
    await expect(page.getByText('展示人才－林怡君')).toBeVisible()
    for (const testId of ['nav-candidates', 'nav-resumes', 'nav-interviews']) {
      await expect(page.getByTestId(testId)).toBeVisible()
    }
    await expect(page.getByTestId('nav-admin')).toHaveCount(0)

    await page.getByRole('button', { name: '登出' }).click()
    await page.getByLabel('帳號或 Email').fill('e2e-admin')
    await page.getByLabel('密碼').fill('E2E-Admin-Password-123!')
    await page.getByRole('button', { name: '登入工作台' }).click()
    await page.getByRole('button', { name: '職缺管理' }).click()
    await expect(page.getByRole('heading', { name: 'E2E 部門雲端工程師' })).toBeVisible()
  })
})
